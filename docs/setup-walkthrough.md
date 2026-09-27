# How Juno's environment was built, step by step

A walkthrough of everything `infra/setup.sh` does and why each piece exists. Read it top to bottom
once and the Databricks governance model should click.

## The mental model first

Five things, and people mix them up constantly:

| Thing | What it is | Juno's |
|---|---|---|
| **Azure subscription** | Where you are billed | `ai_eng_prod` |
| **Workspace** | The Databricks UI and compute you log into. A workspace is an Azure resource. | `db-ws-juno` |
| **Metastore** | The catalog of catalogs. **One per region, shared by every workspace in it.** | `metastore_azure_eastus` |
| **Catalog** | A named container for schemas and tables | `juno` |
| **Storage account** | Where the bytes actually land, in Azure | `sajunoprod` |

The path a query takes:

```
you → workspace (db-ws-juno) → metastore (checks: are you allowed?)
    → catalog juno → external location → storage credential
    → access connector's managed identity → storage account sajunoprod
```

Every arrow is a permission check. That is the whole point of Unity Catalog: the table name and the
storage path are separate things, and access is granted on the name, not the path.

## Why we rebuilt instead of continuing

Juno started in `db-ws-demo`, a workspace created for an earlier course, on that workspace's own
managed storage. It worked, but the project's data lived in someone else's house. So we gave Juno a
workspace and a storage account of its own.

**The metastore is still shared**, and it cannot be otherwise: it is regional, so both workspaces
attach to `metastore_azure_eastus`. That is why the last step binds the catalog — see step 9.

## The Azure half

### 1. Resource group — `rg-juno-prod`
A folder for Azure resources. Everything Juno needs goes in here, so teardown is one command:
`az group delete -n rg-juno-prod`.

### 2. Workspace — `db-ws-juno`
```bash
az databricks workspace create -n db-ws-juno -g rg-juno-prod -l eastus \
  --sku premium --managed-resource-group mrg-juno-prod
```
- **premium**: Unity Catalog, model serving and apps need it. Standard cannot do this project.
- **Hybrid compute mode** (the default, so not passed): a *Serverless*-mode workspace cannot use
  access connectors or a custom catalog storage root, which the rest of this setup depends on.
  Hybrid still runs serverless jobs, SQL warehouses, model serving and apps — it only means the
  workspace *can also* have classic compute.
- **managed resource group**: Azure creates a second resource group (`mrg-juno-prod`) that Databricks
  owns, holding the workspace's own managed storage and networking. Do not edit things inside it.
- Takes 10–15 minutes. Costs nothing while idle; you pay for compute when it runs.

### 3. Storage account — `sajunoprod`
```bash
az storage account create -n sajunoprod -g rg-juno-prod -l eastus \
  --sku Standard_LRS --kind StorageV2 \
  --enable-hierarchical-namespace true --min-tls-version TLS1_2 --allow-blob-public-access false
```
- **`--enable-hierarchical-namespace true`** is the one that matters: it makes this ADLS Gen2 rather
  than plain blob storage. Real directories, real rename, and it is what Unity Catalog requires.
  It **cannot be turned on later**, so getting it right at creation matters.
- `Standard_LRS` is the cheapest redundancy (three copies in one datacentre). Fine for a capstone.
- TLS 1.2 minimum and no public blob access are basic hygiene a reviewer will look for.

### 4. Container — `juno`
A container is the top-level folder. The catalog's storage root becomes
`abfss://juno@sajunoprod.dfs.core.windows.net/`. `abfss` is the ADLS Gen2 protocol, and the part
before `@` is the container.

### 5. Access connector — `ac-juno-prod`
```bash
az databricks access-connector create -n ac-juno-prod -g rg-juno-prod -l eastus \
  --identity-type SystemAssigned
```
This is the important idea. Databricks needs to read and write your storage, and the bad way to
arrange that is to hand it a key or a password. Instead:

- The access connector is an Azure resource with a **managed identity** — an identity Azure creates
  and rotates, whose credentials nobody ever sees, not even you.
- Databricks is allowed to act as that identity.
- You grant *that identity* access to the storage.

No secret exists anywhere, so no secret can leak. This is why the design doc can say keys live in
one place and never in code.

### 6. Role assignment
```bash
az role assignment create --assignee-object-id <the connector's principalId> \
  --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Contributor" --scope <the storage account>
```
Azure has two layers of permission, and this trips everyone up:

- **Control plane** ("Owner", "Contributor") lets you manage the storage account: create it, delete
  it, read its keys.
- **Data plane** ("Storage Blob Data Contributor") lets you read and write the *files inside it*.

