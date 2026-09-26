# Databricks notebook source
# MAGIC %md
# MAGIC # 03 — Build the evaluation question set
# MAGIC
# MAGIC Renders ~100 questions from templates (`eval/question_generator.py`) and computes each correct answer with
# MAGIC SQL over `human_labels`. No LLM is involved, and no answer comes from Juno's own tags.
# MAGIC
# MAGIC The result is `eval_questions`, split 30% `dev` / 70% `test`. **The test split is frozen from
# MAGIC here on**: it is what every later claim about accuracy is measured against. Because ids and the
# MAGIC split are hashes, re-running this notebook reproduces the identical set.

# COMMAND ----------

dbutils.widgets.text("catalog", "juno")
dbutils.widgets.text("schema", "restaurant")
dbutils.widgets.text("volume", "raw")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")

spark.sql(f"USE CATALOG {catalog}")
spark.sql(f"USE SCHEMA {schema}")
volume_path = f"/Volumes/{catalog}/{schema}/{volume}"

# COMMAND ----------

# MAGIC %md ## Import the question templates
# MAGIC The bundle uploads the whole repo. This notebook adds the repo root to the import path, so
# MAGIC `eval/question_generator.py` beside it is importable. Templates live there, not in this notebook,
# MAGIC so they can be unit tested locally without a workspace.

# COMMAND ----------

import os
import sys

notebook_path = (
    dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
)
repo_root = "/Workspace" + os.path.dirname(os.path.dirname(notebook_path))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from eval import question_generator as q  # noqa: E402

print(f"templates from {repo_root}: {', '.join(sorted(q.TEMPLATES))}")

# COMMAND ----------

# MAGIC %md ## Ground truth from SQL
# MAGIC Four aggregates over `human_labels`, all counting **distinct sentences**, which is the grain
# MAGIC decided in step 1.

# COMMAND ----------

support_rows = spark.sql("""
    SELECT category, sentiment, COUNT(DISTINCT sentence_id) AS n
    FROM human_labels GROUP BY category, sentiment
""").collect()
support = {(r["category"], r["sentiment"]): r["n"] for r in support_rows}

total_sentences = spark.table("sentences").count()

sentiment_totals = {
    r["sentiment"]: r["n"]
    for r in spark.sql("""
        SELECT sentiment, COUNT(DISTINCT sentence_id) AS n FROM human_labels GROUP BY sentiment
    """).collect()
}

# Rankings: per sentiment, and overall regardless of sentiment. Ties break on category name so the
# ordering is stable rather than whatever Spark returns first.
def ranking(sentiment: str | None) -> list[str]:
    where = f"WHERE sentiment = '{sentiment}'" if sentiment else ""
    rows = spark.sql(f"""
        SELECT category, COUNT(DISTINCT sentence_id) AS n
        FROM human_labels {where}
        GROUP BY category ORDER BY n DESC, category ASC
    """).collect()
    return [r["category"] for r in rows]

rankings = {s: ranking(s) for s in ("POS", "NEG")}
rankings["ALL"] = ranking(None)

print(f"{total_sentences} sentences | sentiment totals {sentiment_totals}")
print(f"top 3 negative: {rankings['NEG'][:3]}")

# COMMAND ----------

# MAGIC %md ## Evidence sets for the "why" questions
# MAGIC The complete set of sentence ids carrying each (category, sentiment). Citation accuracy is
# MAGIC then set membership — no judge needed to decide whether a cited sentence supports the claim.

# COMMAND ----------

evidence = {
    (r["category"], r["sentiment"]): sorted(r["ids"])
    for r in spark.sql("""
        SELECT category, sentiment, COLLECT_SET(sentence_id) AS ids
        FROM human_labels GROUP BY category, sentiment
    """).collect()
}

# COMMAND ----------

# MAGIC %md ## Attach an answer to every question

# COMMAND ----------

def answer_for(question: dict) -> dict:
    p = question["params"]
    qtype = question["qtype"]
    number = unit = None
    categories: list[str] = []
    sentence_ids: list[str] = []
    support_n = None

    if qtype in ("count", "share", "share_within", "why"):
        support_n = support[(p["category"], p["sentiment"])]

    if qtype == "count":
        number, unit = float(support_n), "sentences"
    elif qtype == "share":
        number, unit = round(100.0 * support_n / total_sentences, 1), "percent"
    elif qtype == "share_within":
        number = round(100.0 * support_n / sentiment_totals[p["sentiment"]], 1)
        unit = "percent"
    elif qtype == "compare":
        a, b = p["category"], p["category_b"]
        n_a, n_b = support[(a, p["sentiment"])], support[(b, p["sentiment"])]
        winner, loser = (a, b) if n_a >= n_b else (b, a)
        categories = [winner, loser]
        number, unit = float(max(n_a, n_b)), "sentences"
    elif qtype == "topn":
        order = rankings[p["sentiment"]] if "sentiment" in p else rankings["ALL"]
        categories = order[: int(p["n"])]
    elif qtype == "why":
        sentence_ids = evidence[(p["category"], p["sentiment"])]

    return {
        **question,
        "answer_number": number,
        "answer_unit": unit,
        "answer_categories": categories,
        "answer_sentence_ids": sentence_ids,
        "support": support_n if support_n is not None else len(sentence_ids) or None,
    }

