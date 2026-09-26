# Project reference — what everything is and why it exists

A map of the project: every table, every column, every file. Read this if you want to know what a
thing is for, or where to change something.

For the narrative version of how the environment was built, see
[setup-walkthrough.md](setup-walkthrough.md). For the answering-versus-grading split, see
[data-model.md](data-model.md).

---

# Part 1 — The idea in one page

Someone asks *"what share of complaints are about service?"* A normal AI chatbot searches for
relevant reviews, gets the best 20, reads them and answers. But there are 5,152 review sentences, so
any number it gives describes those 20 — it is guessing.

Juno does the reading **once, in advance**. An LLM reads all 5,152 sentences and records what each is
about ("negative about service"). That becomes a table, and counting a table is exact arithmetic.

The project measures two approaches against each other:

| | What it does | Expected weakness |
|---|---|---|
| **A — baseline** | Search the 20 closest sentences, let the LLM answer from them | Counts describe a sample |
| **B — Juno** | Per question: count with SQL, or fetch examples; check every number; cite sentences | Slower, costs more |

Both are asked the same 98 questions, whose correct answers are known because researchers
hand-labelled the sentences. 28 questions are visible during development; 70 stay sealed until the
final run.

---

# Part 2 — The tables

All live in Unity Catalog under `juno.restaurant`, on the `sajunoprod` storage account.

## Pipeline at a glance

```
GitHub JSON
    │ 01_ingest
    ▼
raw_sentences ──┬─ 02_curate ─▶ sentences ────┬─▶ vector index (step 4) ─▶ examples
  (bronze)      │                (5,152)      │
                │                             └─▶ ai_query (step 3) ─▶ review_facts ─▶ Juno counts
                └─ 02_curate ─▶ human_labels ──▶ 03_build_questions ─▶ eval_questions ─▶ grading
                                 (6,547)                          (98)
```

## `raw_sentences` — bronze ✅

The dataset exactly as downloaded. Never queried by the project; it exists so anything dropped
downstream can be recovered without re-downloading.

| Column | Type | Meaning |
|---|---|---|
| `raw_words` | string | The review sentence |
| `quadruples` | array&lt;struct&gt; | Human annotations, nested: aspect, category, opinion, sentiment |
| `task` | string | Upstream annotation task name (`ACOS`); constant |
| `source_split` | string | `Train` / `Dev` / `Test` as published |
| `ingested_at` | timestamp | When this load ran |

**Rows:** 5,152. **Written by:** `01_ingest.py`. **Read by:** `02_curate.py` only.

## `sentences` — silver ✅

The corpus. One row per sentence, with the id everything else joins on.

| Column | Type | Meaning |
|---|---|---|
| `sentence_id` | string | First 16 hex characters of `sha2(text, 256)` — **derived here, not in the source data** |
| `text` | string | The sentence |
| `source_split` | string | Provenance only; Juno treats all 5,152 as one corpus |

**Rows:** 5,152. **Written by:** `02_curate.py`.
**Read by:** the vector index, both approaches, and every citation lookup.

**Why a hashed id:** the source has no identifier. A hash of the text is identical on every re-run,
so questions and citations stay valid. A row number would depend on processing order and would
silently break them.

## `human_labels` — silver, **the answer key** ✅

What researchers said each sentence is about. **Used only for grading — Juno never reads it.**

| Column | Type | Meaning |
|---|---|---|
| `sentence_id` | string | Joins to `sentences` |
| `category` | string | One of 12, e.g. `Service#General` |
| `sentiment` | string | `POS`, `NEG`, `NEU` |
| `aspect_terms` | array&lt;string&gt; | Words naming the thing ("cold brew"); empty when implicit |
| `opinion_terms` | array&lt;string&gt; | The verdict words ("delicious") |

**Rows:** 6,547, from 8,496 upstream quadruples. **Written by:** `02_curate.py`.
**Read by:** `03_build_questions.py`, and later the scorers and the tagger's F1 measurement.

**Grain:** one row per (sentence, category, sentiment). A sentence praising two dishes yields one
Food#Quality/POS row, not two, because counts are about sentences.

## `eval_questions` — **the exam** ✅

98 questions with their correct answers.

| Column | Type | Meaning |
|---|---|---|
| `question_id` | string | First 12 hex characters of sha256(question text) |
| `question` | string | The question in plain English |
| `qtype` | string | `count`, `share`, `share_within`, `compare`, `topn`, `why` |
| `template_id` | string | Which template produced it |
| `params` | map&lt;string,string&gt; | What was filled in: category, sentiment, n |
| `split` | string | `dev` (28, visible) or `test` (70, sealed) |
| `answer_number` | double | For counts and shares |
| `answer_unit` | string | `sentences` or `percent` |
| `answer_categories` | array&lt;string&gt; | Ordered list for `topn`; winner-first pair for `compare` |
| `answer_sentence_ids` | array&lt;string&gt; | The full evidence set for `why` |
| `support` | int | Sentences behind the answer, for interpreting errors |

