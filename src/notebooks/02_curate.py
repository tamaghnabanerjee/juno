# Databricks notebook source
# MAGIC %md
# MAGIC # 02 — Curate the silver tables
# MAGIC
# MAGIC Reads `raw_sentences` and writes:
# MAGIC
# MAGIC | Table | Grain | Rows |
# MAGIC |---|---|---|
# MAGIC | `sentences` | one sentence | 5,152 |
# MAGIC | `human_labels` | one (sentence, category, sentiment) | 6,547 |
# MAGIC
# MAGIC `human_labels` is the ground truth every evaluation count is measured against, so this
# MAGIC notebook asserts the expected counts and fails if upstream data has changed.

# COMMAND ----------

dbutils.widgets.text("catalog", "juno")
dbutils.widgets.text("schema", "restaurant")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
spark.sql(f"USE CATALOG {catalog}")
spark.sql(f"USE SCHEMA {schema}")

from pyspark.sql import functions as F

# A hash of the text, so the id is the same on every re-run. Row numbers would not be:
# they depend on processing order, and every question and citation built on them would break.
SENTENCE_ID = F.substring(F.sha2(F.col("raw_words"), 256), 1, 16)

# COMMAND ----------

# MAGIC %md ## `sentences`

# COMMAND ----------

(
    spark.table("raw_sentences")
    .select(
        SENTENCE_ID.alias("sentence_id"),
        F.col("raw_words").alias("text"),
        F.col("source_split"),
    )
    .write.mode("overwrite").option("overwriteSchema", "true")
    .saveAsTable("sentences")
)

display(spark.table("sentences").limit(5))

# COMMAND ----------

# MAGIC %md ## `human_labels`
# MAGIC One row per (sentence, category, sentiment). A sentence praising two dishes is one
# MAGIC Food#Quality/POS row, not two, because counts are about sentences. Aspect and opinion words
# MAGIC are collected into arrays so the evidence survives. `NULL` marks an implicit aspect (1,831 of
# MAGIC them) and is dropped from the arrays rather than kept as a word.

# COMMAND ----------

quadruples = (
    spark.table("raw_sentences")
    .select(SENTENCE_ID.alias("sentence_id"), F.explode("quadruples").alias("q"))
)


def terms(col):
    return F.array_remove(F.array_distinct(F.flatten(F.collect_list(col))), "NULL")


(
    quadruples.select(
        "sentence_id",
        F.col("q.category").alias("category"),
        F.col("q.sentiment").alias("sentiment"),
        F.col("q.aspect.term").alias("aspect_term"),
        F.col("q.opinion.term").alias("opinion_term"),
    )
    .groupBy("sentence_id", "category", "sentiment")
    .agg(terms("aspect_term").alias("aspect_terms"), terms("opinion_term").alias("opinion_terms"))
    .write.mode("overwrite").option("overwriteSchema", "true")
    .saveAsTable("human_labels")
)

display(spark.table("human_labels").limit(5))

# COMMAND ----------

# MAGIC %md ## Checks
# MAGIC These numbers come from the upstream dataset. If they change, the ground truth has changed and
# MAGIC the evaluation would be measuring something else — so the job fails instead.

# COMMAND ----------

expected = {
    "raw_sentences": 5152,
    "sentences": 5152,
    "human_labels": 6547,
    "quadruples": 8496,
    "categories": 12,
    "sentiments": 3,
}

actual = {
    "raw_sentences": spark.table("raw_sentences").count(),
    "sentences": spark.table("sentences").count(),
    "human_labels": spark.table("human_labels").count(),
    "quadruples": spark.table("raw_sentences").select(F.explode("quadruples")).count(),
    "categories": spark.table("human_labels").select("category").distinct().count(),
    "sentiments": spark.table("human_labels").select("sentiment").distinct().count(),
}

for key, want in expected.items():
    got = actual[key]
    print(f"{'ok  ' if got == want else 'FAIL'} {key}: {got} (expected {want})")

assert actual == expected, f"unexpected counts: {actual}"
assert spark.table("sentences").select("sentence_id").distinct().count() == 5152, "ids not unique"

# COMMAND ----------

# MAGIC %md ## What a ground-truth answer looks like
# MAGIC The shape every correct answer in step 2 takes: SQL over the human labels, counting distinct
# MAGIC sentences.

# COMMAND ----------

display(spark.sql("""
    SELECT category,
           COUNT(DISTINCT sentence_id) AS sentences,
           ROUND(100.0 * COUNT(DISTINCT sentence_id) /
                 (SELECT COUNT(*) FROM sentences), 1) AS pct_of_corpus
    FROM human_labels
    WHERE sentiment = 'NEG'
    GROUP BY category
    ORDER BY sentences DESC
"""))
