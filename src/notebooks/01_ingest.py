# Databricks notebook source
# MAGIC %md
# MAGIC # 01 — Ingest MEMD-ABSA Restaurant
# MAGIC
# MAGIC Downloads the dataset into the Unity Catalog volume, then builds:
# MAGIC
# MAGIC | Table | Contents |
# MAGIC |---|---|
# MAGIC | `raw_sentences` | bronze: the JSON as loaded |
# MAGIC | `sentences` | silver: one row per sentence, with a stable `sentence_id` |
# MAGIC | `human_labels` | silver: one row per human (category, sentiment) label — the ground truth |
# MAGIC
# MAGIC Step 0 leaves this as a skeleton that proves the job wiring works; step 1 fills it in.

# COMMAND ----------

dbutils.widgets.text("catalog", "juno")
dbutils.widgets.text("schema", "restaurant")
dbutils.widgets.text("volume", "raw")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")

# The workspace default catalog is not juno, so always qualify names.
spark.sql(f"USE CATALOG {catalog}")
spark.sql(f"USE SCHEMA {schema}")

volume_path = f"/Volumes/{catalog}/{schema}/{volume}"
print(f"catalog={catalog} schema={schema} volume_path={volume_path}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1 goes here
# MAGIC
# MAGIC 1. Download `MEMD_ABSA_Dataset/Restaurant/{Train,Dev,Test}.json` from the upstream GitHub
# MAGIC    repository into `volume_path` (the dataset is never committed to git).
# MAGIC 2. Load to `raw_sentences`, then explode the quadruples.
# MAGIC 3. Expect 5,152 sentences and 8,496 labels across 12 categories.

# COMMAND ----------

display(spark.sql("SELECT current_catalog(), current_schema()"))