**Written by:** `03_build_questions.py`. **Read by:** the evaluation runs in steps 6 and 8.
Also exported to `eval/questions.json` so a reviewer without workspace access can reproduce it.

## `review_facts` — gold 📋 step 3

**Not built yet.** Same grain as `human_labels`, but produced by an LLM instead of people — and
**this is the table Juno counts**. Matching grain is what makes the comparison meaningful.

Columns: `sentence_id`, `category`, `sentiment`, `model`, `instructions_version`, `tagged_at`. The
last three record which model and which version of the instructions produced the labels.
**Written by:** `04_tag_sentences.py` with `stage = full`, once. How the labels are checked before and
after is set out in [design.md](design.md).

## Tables that record how far the labels can be trusted 📋 step 3

**None built yet.** All written by `04_tag_sentences.py`.

| Table | Rows | What it holds |
|---|---|---|
| `tagging_trials` | One per trial run | Model, instructions version, trial size, which "how many" questions were marked and which skipped, ticks, average F1, the verdict on each condition of checkpoint 1, sentences that failed or came back unreadable, F1 per category, count error per question. The evidence for comparing two models. |
| `checkpoint2` | 18, one per "how many" question | Human count, tagger count, how far off, tick or cross, on all 5,152 sentences; whether checkpoint 1 had passed and, if not, the project owner's written reason for running anyway. Written once, after the full run. It governs what the report says. |
| `tagging_quality` | One per (category, sentiment) | Both counts, how far apart, precision, recall and F1, on all the data. |
| `tagging_quality_untouched` | One per (category, sentiment) | The same, on the 3,652 sentences that were never in a trial run: the honest figure for the tagger's general quality. |

## `sentences_index` — Vector Search 📋 step 4

**Not built yet.** A searchable copy of the sentence text with `category` and `sentiment` as filters.
Approach A retrieves 20 from it; Juno uses it only to fetch examples for "why" answers.

---

# Part 3 — The code

