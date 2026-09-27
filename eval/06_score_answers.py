# Databricks notebook source
import os
import sys
from datetime import datetime, timezone

notebook_path = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
repo_root = "/Workspace" + os.path.dirname(os.path.dirname(notebook_path))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

from eval.judge import build_judge_prompt, parse_grade
from eval.scorers import score

dbutils.widgets.text("split", "dev")
dbutils.widgets.text("judge_model", "databricks-qwen35-122b-a10b")
split = dbutils.widgets.get("split")
judge_model = dbutils.widgets.get("judge_model")
assert split in ("dev", "test"), f"split must be dev or test, got {split!r}"

workspace = WorkspaceClient()


def call_judge(prompt):
    response = workspace.serving_endpoints.query(
        name=judge_model,
        messages=[ChatMessage(role=ChatMessageRole.USER, content=prompt)],
    )
    content = response.choices[0].message.content
    if isinstance(content, list):
        content = " ".join(part.get("text", "") for part in content if isinstance(part, dict))
    return content

# COMMAND ----------

pairs = spark.sql("""
    SELECT q.question_id, q.question, q.qtype, q.split, q.answer_number, q.answer_categories,
           q.answer_sentence_ids, a.approach, a.answer_text, a.number, a.ranked_categories,
           a.cited_sentence_ids, a.tool_numbers, a.seconds
    FROM juno.restaurant.eval_questions q
    JOIN juno.restaurant.eval_answers a USING (question_id)
    WHERE q.split = :split
    QUALIFY ROW_NUMBER() OVER (PARTITION BY a.approach, q.question_id ORDER BY a.answered_at DESC) = 1
""", args={"split": split}).collect()

texts = {
    r["sentence_id"]: r["text"]
    for r in spark.sql("SELECT sentence_id, text FROM juno.restaurant.sentences").collect()
}

scored_at = datetime.now(timezone.utc)
rows = []
for p in pairs:
    question = p.asDict()
    answer = {"number": p["number"], "ranked_categories": p["ranked_categories"] or [],
              "cited_sentence_ids": p["cited_sentence_ids"] or []}
    measures = score(question, answer)
    if p["approach"] == "juno_agent" and p["qtype"] in ("count", "share", "share_within") \
            and p["number"] is not None:
        measures["exact_number"] = 1.0 if p["number"] in (p["tool_numbers"] or []) else 0.0
    grade = reason = None
    if p["qtype"] == "why":
        cited = [{"sentence_id": i, "text": texts.get(i, "")} for i in answer["cited_sentence_ids"]]
        grade, reason = parse_grade(call_judge(build_judge_prompt(p["question"], p["answer_text"], cited)))
        measures["answer_quality"] = None if grade is None else float(grade)
    for measure, value in measures.items():
        rows.append({
            "question_id": p["question_id"], "approach": p["approach"], "split": p["split"],
            "qtype": p["qtype"], "measure": measure, "score": value,
            "judge_grade": grade if measure == "answer_quality" else None,
            "judge_reason": reason if measure == "answer_quality" else None,
            "judge_model": judge_model if measure == "answer_quality" else None,
            "seconds": float(p["seconds"] or 0), "scored_at": scored_at,
        })

# COMMAND ----------

spark.createDataFrame(
    rows,
    "question_id string, approach string, split string, qtype string, measure string, "
    "score double, judge_grade int, judge_reason string, judge_model string, seconds double, "
    "scored_at timestamp",
).write.mode("append").saveAsTable("juno.restaurant.eval_scores")

display(spark.sql("""
    SELECT measure, approach, COUNT(*) AS questions, ROUND(AVG(score), 2) AS mean_score
    FROM juno.restaurant.eval_scores
    WHERE split = :split
      AND scored_at = (SELECT MAX(scored_at) FROM juno.restaurant.eval_scores WHERE split = :split)
    GROUP BY measure, approach ORDER BY measure, approach
""", args={"split": split}))
