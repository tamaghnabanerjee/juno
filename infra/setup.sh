#!/usr/bin/env bash
#
# Project Juno — environment setup.
#
# Creates a dedicated Azure Databricks workspace, a dedicated ADLS Gen2 storage account, and the
# Unity Catalog objects Juno writes into. Every step checks whether the thing already exists, so
# re-running is a no-op rather than an error.
#
#   ./infra/setup.sh azure    # resource group, workspace, storage, access connector, role
#   ./infra/setup.sh login    # prints the sign-in command you run yourself (OAuth needs a browser)
#   ./infra/setup.sh unity    # storage credential, external location, catalog, schema, volume
#   ./infra/setup.sh verify   # checks everything is usable
#   ./infra/setup.sh all      # azure -> login hint -> unity -> verify
#
# Requires: az CLI (logged in), databricks CLI >= 1.9.0.
# See infra/README.md for what this costs and how to tear it down.

set -euo pipefail

# ---------------------------------------------------------------------------- names
LOCATION="${LOCATION:-eastus}"
RG="${RG:-rg-juno-prod}"
WS="${WS:-db-ws-juno}"
MRG="${MRG:-mrg-juno-prod}"
SA="${SA:-sajunoprod}"
CONTAINER="${CONTAINER:-juno}"
CONNECTOR="${CONNECTOR:-ac-juno-prod}"

PROFILE="${PROFILE:-JUNO}"
CRED="${CRED:-cred_juno}"
EXTLOC="${EXTLOC:-extloc_juno}"
CATALOG="${CATALOG:-juno}"
SCHEMA="${SCHEMA:-restaurant}"
VOLUME="${VOLUME:-raw}"

STORAGE_ROOT="abfss://${CONTAINER}@${SA}.dfs.core.windows.net/"

# ---------------------------------------------------------------------------- helpers
bold() { printf '\033[1m%s\033[0m\n' "$*"; }
step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
ok()   { printf '    \033[32mok\033[0m  %s\n' "$*"; }
skip() { printf '    --  %s (already exists)\n' "$*"; }
warn() { printf '    \033[33m!\033[0m   %s\n' "$*"; }
die()  { printf '\n\033[31mstopped:\033[0m %s\n' "$*" >&2; exit 1; }

require() { command -v "$1" >/dev/null 2>&1 || die "$1 is not installed"; }

dbx() { databricks -p "$PROFILE" "$@"; }

# ---------------------------------------------------------------------------- azure
stage_azure() {
  require az
  az account show >/dev/null 2>&1 || die "az is not logged in. Run: az login"
  bold "Subscription: $(az account show --query name -o tsv)"

  step "Resource group $RG"
  if az group show -n "$RG" >/dev/null 2>&1; then skip "$RG"; else
    az group create -n "$RG" -l "$LOCATION" -o none
    ok "created $RG in $LOCATION"
  fi

  step "Databricks workspace $WS (premium, Hybrid compute mode)"
  # Hybrid, not Serverless: a Serverless-mode workspace cannot use access connectors or a custom
  # catalog storage root, which this setup depends on. Hybrid still runs serverless jobs,
  # SQL warehouses, model serving and apps.
  if az databricks workspace show -n "$WS" -g "$RG" >/dev/null 2>&1; then skip "$WS"; else
    warn "this takes 10-15 minutes"
    az databricks workspace create -n "$WS" -g "$RG" -l "$LOCATION" \
      --sku premium --managed-resource-group "$MRG" -o none
    ok "created $WS"
  fi
  WS_URL="$(az databricks workspace show -n "$WS" -g "$RG" --query workspaceUrl -o tsv)"
  WS_ID="$(az databricks workspace show -n "$WS" -g "$RG" --query workspaceId -o tsv)"
  ok "https://${WS_URL} (id ${WS_ID})"

  step "Storage account $SA (ADLS Gen2)"
  if az storage account show -n "$SA" -g "$RG" >/dev/null 2>&1; then skip "$SA"; else
    az storage account create -n "$SA" -g "$RG" -l "$LOCATION" \
      --sku Standard_LRS --kind StorageV2 \
      --enable-hierarchical-namespace true \
      --min-tls-version TLS1_2 \
      --allow-blob-public-access false -o none
    ok "created $SA"
  fi
  SA_ID="$(az storage account show -n "$SA" -g "$RG" --query id -o tsv)"

  step "Container $CONTAINER"
  local key
  key="$(az storage account keys list -g "$RG" -n "$SA" --query "[0].value" -o tsv)"
  if [ "$(az storage fs exists -n "$CONTAINER" --account-name "$SA" --account-key "$key" --query exists -o tsv)" = "true" ]; then
    skip "$CONTAINER"
  else
    az storage fs create -n "$CONTAINER" --account-name "$SA" --account-key "$key" -o none
    ok "created $CONTAINER"
  fi

  step "Access connector $CONNECTOR"
  if az databricks access-connector show -n "$CONNECTOR" -g "$RG" >/dev/null 2>&1; then
    skip "$CONNECTOR"
  else
    az databricks access-connector create -n "$CONNECTOR" -g "$RG" -l "$LOCATION" \
      --identity-type SystemAssigned -o none
    ok "created $CONNECTOR"
  fi
  CONNECTOR_ID="$(az databricks access-connector show -n "$CONNECTOR" -g "$RG" --query id -o tsv)"
  PRINCIPAL_ID="$(az databricks access-connector show -n "$CONNECTOR" -g "$RG" --query identity.principalId -o tsv)"

  step "Role assignment: Storage Blob Data Contributor on $SA"
  if [ -n "$(az role assignment list --assignee-object-id "$PRINCIPAL_ID" --scope "$SA_ID" \
             --query "[?roleDefinitionName=='Storage Blob Data Contributor'].id" -o tsv 2>/dev/null)" ]; then
    skip "role already assigned"
  else
    if az role assignment create --assignee-object-id "$PRINCIPAL_ID" \
         --assignee-principal-type ServicePrincipal \
         --role "Storage Blob Data Contributor" --scope "$SA_ID" -o none 2>/dev/null; then
      ok "assigned (allow a minute or two to propagate)"
    else
      warn "could not assign the role - you likely lack Owner / User Access Administrator"
      cat <<EOF

    Assign it in the portal instead, then re-run this stage:
      1. Azure portal -> Storage accounts -> $SA
      2. Access Control (IAM) -> Add -> Add role assignment
      3. Role: Storage Blob Data Contributor -> Next
      4. Assign access to: Managed identity -> Select members
      5. Managed identity: Access connector for Azure Databricks -> $CONNECTOR -> Select
      6. Review + assign

EOF
      die "role assignment is required before the unity stage"
    fi
  fi

  step "Next"
  cat <<EOF
    Sign in to the new workspace (this needs a browser, so run it yourself):

      databricks auth login --host https://${WS_URL} -p ${PROFILE}

    Then: ./infra/setup.sh unity
EOF
}

