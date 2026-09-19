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
| `databricks.yml`, `resources/` | Databricks Asset Bundle: jobs, and later the index and app |
| `src/juno/` | Importable core: config, counting, retrieval, baseline, agent |
| `src/notebooks/` | Notebooks run by the jobs, in Databricks source format |
| `sql/` | One-off DDL for the catalog, schema and volume |
| `eval/` | Question templates and the LLM-judge rubric |
| `tests/` | Local unit tests that need no workspace |
| `docs/` | The submitted design document |

## Running it

Prerequisites: Databricks CLI v1.9.0+ authenticated against a workspace with Unity Catalog, a
serverless SQL warehouse, and Vector Search.

```bash
# one-off: create the catalog, schema and volume (see sql/00_setup.sql for the equivalent DDL)
databricks catalogs create juno
databricks schemas create restaurant juno
databricks volumes create juno restaurant raw MANAGED

# deploy and run
databricks bundle validate
databricks bundle deploy -t dev
databricks bundle run ingest -t dev
```

## Licence

MIT, see [LICENSE](LICENSE). The MEMD-ABSA dataset is the property of its authors and is not
included in this repository.