built = [answer_for(question) for question in q.build(support)]
print(f"{len(built)} questions built")

# COMMAND ----------

# MAGIC %md ## Write `eval_questions`

# COMMAND ----------

from pyspark.sql import types as T

SCHEMA = T.StructType([
    T.StructField("question_id", T.StringType(), False),
    T.StructField("question", T.StringType(), False),
    T.StructField("qtype", T.StringType(), False),
    T.StructField("template_id", T.StringType(), False),
    T.StructField("params", T.MapType(T.StringType(), T.StringType()), False),
    T.StructField("split", T.StringType(), False),
    T.StructField("answer_number", T.DoubleType(), True),
    T.StructField("answer_unit", T.StringType(), True),
    T.StructField("answer_categories", T.ArrayType(T.StringType()), True),
    T.StructField("answer_sentence_ids", T.ArrayType(T.StringType()), True),
    T.StructField("support", T.IntegerType(), True),
])

(
    spark.createDataFrame(built, schema=SCHEMA)
    .write.mode("overwrite").option("overwriteSchema", "true")
    .saveAsTable("eval_questions")
)

display(spark.sql("""
    SELECT qtype, split, COUNT(*) AS questions
    FROM eval_questions GROUP BY qtype, split ORDER BY qtype, split
"""))

# COMMAND ----------

# MAGIC %md ## Checks
# MAGIC The last one matters most: a known answer, verified independently. Service#General NEG was
# MAGIC counted in step 1 as 466 sentences, 9.0% of the corpus.

# COMMAND ----------

rows = spark.table("eval_questions")
total = rows.count()
dev = rows.filter("split = 'dev'").count()

assert total == sum(q.TARGETS.values()), f"expected {sum(q.TARGETS.values())} questions, got {total}"
assert 0.25 <= dev / total <= 0.35, f"dev split is {dev / total:.0%}, expected about 30%"
assert rows.select("qtype").distinct().count() == len(q.TARGETS), "a question type is missing"
assert rows.filter("qtype IN ('count','share','share_within','compare') AND answer_number IS NULL").count() == 0
assert rows.filter("qtype = 'topn' AND SIZE(answer_categories) = 0").count() == 0
assert rows.filter(f"qtype = 'why' AND SIZE(answer_sentence_ids) < {q.WHY_MIN_SUPPORT}").count() == 0
assert rows.filter("params['sentiment'] = 'NEU'").count() == 0, "neutral should not be asked about"

known = spark.sql("""
    SELECT answer_number, answer_unit FROM eval_questions
    WHERE qtype = 'count' AND params['category'] = 'Service#General' AND params['sentiment'] = 'NEG'
""").collect()
assert known and known[0]["answer_number"] == 466.0, f"service NEG count should be 466, got {known}"

print(f"ok  {total} questions, {dev} dev / {total - dev} test, service NEG count = 466")

# COMMAND ----------

# MAGIC %md ## Export for the repository
# MAGIC Written to the volume, then downloaded into `eval/questions.json` so the evaluation is
# MAGIC reproducible by a reviewer who cannot reach this workspace:
# MAGIC
# MAGIC ```
# MAGIC databricks -p JUNO fs cp dbfs:/Volumes/juno/restaurant/raw/questions.json eval/questions.json
# MAGIC ```

# COMMAND ----------

import json

export = [
    {k: v for k, v in row.asDict(recursive=True).items()}
    for row in spark.table("eval_questions").orderBy("qtype", "question_id").collect()
]
with open(f"{volume_path}/questions.json", "w") as f:
    json.dump(export, f, indent=1, sort_keys=True)

print(f"exported {len(export)} questions to {volume_path}/questions.json")

# COMMAND ----------

display(spark.sql("""
    SELECT question, qtype, split, answer_number, answer_unit,
           answer_categories, SIZE(answer_sentence_ids) AS evidence, support
    FROM eval_questions ORDER BY qtype, question_id LIMIT 12
"""))
