# Project Juno

An agent that answers questions about customer reviews with **exact counts and cited examples**.

A standard RAG chatbot answers "how many" questions from roughly 20 retrieved sentences, so every
count it gives describes a sample rather than the whole corpus. Juno counts with SQL over every
labelled row instead, and uses filtered search only to fetch the examples behind a "why" answer.

The repository contains both approaches and the evaluation that compares them:

- **A — baseline:** vector search returns the top 20 sentences; the LLM answers from those.
- **B — Juno agent:** a LangGraph loop where the LLM picks `count_sql` (a fixed query template over
  `review_facts`) and/or `find_examples` (filtered vector search, at most 10 sentences), checks every
  number against the SQL result, retries once, and cites sentence IDs.

**Data:** [MEMD-ABSA](https://github.com/NUSTM/MEMD-ABSA) Restaurant (Cai et al., 2023) — 5,152
English review sentences with 8,496 human labels over 12 categories. The dataset is downloaded at
run time and is not redistributed here. The human labels are the ground truth for every count.

**Platform:** Azure Databricks — Unity Catalog, `ai_query` batch tagging, Vector Search, Model
Serving, MLflow 3, and a Databricks App for the chat UI.

## Status

Build in progress (capstone build phase, 19–27 Sep 2026). Results, the A-vs-B comparison table and
the failure analysis land here as they are produced.

## Repository layout

| Path | Contents |
|---|---|
| `infra/` | One-command setup of the workspace, storage and Unity Catalog objects |
| `databricks.yml`, `resources/` | Databricks Asset Bundle: jobs, and later the index and app |
| `src/juno/` | Importable core: config, counting, retrieval, baseline, agent |
| `src/notebooks/` | Notebooks run by the jobs, in Databricks source format |
| `sql/` | One-off DDL for the catalog, schema and volume |
| `eval/` | Question templates and the LLM-judge rubric |
| `tests/` | Local unit tests that need no workspace |
| `docs/` | The submitted design document |

## Running it

Prerequisites: the [az CLI](https://learn.microsoft.com/cli/azure/) logged in to an Azure
subscription, and the [Databricks CLI](https://docs.databricks.com/dev-tools/cli/) v1.9.0+.

```bash
# one-off: workspace, storage, access connector, catalog, schema, volume
./infra/setup.sh azure           # Azure resources (10-15 min)
./infra/setup.sh login           # prints the sign-in command to run
./infra/setup.sh unity           # Unity Catalog objects on the new storage
./infra/setup.sh verify          # checks everything is usable

# deploy and run
databricks -p JUNO bundle validate
databricks -p JUNO bundle deploy -t dev
databricks -p JUNO bundle run ingest -t dev
```

See [infra/README.md](infra/README.md) for what the setup creates, what it costs, and how to tear it
down. `sql/00_setup.sql` holds the same catalog DDL for anyone who prefers a SQL editor.

## Documentation

| Document | What it covers |
|---|---|
| [docs/data-model.md](docs/data-model.md) | Every table, which notebook writes it, and which are used for answering versus grading |
| [docs/setup-walkthrough.md](docs/setup-walkthrough.md) | How the environment was built, step by step, and why each piece exists |
| [docs/design-doc.pdf](docs/design-doc.pdf) | The submitted design document |

## Licence

MIT, see [LICENSE](LICENSE). The MEMD-ABSA dataset is the property of its authors and is not
included in this repository.
