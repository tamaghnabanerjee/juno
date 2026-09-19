# Infrastructure

`setup.sh` builds the whole environment Juno runs in, from an empty Azure subscription to a Unity
Catalog schema ready for data. Every step checks whether the thing already exists, so re-running is
safe.

```bash
./infra/setup.sh azure     # Azure resources (10-15 min, mostly workspace creation)
./infra/setup.sh login     # prints the sign-in command for you to run
./infra/setup.sh unity     # Unity Catalog objects on the new storage
./infra/setup.sh verify    # checks everything is usable
```

Prerequisites: [az CLI](https://learn.microsoft.com/cli/azure/) logged in with rights to create
resources and role assignments, and the [Databricks CLI](https://docs.databricks.com/dev-tools/cli/)
v1.9.0 or later.

## What it creates

| Resource | Default name | Purpose |
|---|---|---|
| Resource group | `rg-juno-prod` | Holds everything below |
| Databricks workspace | `db-ws-juno` | Premium, **Hybrid** compute mode |
| Storage account | `sajunoprod` | ADLS Gen2, TLS 1.2, no public blob access |
| Container | `juno` | The catalog's storage root |
| Access connector | `ac-juno-prod` | System-assigned managed identity |
| Role assignment | — | Storage Blob Data Contributor for that identity, on the storage account |
| Storage credential | `cred_juno` | Unity Catalog's handle on the access connector |
| External location | `extloc_juno` | `abfss://juno@sajunoprod.dfs.core.windows.net/` |
| Catalog / schema / volume | `juno` / `juno.restaurant` / `raw` | Where the project's data lives |

Every name is a variable at the top of the script, so a different project can reuse it:

```bash
RG=rg-demo-prod WS=db-ws-demo2 SA=sademoprod CATALOG=demo ./infra/setup.sh all
```

**Hybrid, not Serverless compute mode.** A Serverless-mode workspace cannot use access connectors or
a custom catalog storage root, which this setup depends on. Hybrid still runs serverless jobs, SQL
warehouses, model serving and apps.

## Cost

An idle workspace and an access connector cost nothing. Storage is Standard_LRS, a few cents a month
for this dataset. Everything expensive (SQL warehouse, model endpoints, Vector Search) is started by
later steps, not by this script.

## If the role assignment fails

Creating a role assignment needs Owner or User Access Administrator on the subscription. If the
script cannot do it, it prints portal steps and stops before the Unity Catalog stage. Assign
**Storage Blob Data Contributor** to the access connector's managed identity on the storage account,
then re-run `./infra/setup.sh azure`.

Role assignments take a minute or two to propagate. If the external location fails to validate on the
first try, wait and re-run `./infra/setup.sh unity` rather than skipping validation.

## Tearing it down

```bash
databricks -p JUNO catalogs delete juno --force     # data first
databricks -p JUNO external-locations delete extloc_juno
databricks -p JUNO storage-credentials delete cred_juno
az group delete -n rg-juno-prod --yes               # workspace, storage, connector
```

The first command deletes every table and file in the catalog. There is no undo.