# ---------------------------------------------------------------------------- login hint
stage_login() {
  local url
  url="$(az databricks workspace show -n "$WS" -g "$RG" --query workspaceUrl -o tsv)"
  bold "databricks auth login --host https://${url} -p ${PROFILE}"
}

# ---------------------------------------------------------------------------- unity catalog
stage_unity() {
  require databricks
  require az
  dbx current-user me >/dev/null 2>&1 || die "profile $PROFILE cannot reach the workspace. Run: $0 login"

  local connector_id ws_id
  connector_id="$(az databricks access-connector show -n "$CONNECTOR" -g "$RG" --query id -o tsv)"
  ws_id="$(az databricks workspace show -n "$WS" -g "$RG" --query workspaceId -o tsv)"

  step "Storage credential $CRED"
  if dbx storage-credentials get "$CRED" >/dev/null 2>&1; then skip "$CRED"; else
    # With --json the CLI takes every field in the payload, including the name.
    dbx storage-credentials create --json "$(cat <<JSON
{"name": "${CRED}",
 "comment": "Access connector ${CONNECTOR}, used by the ${CATALOG} catalog",
 "azure_managed_identity": {"access_connector_id": "${connector_id}"}}
JSON
)" >/dev/null
    ok "created $CRED"
  fi

  step "External location $EXTLOC -> $STORAGE_ROOT"
  if dbx external-locations get "$EXTLOC" >/dev/null 2>&1; then skip "$EXTLOC"; else
    # Creation validates the credential. If the role assignment has not propagated yet this fails;
    # wait a minute and re-run rather than passing --skip-validation.
    dbx external-locations create "$EXTLOC" "$STORAGE_ROOT" "$CRED" \
      --comment "Storage root for the $CATALOG catalog" >/dev/null
    ok "created $EXTLOC"
  fi

  step "Catalog $CATALOG on $STORAGE_ROOT"
  if dbx catalogs get "$CATALOG" >/dev/null 2>&1; then
    local root
    root="$(dbx catalogs get "$CATALOG" -o json | python3 -c 'import sys,json;print(json.load(sys.stdin).get("storage_root",""))')"
    if [ "$root" = "${STORAGE_ROOT%/}" ] || [ "$root" = "$STORAGE_ROOT" ]; then
      skip "$CATALOG already on the right storage root"
    else
      warn "$CATALOG exists on a different storage root:"
      warn "  $root"
      # A catalog's storage root is fixed at creation, so moving it means recreating the catalog.
      # Only safe while it holds no data, so count tables across every schema first.
      local tables=0 s
      for s in $(dbx schemas list "$CATALOG" -o json | python3 -c 'import sys,json;[print(x["name"]) for x in json.load(sys.stdin) if x["name"]!="information_schema"]'); do
        tables=$(( tables + $(dbx tables list "$CATALOG" "$s" -o json | python3 -c 'import sys,json;print(len(json.load(sys.stdin) or []))') ))
      done
      [ "$tables" -eq 0 ] || die "$CATALOG holds $tables table(s). Refusing to recreate it - move or drop the data first."
      ok "catalog is empty ($tables tables), recreating it"
      dbx catalogs delete "$CATALOG" --force
      dbx catalogs create "$CATALOG" --storage-root "$STORAGE_ROOT" \
        --comment "Project Juno - review analytics with exact counts (AI Engineering capstone)" >/dev/null
      ok "recreated $CATALOG"
    fi
  else
    dbx catalogs create "$CATALOG" --storage-root "$STORAGE_ROOT" \
      --comment "Project Juno - review analytics with exact counts (AI Engineering capstone)" >/dev/null
    ok "created $CATALOG"
  fi

  step "Schema $CATALOG.$SCHEMA and volume $VOLUME"
  if dbx schemas get "${CATALOG}.${SCHEMA}" >/dev/null 2>&1; then skip "$SCHEMA"; else
    dbx schemas create "$SCHEMA" "$CATALOG" \
      --comment "Bronze, silver and gold tables, evaluation datasets and the vector index" >/dev/null
    ok "created $SCHEMA"
  fi
  if dbx volumes read "${CATALOG}.${SCHEMA}.${VOLUME}" >/dev/null 2>&1; then skip "$VOLUME"; else
    dbx volumes create "$CATALOG" "$SCHEMA" "$VOLUME" MANAGED \
      --comment "Raw MEMD-ABSA download; the dataset is not redistributed in the repository" >/dev/null
    ok "created $VOLUME"
  fi

  step "Bind $CATALOG to workspace $WS only"
  # ISOLATED plus a binding means other workspaces on this regional metastore cannot see the catalog.
  dbx catalogs update "$CATALOG" --isolation-mode ISOLATED >/dev/null
  dbx workspace-bindings update-bindings catalog "$CATALOG" \
    --json "{\"add\":[{\"workspace_id\":${ws_id},\"binding_type\":\"BINDING_TYPE_READ_WRITE\"}]}" >/dev/null
  ok "bound to workspace ${ws_id}"
}

