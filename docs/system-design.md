# Project Juno — system design (as built)

Tamaghna Banerjee · Azure Databricks · 27 September 2026

This describes the system as built and evaluated. The design submitted on 17 September 2026 is kept
unchanged as [design-doc.pdf](design-doc.pdf); section 7 lists what changed and why.

## 1. Problem

Leadership and analysts ask two kinds of questions about customer reviews: "how many" ("What share
of complaints are about service?") and "why" ("Why don't guests like the food?"). The usual approach,
retrieve-only RAG, retrieves the top K sentences most relevant to the question (here K = 20) and
answers from those alone, so its counts describe a sample, not the whole collection. Juno must get
counts, top categories and why-with-examples right.

**Data:** MEMD-ABSA Restaurant (Cai et al., 2023): 5,152 review sentences labelled by people with 12
categories and a sentiment. These human labels are the right answers. There are no dates, so no
trend questions.

## 2. Architecture

![Build pipeline: four stages writing tables in Unity Catalog](images/architecture-build.svg)

**Build, once.** Four stages, each a Databricks job, share data only through Unity Catalog tables:
the dataset is cleaned into `sentences` and `human_labels`; 98 test questions are frozen with right
answers computed from `human_labels`; an LLM labels every sentence into `review_facts`, checked
against the human labels at two checkpoints; every sentence is embedded into `sentence_embeddings`.

![Answering: approach A and Juno, then scoring](images/architecture-answer.svg)

**Answer, per question.** A (retrieve-only RAG) retrieves the 20 sentences closest to the question by
cosine similarity and makes one LLM call. B (Juno) is an agent that chooses per question between two
tools: `count_sentences`, a fixed SQL template over all of `review_facts`, and `find_examples`,
retrieval restricted to one category and sentiment (top 10). A check requires the number Juno states
to be one the count tool returned; otherwise it retries once. Both approaches use the same model and
return the same fields, so the same scorers apply.

## 3. Components

| Component | What it does | Code |
|---|---|---|
| Count tool | Builds a read-only SQL count from a category and sentiment chosen from fixed lists; counts distinct sentences; returns the count and two shares | `juno/sql_count_tool.py` |
| Retrieval | One SQL query: embed the question, rank stored embeddings by cosine similarity, optionally filter to one label | `juno/retrieval.py` |
| Approach A | Retrieve top 20, one LLM call, parse the JSON response | `juno/rag_baseline.py` |
| Approach B, Juno | LangGraph ReAct agent with the two tools, then the number check | `juno/agent.py` |
| Labelling | Bulk LLM labelling with a versioned prompt; checkpoints against the human labels | `tagger/` |
| Evaluation | Runs either approach on dev or test questions; scores answers; LLM judge for "why" answers | `eval/` |

## 4. Evaluation

98 template questions, right answers by SQL over the human labels (never Juno's labels). Split once:
28 dev for building, 70 test run once. Measures and targets are those submitted: count accuracy
within 10% on ≥ 80% of "how many" questions and ≥ 30 points above A; top-3 match ≥ 0.8; citation
accuracy ≥ 90%; answer quality by LLM judge ≥ 4 of 5; exact number ≥ 95%; median time ≤ 15 s. The
judge is a different model from the answering model and sees only the question, the answer and the
cited sentences.

**Result:** Juno 5 of 13 counts within 10% against 0 of 13 for A; ahead on every measure except
answer quality (4.00 against 4.07). The 80% target was missed: Juno got exactly the questions where
the LLM's labels are within 10% of the human labels. Full table in the [README](../README.md).

## 5. Technology choices

| Choice | Why | Instead of |
|---|---|---|
| LangGraph (`create_react_agent`) | The agent loop as a small, testable graph; unit-tested with a scripted model | A hand-written loop |
| Databricks: Unity Catalog, serverless jobs, Asset Bundles, `ai_query` | Governed tables, jobs as code, bulk LLM work in SQL | Local stores, manual runs |
| Vector search as SQL over an embeddings table | 5,152 rows need no index service; no hourly cost | Managed Vector Search (deferred) |
| Own scorers and LLM judge, results in tables | Every measure is plain, tested code | MLflow's evaluation API |
| Models by role | Labelling: Claude Opus 4.8 (bulk) · answering, both approaches: Llama 3.3 70B · judge: Qwen 3.5 122B · embeddings: GTE Large (English) | The planned Claude models, rate-limited to zero here |

## 6. Controls

| Risk | Control | State |
|---|---|---|
| SQL injection or data changes | The LLM only picks values from fixed lists; values travel as query parameters; queries only read | In place, unit-tested |
| Made-up numbers | The stated number must be one the count tool returned; one retry; a miss is recorded | In place; 39 of 39 test answers passed |
| Malformed model responses | Recorded with the raw text and scored 0; the run continues | In place |
| Spend | Monthly budget with an email alert | In place |
| Off-topic questions | Declining anything not about the reviews | Not implemented |
| App access, gateway filtering, rate limits | Planned for the chat page | Not built: no chat page |
| Cost per question | Token counts added up per question | Not measured: the billing table is not readable from this account |

## 7. Changes from the submitted design

| Submitted (17 September) | Built | Why |
|---|---|---|
| Databricks Vector Search index | Cosine similarity in SQL over `sentence_embeddings` | Scope cut to meet the deadline; the service bills by the hour |
| MLflow scores A and B | Own scorers and judge; results in `eval_answers`, `eval_scores` | Evaluation built as tested code, per the course's emphasis |
| Judge checked against 30 hand-graded answers | Not done | Time; listed as a limitation |
| Model calls through Unity AI Gateway | Direct calls to pay-per-token endpoints | All Claude models rate-limited to zero in this workspace; open models used |
| Databricks App chat page with ratings | Not built; answers run as jobs into tables | The course marks a UI as optional; scope cut |
| After a failed retry, fall back to the SQL number | The answer is kept and the miss recorded | The count tool returns up to three numbers, so there is no single one to substitute |
| Labels trusted after tagging | Two checkpoints against the human labels, before Juno was built | The first trial showed the labels decide Juno's ceiling |
