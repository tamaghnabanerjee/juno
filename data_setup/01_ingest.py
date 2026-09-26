# Databricks notebook source
# MAGIC %md
# MAGIC # 01 — Ingest MEMD-ABSA Restaurant
# MAGIC
# MAGIC Downloads the dataset into the Unity Catalog volume and writes it to `raw_sentences`
# MAGIC exactly as it arrives. No reshaping happens here — that is `02_curate`.

# COMMAND ----------

dbutils.widgets.text("catalog", "juno")
dbutils.widgets.text("schema", "restaurant")
dbutils.widgets.text("volume", "raw")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")

# The workspace default catalog is not juno, so set it explicitly.
spark.sql(f"USE CATALOG {catalog}")
spark.sql(f"USE SCHEMA {schema}")

volume_path = f"/Volumes/{catalog}/{schema}/{volume}"
SPLITS = ["Train", "Dev", "Test"]
print(f"writing into {catalog}.{schema}, volume {volume_path}")

# COMMAND ----------

# MAGIC %md ## Download
# MAGIC The dataset has no upstream licence file, so it is never committed to the repository; it is
# MAGIC fetched from source instead. Files already in the volume are left alone, so re-runs are free
# MAGIC and a manual upload still works if egress is ever blocked.

# COMMAND ----------

import os
import shutil
import urllib.request

BASE = "https://raw.githubusercontent.com/NUSTM/MEMD-ABSA/main/MEMD_ABSA_Dataset/Restaurant"

# Stream straight into the volume. Serverless compute blocks the local filesystem
# ("Cannot access non /Workspace local filesystem path"), so staging through /tmp fails;
# /Volumes paths are allowed and can be written with ordinary Python file I/O.
for split in SPLITS:
    target = f"{volume_path}/{split}.json"
    if os.path.exists(target):
        print(f"skip   {split}.json (already in the volume)")
        continue
    with urllib.request.urlopen(f"{BASE}/{split}.json") as response, open(target, "wb") as out:
        shutil.copyfileobj(response, out)
    print(f"loaded {split}.json ({os.path.getsize(target):,} bytes)")

display(dbutils.fs.ls(volume_path))

# COMMAND ----------

# MAGIC %md ## Bronze — `raw_sentences`
# MAGIC Written as-is, plus which split each record came from and when it was loaded.

# COMMAND ----------

from pyspark.sql import functions as F

bronze = None
for split in SPLITS:
    df = (
        spark.read.option("multiLine", "true").json(f"{volume_path}/{split}.json")
        .withColumn("source_split", F.lit(split))
    )
    bronze = df if bronze is None else bronze.unionByName(df)

(
    bronze.withColumn("ingested_at", F.current_timestamp())
    .write.mode("overwrite").option("overwriteSchema", "true")
    .saveAsTable("raw_sentences")
)

rows = spark.table("raw_sentences").count()
print(f"raw_sentences: {rows} rows")
assert rows == 5152, f"expected 5152 records from upstream, got {rows}"
spark.table("raw_sentences").printSchema()