# ---------------------------------------------------------------------------- verify
stage_verify() {
  require databricks
  local failures=0
  check() { if eval "$2" >/dev/null 2>&1; then ok "$1"; else warn "FAILED: $1"; failures=$((failures+1)); fi; }

  step "Azure"
  check "workspace $WS provisioned" \
    "[ \"\$(az databricks workspace show -n $WS -g $RG --query provisioningState -o tsv)\" = Succeeded ]"
  check "storage $SA has hierarchical namespace" \
    "[ \"\$(az storage account show -n $SA -g $RG --query isHnsEnabled -o tsv)\" = true ]"

  step "Workspace"
  check "profile $PROFILE authenticated" "dbx current-user me"
  check "metastore assigned" "dbx metastores current"
  check "a SQL warehouse exists" \
    "[ \"\$(dbx warehouses list -o json | python3 -c 'import sys,json;print(len(json.load(sys.stdin) or []))')\" -gt 0 ]"
  check "foundation model endpoints available" \
    "dbx serving-endpoints list -o json | grep -q databricks-gte-large-en"

  step "Unity Catalog"
  check "external location $EXTLOC" "dbx external-locations get $EXTLOC"
  check "catalog $CATALOG on $SA" "dbx catalogs get $CATALOG -o json | grep -q '$SA'"
  check "volume $CATALOG.$SCHEMA.$VOLUME" "dbx volumes read ${CATALOG}.${SCHEMA}.${VOLUME}"

  step "Write test (no compute needed)"
  local tmp="/tmp/juno-write-test.txt"
  echo "juno setup write test" > "$tmp"
  if dbx fs cp "$tmp" "dbfs:/Volumes/${CATALOG}/${SCHEMA}/${VOLUME}/_setup_check.txt" --overwrite >/dev/null 2>&1 \
     && dbx fs rm "dbfs:/Volumes/${CATALOG}/${SCHEMA}/${VOLUME}/_setup_check.txt" >/dev/null 2>&1; then
    ok "wrote and removed a file through the managed identity"
  else
    warn "FAILED: could not write to the volume - check the role assignment has propagated"
    failures=$((failures+1))
  fi
  rm -f "$tmp"

  echo
  [ "$failures" -eq 0 ] && bold "All checks passed." || die "$failures check(s) failed"
}

# ---------------------------------------------------------------------------- main
case "${1:-}" in
  azure)  stage_azure ;;
  login)  stage_login ;;
  unity)  stage_unity ;;
  verify) stage_verify ;;
  all)    stage_azure; stage_unity; stage_verify ;;
  *)      sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
