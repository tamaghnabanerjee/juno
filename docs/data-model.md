# Data model — which table is used where

The single most important rule in this project:

> **`human_labels` grades Juno. Juno never reads it.**

Everything below follows from that. If the agent could see the human labels while answering, it would
be marking its own homework and every number in the results table would be meaningless.

## The two paths

```
ANSWERING (what Juno does in production)      EVALUATION (how Juno is graded)
──────────────────────────────────────        ───────────────────────────────
             question                                  eval_questions
                 │                                     (question + correct answer
                 ▼                                      from human_labels)
        ┌────────────────┐                                     │
        │   agent LLM    │                                     │
        └───┬────────┬───┘                                     │
            │        │                                         │
   count_sql│        │find_examples                            │
            ▼        ▼                                         ▼
     review_facts   vector index  ──────────────▶  compare, then score
     (LLM's tags)   (sentence text)                 count · top-3 · citations
            │                                              │
            ▼                                              ▼
     answer + cited sentence ids ──────────────────▶  results: A vs B
```

The two halves meet only at the scoring step. `review_facts` (the LLM's tags) is what Juno counts
over; `human_labels` (people's tags) is what the counts are checked against.

## Tables

All in `juno.restaurant`.

### `raw_sentences` — bronze ✅ built

| | |
|---|---|
| Grain | One record exactly as downloaded |
| Rows | 5,152 |
| Written by | `src/notebooks/01_ingest.py` |
| Read by | `02_curate` only |

| Column | Type | Notes |
|---|---|---|
| `raw_words` | string | The review sentence |
| `quadruples` | array&lt;struct&gt; | The human annotations, nested |
| `task` | string | Annotation task name (`ACOS`), constant |
| `source_split` | string | `Train` / `Dev` / `Test` from upstream |
| `ingested_at` | timestamp | When this load ran |

Kept unchanged so anything dropped downstream can be recovered without re-downloading.

### `sentences` — silver ✅ built

| | |
|---|---|
| Grain | One row per sentence |
| Rows | 5,152 |
| Written by | `src/notebooks/02_curate.py` |
| Read by | The vector index (step 4), both approaches, every citation lookup |

| Column | Notes |
|---|---|
| `sentence_id` | First 16 hex chars of `sha2(text, 256)` — **derived, not from the source** |
| `text` | The sentence |
| `source_split` | Provenance only; Juno treats all 5,152 as one corpus |

The upstream data has no identifier, so one is derived from the text itself. A hash is stable across
re-runs; a row number would depend on processing order and would silently invalidate every question
and citation built on the old numbering.

### `human_labels` — silver, **the ground truth** ✅ built

| | |
|---|---|
| Grain | One row per (sentence, category, sentiment) |
| Rows | 6,547, from 8,496 upstream quadruples |
| Written by | `src/notebooks/02_curate.py` |
| Read by | **Evaluation only** — `eval_questions`, scorers, tagger F1 |

| Column | Notes |
|---|---|
| `sentence_id` | Joins to `sentences` |
| `category` | One of 12, e.g. `Service#General` |
| `sentiment` | `POS`, `NEG`, `NEU` |
| `aspect_terms` | Words naming the thing ("cold brew"); empty when the aspect is implicit |
| `opinion_terms` | The verdict words ("delicious", "very reasonable") |

### `review_facts` — gold 📋 planned, step 3

Same grain as `human_labels` — one row per (sentence, category, sentiment) — but produced by an LLM
via `ai_query` rather than by people. **This is what Juno counts.** The matching grain is what makes
Juno's counts comparable with the ground truth; different grains would make the comparison
meaningless.

### `eval_questions` 📋 planned, step 2

One row per question: the text, its type, the `dev`/`test` split, and the correct answer computed by
SQL over `human_labels` — a number for counts and shares, an ordered category list for top-N, a set
of sentence ids for "why" questions.

## How a quadruple becomes label rows

Upstream, each annotation is a quadruple:

```json
{"aspect":   {"term": ["food"], "from": 5, "to": 6},
 "category": "Food#Quality",
 "opinion":  {"term": ["delicious"], "from": 4, "to": 5},
 "sentiment": "POS"}
```

| Field | Destination | Why |
|---|---|---|
| `category` | `category` | Every count filters on it |
| `sentiment` | `sentiment` | POS / NEG / NEU |
| `aspect.term` | `aspect_terms` | Evidence: *what* was praised or criticised |
| `opinion.term` | `opinion_terms` | Evidence: the verdict words |
| `aspect.from` / `.to` | dropped | Character offsets, for span-extraction models; Juno highlights nothing |
| `task` | bronze only | Constant |

**8,496 quadruples become 6,547 rows.** A sentence praising two dishes produces two quadruples with
different aspect words but the same (category, sentiment); they collapse into one row, with both sets
of words kept in the arrays. That is deliberate: counts are about sentences, so a sentence should
count once.

## Shape of the data

- **5,152 sentences**, averaging 17 words (1 to 191).
- **Every sentence is labelled** — none is invisible to the ground truth.
- **1.27 labels per sentence**: 4,052 have one, 871 two, 174 three, 46 four, 7 five, 2 six.
- **Reviews skew positive**: 3,973 sentences carry a positive label, 1,499 negative, 109 neutral.
- **251 sentences disagree with themselves** — the same category labelled both POS and NEG (liked the
  latte, disliked the cold brew). Both rows are kept; resolving them would turn the ground truth into
  an opinion. Shares across sentiments can therefore exceed 100%.
- **1,831 quadruples have an implicit aspect** — praise or criticism with no noun naming the target.
  Keyword search misses these; an LLM tagger should catch them.

Sentences per category and sentiment:

| Category | POS | NEG | NEU | Total |
|---|---|---|---|---|
| Food#Quality | 1,889 | 510 | 59 | 2,458 |
| Restaurant#General | 1,083 | 296 | 29 | 1,408 |
| Service#General | 799 | 466 | 8 | 1,273 |
| Ambience#General | 350 | 124 | 4 | 478 |
| Food#Style_Options | 229 | 62 | 1 | 292 |
| Drinks#Quality | 198 | 28 | 6 | 232 |
| Food#Prices | 75 | 44 | 1 | 120 |
| Location#General | 64 | 17 | 1 | 82 |
| Restaurant#Prices | 45 | 36 | 0 | 81 |
| Restaurant#Miscellaneous | 42 | 10 | 0 | 52 |
| Drinks#Style_Options | 35 | 3 | 0 | 38 |
| Drinks#Prices | 20 | 12 | 1 | 33 |

Two consequences for the evaluation:

- **Neutral is excluded from questions.** 110 label rows across 109 sentences, and three categories
  have none at all. A question about neutral mentions of drink prices would rest on a single sentence.
- **Count questions need at least 30 sentences of support.** "Within 10%" of a 3-sentence category
  means being exactly right, which would make the target meaningless. Small categories still appear
  in top-N answers, where they belong at the bottom of the ranking.

The unevenness is the point, incidentally: Food#Quality has 2,458 sentences and Drinks#Prices has 33.
A top-20 retrieval over-samples the big topics and never sees the small ones — the exact failure
Juno is built to expose.

## Where each metric's truth comes from

| Metric | Source of truth |
|---|---|
| Count accuracy | `COUNT(DISTINCT sentence_id)` over `human_labels` |
| Top-3 match | The true category ranking from `human_labels` |
| Citation accuracy | The set of sentence ids carrying that (category, sentiment) — pure set membership, no judge |
| Tagging quality (F1) | `review_facts` compared row by row with `human_labels` |
| Calculation accuracy | Juno's stated number vs its own SQL result |
| Answer quality | **The LLM judge** — the one metric human labels cannot supply |

## The ceiling caveat

Juno counts over `review_facts`, which an LLM produced. If the tagger scores 0.6 F1 on drinks, Juno's
drink numbers inherit that error no matter how correct the SQL is.

That is why tagging F1 is reported next to count accuracy: it separates *"the agent counted wrongly"*
from *"the agent counted the wrong rows correctly"*. It is a finding to report, not a flaw to hide.