Being Owner does **not** give you data access. This line grants the connector's identity the data
role, scoped to this one storage account and nothing else. It takes a minute or two to propagate,
which is why a validation straight afterwards sometimes needs a retry.

## The Databricks half

### 7. Sign in — profile `JUNO`
```bash
databricks auth login --host https://adb-7405616821600861.1.azuredatabricks.net -p JUNO
```
Writes an OAuth profile into `~/.databrickscfg`. Every later command passes `-p JUNO` to say which
workspace it means. `DEFAULT` still points at the old workspace, untouched, which is how both can
coexist.

### 8. Storage credential, external location, catalog

Three objects, each wrapping the last:

```
cred_juno         "Unity Catalog may act as this managed identity"
  └── extloc_juno "…and that identity may be used for abfss://juno@sajunoprod…"
        └── catalog juno   "…and this catalog stores its data there"
```

```bash
databricks -p JUNO storage-credentials create --json '{"name":"cred_juno", ...}'
databricks -p JUNO external-locations create extloc_juno abfss://juno@sajunoprod.dfs.core.windows.net/ cred_juno
databricks -p JUNO catalogs create juno --storage-root abfss://juno@sajunoprod.dfs.core.windows.net/
```

Creating the external location **validates** the whole chain by actually writing a test file. If the
role assignment from step 6 has not propagated, this is where it fails — and that failure is useful,
so never pass `--skip-validation` to get past it.

Then the schema (`juno.restaurant`, a folder for tables) and the volume (`raw`, a folder for files
rather than tables — the downloaded dataset goes there).

**A catalog's storage root is fixed when it is created.** That is why the catalog had to be deleted
and recreated rather than edited. Safe here because it held no data; the script counts tables first
and refuses if it finds any.

### 9. Isolation and binding
```bash
databricks -p JUNO catalogs update juno --isolation-mode ISOLATED
databricks -p JUNO workspace-bindings update-bindings catalog juno \
  --json '{"add":[{"workspace_id":7405616821600861,"binding_type":"BINDING_TYPE_READ_WRITE"}]}'
```
Because the metastore is shared, a new catalog is visible from *every* workspace in the region by
default (`isolation_mode: OPEN`). These two commands say "isolated, and only this workspace may see
it". Verified by listing catalogs from the old workspace: `juno` is no longer there.

This is exactly how a real client separates environments that share a metastore.

## The bundle

A Databricks Asset Bundle is infrastructure-as-code for jobs, pipelines and apps. `databricks.yml`
declares them; `bundle deploy` makes the workspace match.

```bash
databricks -p JUNO bundle validate      # config correct?
databricks -p JUNO bundle deploy -t dev # upload files, create/update jobs
databricks -p JUNO bundle run data -t dev
```

- **Targets** are environments. `dev` runs in *development mode*, which prefixes every job with
  `[dev your_name]` and pauses schedules, so experiments cannot be mistaken for the real thing.
- **`bundle destroy`** deletes what the bundle created in that target. We used it deliberately on the
  old workspace to clean up, *before* switching the host — otherwise it would have pointed at the
  new one.
- Catalog, schema and volume are deliberately **not** bundle resources: in development mode their
  names would be prefixed too, and a destroy would take the data with it.
- `.gitignore` also controls what `bundle deploy` uploads. A file you ignore silently never reaches
  the workspace, which is a confusing failure the first time it bites.

## How we knew it worked

`./infra/setup.sh verify` checks each link in the chain, ending with the one that matters:

```bash
databricks -p JUNO fs cp local.txt dbfs:/Volumes/juno/restaurant/raw/_setup_check.txt
databricks -p JUNO fs rm  dbfs:/Volumes/juno/restaurant/raw/_setup_check.txt
```

A write that lands in `sajunoprod` proves the catalog, external location, credential, managed
identity and role assignment are all correct — and it needs no cluster, so it costs nothing.

## Glossary

| Term | Meaning |
|---|---|
| **ADLS Gen2** | Azure storage with real directories. Enabled by "hierarchical namespace". |
| **abfss://** | The protocol for reaching ADLS Gen2, encrypted |
| **Managed identity** | An Azure identity with no password, which Azure rotates itself |
| **Access connector** | The Azure resource that lets Databricks act as a managed identity |
| **Storage credential** | Unity Catalog's reference to that connector |
| **External location** | A credential plus a path: "this identity, for this container" |
| **Storage root** | Where a catalog's managed tables are written |
| **Volume** | A folder for files inside a schema, for things that are not tables |
| **Isolation mode / binding** | Which workspaces can see a catalog |
| **DAB** | Databricks Asset Bundle: jobs and apps as code |
