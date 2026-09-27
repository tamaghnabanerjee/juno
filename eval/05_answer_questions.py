# Databricks notebook source
# MAGIC %pip install --quiet "langgraph==1.2.12" "langgraph-prebuilt==1.1.0" "langgraph-checkpoint==4.2.0" databricks-langchain

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import os
import sys
from datetime import datetime, timezone

notebook_path = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
repo_root = "/Workspace" + os.path.dirname(os.path.dirname(notebook_path))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

from juno import agent as juno_agent
from juno import rag_baseline
from juno.retrieval import build_search_sql

dbutils.widgets.text("approach", "rag_baseline")
dbutils.widgets.text("split", "dev")
dbutils.widgets.text("limit", "1")
approach = dbutils.widgets.get("approach")
split = dbutils.widgets.get("split")
limit = int(dbutils.widgets.get("limit"))
assert split in ("dev", "test"), f"split must be dev or test, got {split!r}"
assert approach in ("rag_baseline", "juno_agent"), f"unknown approach {approach!r}"

TABLES = {
    "embeddings_table": "juno.restaurant.sentence_embeddings",
    "sentences_table": "juno.restaurant.sentences",
    "labels_table": "juno.restaurant.review_facts",
}


def search(question):
    sql, params = build_search_sql(question, k=20, **TABLES)
    return [row.asDict() for row in spark.sql(sql, args=params).collect()]


MODEL = "databricks-meta-llama-3-3-70b-instruct"
workspace = WorkspaceClient()


def call_llm(prompt):
    response = workspace.serving_endpoints.query(
        name=MODEL,
        messages=[ChatMessage(role=ChatMessageRole.USER, content=prompt)],
    )
    return response.choices[0].message.content


def run_sql(sql, params):
    return [row.asDict() for row in spark.sql(sql, args=params).collect()]


if approach == "juno_agent":
    from databricks_langchain import ChatDatabricks

    agent = juno_agent.build_agent(
        ChatDatabricks(endpoint=MODEL, temperature=0),
        run_sql,
        {"labels": TABLES["labels_table"], "sentences": TABLES["sentences_table"],
         "embeddings": TABLES["embeddings_table"]},
    )


def answer(question):
    if approach == "juno_agent":
        return juno_agent.run_juno(question, agent=agent)
    return rag_baseline.run_rag_baseline(question, search=search, call_llm=call_llm)

# COMMAND ----------

questions = spark.sql(
    f"SELECT question_id, question FROM juno.restaurant.eval_questions "
    f"WHERE split = :split ORDER BY question_id LIMIT {limit}",
    args={"split": split},
).collect()

rows = []
for q in questions:
    try:
        result = answer(q["question"])
    except Exception as error:  # noqa: BLE001
        result = {"answer_text": None, "number": None, "unit": None, "ranked_categories": [],
                  "cited_sentence_ids": [], "retrieved_sentence_ids": [], "seconds": 0.0,
                  "response_text": None, "tool_numbers": [], "retried": False,
                  "parse_error": f"call failed: {type(error).__name__}: {error}"[:1000]}
    rows.append({
        "question_id": q["question_id"],
        "approach": approach,
        "answer_text": result["answer_text"],
        "number": result["number"],
        "unit": result["unit"],
        "ranked_categories": result["ranked_categories"],
        "cited_sentence_ids": result["cited_sentence_ids"],
        "retrieved_sentence_ids": result["retrieved_sentence_ids"],
        "seconds": float(result["seconds"]),
        "response_text": result["response_text"],
        "tool_numbers": result.get("tool_numbers", []),
        "retried": result.get("retried", False),
        "parse_error": result["parse_error"],
        "answered_at": datetime.now(timezone.utc),
    })
    print(q["question_id"], "|", q["question"], "->", result["answer_text"] or result["parse_error"])

# COMMAND ----------

spark.createDataFrame(
    rows,
    "question_id string, approach string, answer_text string, number double, unit string, "
    "ranked_categories array<string>, cited_sentence_ids array<string>, "
    "retrieved_sentence_ids array<string>, "
    "seconds double, response_text string, tool_numbers array<double>, retried boolean, "
    "parse_error string, answered_at timestamp",
).write.mode("append").option("mergeSchema", "true").saveAsTable("juno.restaurant.eval_answers")
print(f"saved {len(rows)} answers to juno.restaurant.eval_answers")