Since 2026-09-26 the code is arranged in one folder per stage of the pipeline, in the order the
stages run. The folder names are project choices. Notebooks are plain `.py` files with
`# Databricks notebook source` at the top, so they are readable on GitHub and never store output rows
of a dataset we cannot redistribute. A notebook imports the Python modules by adding the repo root to
`sys.path` (the line that computes `repo_root` from the notebook's own path).

## `data_setup/` — download and clean the dataset. Done; does not run again.

| File | Lines | What it does |
|---|---|---|
| `01_ingest.py` | 81 | Notebook. Streams three JSON files from GitHub into the volume, writes `raw_sentences`, asserts 5,152 records |
| `02_curate.py` | 136 | Notebook. Derives `sentences` and `human_labels` from `raw_sentences`, asserts six counts and id uniqueness |

## `eval/` — the test set; later the scorers and the judge

| File | Lines | What it does |
|---|---|---|
| `03_build_questions.py` | 243 | Notebook. Counts `human_labels` with SQL, gets the questions from `question_generator.py`, attaches the right answer to each, writes `eval_questions`, exports JSON. Done; does not run again. |
| `question_generator.py` | 183 | The 7 question templates, the plain-English name of each category, question ids and the dev/test split. Needs no data, so it is tested on the laptop. It is the evidence of how the 98 questions were made. |
| `questions.json` | — | The 98 questions with their right answers. A copy of the table `eval_questions`, kept in git so the frozen test set is visible and any change to it shows. |

## `tagger/` — the LLM labels every sentence. Frozen since 2026-09-25.

| File | Lines | What it does |
|---|---|---|
| `04_tag_sentences.py` | 482 | Notebook. Two stages. `trial`: labels the first 1,500 sentences, holds checkpoint 1, saves a row to `tagging_trials`. `full`: refuses to start without a passing trial unless a written `override_reason` is given, labels the 3,652 sentences outside the trial, reuses the trial's labels for the other 1,500, writes `review_facts`, holds checkpoint 2 |
| `prompt.py` | 130 | The tagger's prompt, version 4, the only version kept. Also the response schema and the check that no dataset sentence appears inside the prompt. |
| `checkpoints.py` | 206 | Marks the tagger against the human labels: F1 per category, count error per question, the checkpoint 1 verdict with its 30-sentence minimum, the rule that picks the better of two models, and the rule for starting the full run. |

## `juno/` — the product: answers a question

| File | Lines | What it does |
|---|---|---|
| `categories.py` | 16 | The 12 categories and 3 sentiments, spelled exactly as in the human labels. Used by the count tool, the tagger's prompt and the tests. |
| `sql_count_tool.py` | 72 | **The agent's count tool.** Builds a fixed SQL template from a category and sentiment chosen from allow-lists, rejecting anything else. The LLM picks values, never writes SQL. |
| `retrieval.py` | 17 | 📋 Retrieval: the 20 closest sentences for the RAG baseline, and example sentences filtered by label for the agent. Stub. |
| `rag_baseline.py` | 12 | 📋 Approach A, the vanilla RAG baseline: retrieve 20, one LLM call. Stub. |
| `agent.py` | 19 | 📋 Approach B, Juno: the LangGraph agent. Stub. |

## `resources/` — jobs as code

| File | Defines |
|---|---|
| `data.job.yml` | Job `juno-data`: task `ingest`, then `curate` if it succeeded |
| `evalset.job.yml` | Job `juno-evalset`: builds the question set. **Separate on purpose** — rebuilding data must never silently regenerate the frozen questions |
| `tagging_trial.job.yml`, `tagging_full.job.yml` | Jobs `juno-tagging-trial` and `juno-tagging-full`, one per file. **Two jobs on purpose** — a passing trial must never start the full run by itself, because two models are compared on the trial first |

## Configuration and setup

| File | What it does |
|---|---|
| `databricks.yml` | The bundle: variables (catalog, schema, model endpoints) and targets (`dev`, `prod`) |
| `infra/setup.sh` | Creates the workspace, storage account, access connector, credential, external location, catalog, schema, volume. Stages: `azure`, `login`, `unity`, `verify` |
| `sql/00_setup.sql` | The same catalog DDL, for anyone who prefers a SQL editor |
| `pytest.ini` | `pythonpath = .` points pytest at the repo root, so `import juno`, `import tagger` and `import eval` work |
| `requirements-dev.txt` | Local tooling only; notebooks install their own dependencies |

## Tests

| File | Covers |
|---|---|
| `tests/test_sql_count_tool.py` | The SQL template: values travel as parameters, injection attempts rejected, grouping and limits |
| `tests/test_question_generator.py` | Determinism, the type mix, split proportions, support thresholds, no neutral, English not category codes |
| `tests/test_tagger_checkpoints.py` | F1 and count error, checkpoint 1 including the 30-sentence minimum and its edge at 29 and 30, each of the four steps that pick the better model, and the full-run override |
| `tests/test_tagger_prompt.py` | The prompt names all 12 categories and ends ready for a sentence; an unknown version raises; a dataset sentence inside the prompt is found |

Run them with `pytest -q` — 49 tests, well under a second, no workspace needed.

## Documentation

| File | Contents |
|---|---|
| `README.md` | What Juno is, how to run it |
| `docs/reference.md` | This file |
| `docs/data-model.md` | Answering path versus grading path, metric-by-metric truth sources |
| `docs/setup-walkthrough.md` | How the environment was built and why each piece exists |
| `docs/design-doc.pdf` | The submitted design document |
| `docs/design.md` | How the tagger's labels are checked (two checkpoints) and how Juno's score is reported |
| `docs/implementation.md` | Every remaining step, in order and in detail |
| `eval/questions.json` | The frozen question set, committed |

---

# Part 4 — How a question will flow

Once steps 3–7 are done, asking *"What share of complaints are about service?"* runs:

1. The chat app sends the question to both approaches.
2. **A** searches `sentences_index`, gets 20 sentences, and the LLM answers from those.
3. **B** decides it is a counting question, calls `count_sql` (from `juno/sql_count_tool.py`) against
   `review_facts`, gets 471, checks the answer repeats that number, and replies with cited ids.
4. The evaluation compares both to `eval_questions`: the true answer is 466, so B is within 10% and
   A is not.

**Two sources of error in B's answer**, measured separately:

- **Tagging** — did the LLM label the right sentences? (tagging F1, `review_facts` vs `human_labels`)
- **Arithmetic** — did the agent report its own SQL result faithfully? (calculation accuracy)

Juno can never beat the quality of its own tags. That ceiling is a finding to report, not a flaw to
hide.

---

# Part 5 — Where things stand

| Step | State |
|---|---|
| 0 · Repo, bundle, Unity Catalog | ✅ |
| — · Dedicated workspace and storage | ✅ |
| 1 · Ingest and curate | ✅ 3 tables |
| 2 · Question set and ground truth | ✅ 98 questions, test split frozen |
| 3 · Tag every sentence → `review_facts` | In progress. Three trial attempts made on 500 sentences; code brought in line with `design.md` on 2026-09-20; nothing run on the full data |
| 4 · Vector Search index | |
| 5 · Baseline A | |
| 6 · Evaluation harness (scorers + judge) | |
| 7 · Juno agent B | |
| 8 · Final run on the sealed test split | |
| 9 · Chat app | |
| 10 · Guardrails, cost controls | |
| 11 · README, documentation, demo video | |
