# Databricks notebook source
# MAGIC %md
# MAGIC # 04 — Tag every sentence, and prove the tags are usable
# MAGIC
# MAGIC Juno counts rows in `review_facts`. If the tags are wrong, Juno is wrong — however good the
# MAGIC agent is. So this notebook measures before it spends:
# MAGIC
# MAGIC 1. tag a sample
# MAGIC 2. score it against `human_labels`
# MAGIC 3. **gate** — stop unless the tagger can already meet Juno's count target
# MAGIC 4. tag all 5,152 sentences
# MAGIC 5. publish `tagging_quality`, the evidence that the table is fit to count
# MAGIC
# MAGIC The tagger sees one sentence and the list of categories. It never sees the human labels or the
# MAGIC evaluation questions.

# COMMAND ----------

dbutils.widgets.text("catalog", "juno")
dbutils.widgets.text("schema", "restaurant")
dbutils.widgets.text("model", "databricks-gpt-oss-120b")
dbutils.widgets.text("sample_size", "500")
dbutils.widgets.dropdown("stage", "sample", ["sample", "full"])

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
model = dbutils.widgets.get("model")
sample_size = int(dbutils.widgets.get("sample_size"))
stage = dbutils.widgets.get("stage")

spark.sql(f"USE CATALOG {catalog}")
spark.sql(f"USE SCHEMA {schema}")

import os
import sys

notebook_path = (
    dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
)
src_dir = "/Workspace" + os.path.dirname(os.path.dirname(notebook_path))
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from juno import scoring  # noqa: E402
from juno.counting import CATEGORIES, SENTIMENTS  # noqa: E402

print(f"model={model} stage={stage} sample_size={sample_size}")

# COMMAND ----------

# MAGIC %md ## The prompt
# MAGIC The two examples are hand-written, not taken from the dataset: a real labelled sentence in the
# MAGIC prompt would leak ground truth into the answering path.

# COMMAND ----------

PROMPT = """You label restaurant review sentences for topic and sentiment.

Categories (use these exact strings):
""" + "\n".join(f"- {c}" for c in CATEGORIES) + """

Rules:
- One entry per topic the sentence actually discusses. A sentence may cover several.
- sentiment is POS, NEG or NEU, from the writer's point of view.
- The same topic may appear twice with different sentiments if the writer is mixed about it.
- If the sentence discusses none of the categories, return [].
- Return JSON only, no explanation.

Example: "The pasta was cold but our waiter was lovely."
[{"category": "Food#Quality", "sentiment": "NEG"}, {"category": "Service#General", "sentiment": "POS"}]

Example: "We parked round the back."
[]

Sentence: """

TAGS_SCHEMA = "array<struct<category:string,sentiment:string>>"

def tag(source_table: str, target_table: str) -> None:
    """Run the tagger over a table of sentences and write one row per (sentence, category, sentiment)."""
    spark.sql(f"""
        CREATE OR REPLACE TABLE {target_table} AS
        WITH raw AS (
            SELECT sentence_id,
                   ai_query('{model}', CONCAT(:prompt, text)) AS response
            FROM {source_table}
        ),
        parsed AS (
            SELECT sentence_id, response, FROM_JSON(response, '{TAGS_SCHEMA}') AS tags
            FROM raw
        )
        SELECT DISTINCT
               sentence_id,
               tag.category AS category,
               tag.sentiment AS sentiment,
               '{model}' AS model,
               CURRENT_TIMESTAMP() AS tagged_at
        FROM parsed
        LATERAL VIEW EXPLODE(tags) t AS tag
        WHERE tag.category IN ({",".join(f"'{c}'" for c in CATEGORIES)})
          AND tag.sentiment IN ({",".join(f"'{s}'" for s in SENTIMENTS)})
    """, args={"prompt": PROMPT})

# COMMAND ----------

# MAGIC %md ## Helpers: score whatever has been tagged
# MAGIC Both the sample and the full run are measured the same way, so the numbers are comparable.

# COMMAND ----------

def triples(table: str, restrict_to: str | None = None) -> set[tuple[str, str, str]]:
    where = f"WHERE sentence_id IN (SELECT sentence_id FROM {restrict_to})" if restrict_to else ""
    rows = spark.sql(f"SELECT sentence_id, category, sentiment FROM {table} {where}").collect()
    return {(r["sentence_id"], r["category"], r["sentiment"]) for r in rows}


def count_errors(tagged: str, restrict_to: str | None = None) -> dict[tuple[str, str], float]:
    """Relative count error per (category, sentiment), for the pairs the evaluation asks about."""
    eval_pairs = {
        (r["category"], r["sentiment"])
        for r in spark.sql("""
            SELECT DISTINCT params['category'] AS category, params['sentiment'] AS sentiment
            FROM eval_questions WHERE params['category'] IS NOT NULL
        """).collect()
    }
    where = f"AND sentence_id IN (SELECT sentence_id FROM {restrict_to})" if restrict_to else ""

    def counts(table: str) -> dict[tuple[str, str], int]:
        rows = spark.sql(f"""
            SELECT category, sentiment, COUNT(DISTINCT sentence_id) AS n
            FROM {table} WHERE 1=1 {where} GROUP BY category, sentiment
        """).collect()
        return {(r["category"], r["sentiment"]): r["n"] for r in rows}

    human, llm = counts("human_labels"), counts(tagged)
    return {
        pair: scoring.relative_error(llm.get(pair, 0), human.get(pair, 0))
        for pair in sorted(eval_pairs)
        if human.get(pair, 0) > 0
    }


def report(tagged: str, restrict_to: str | None = None) -> tuple[bool, dict]:
    predicted = triples(tagged, restrict_to)
    actual = triples("human_labels", restrict_to)
    scores = scoring.by_category(predicted, actual)
    errors = count_errors(tagged, restrict_to)

    print(f"{'category':<26}{'P':>6}{'R':>6}{'F1':>6}")
    for category, s in scores.items():
        print(f"{category:<26}{s.precision:>6.2f}{s.recall:>6.2f}{s.f1:>6.2f}")
    print(f"\n{'macro-F1':<26}{scoring.macro_f1(scores):>18.2f}\n")

    print(f"{'count error':<26}{'human':>7}{'llm':>7}{'err':>8}")
    for (category, sentiment), err in sorted(errors.items(), key=lambda kv: -abs(kv[1])):
        print(f"{category + ' ' + sentiment:<26}{'':>7}{'':>7}{err:>+8.1%}")

    ok, lines = scoring.passes_gate(errors, scores)
    print()
    for line in lines:
        print(line)
    return ok, {"scores": scores, "errors": errors}

# COMMAND ----------

# MAGIC %md ## Stage 1 — sample
# MAGIC A deterministic slice of the corpus, so a re-run measures the same sentences.

# COMMAND ----------

spark.sql(f"""
    CREATE OR REPLACE TABLE _tagging_sample AS
    SELECT sentence_id, text FROM sentences ORDER BY sentence_id LIMIT {sample_size}
""")

tag("_tagging_sample", "_tagging_sample_facts")

sample_rows = spark.table("_tagging_sample_facts").count()
print(f"tagged {sample_size} sentences -> {sample_rows} label rows\n")

gate_ok, _ = report("_tagging_sample_facts", restrict_to="_tagging_sample")

# COMMAND ----------

# MAGIC %md ## The gate
# MAGIC Juno's target is "within 10% on at least 80% of count questions". The tagger has to clear that
# MAGIC on its own, or the target is unreachable no matter how good the agent is. A failure here means
# MAGIC fix the prompt or change the model and re-run this notebook with `stage = sample` — **not**
# MAGIC proceed and hope.

# COMMAND ----------

if stage == "sample":
    assert gate_ok, (
        "gate failed on the sample: iterate on the prompt or model before the full run. "
        "If two rounds cannot pass it, record the decision in the log and lower the target "
        "with this measurement as the evidence."
    )
    print("gate passed — re-run with stage = full to tag the whole corpus")
    dbutils.notebook.exit("gate passed")

# COMMAND ----------

# MAGIC %md ## Stage 2 — the full corpus
# MAGIC 5,152 sentences. Only reached when `stage = full`, which the job sets after the gate has passed.

# COMMAND ----------

tag("sentences", "review_facts")

total = spark.table("review_facts").count()
sentences_tagged = spark.table("review_facts").select("sentence_id").distinct().count()
print(f"review_facts: {total} rows over {sentences_tagged} sentences (of 5152)")

# COMMAND ----------

# MAGIC %md ## `tagging_quality` — the evidence
# MAGIC One row per (category, sentiment): what the humans counted, what the tagger counted, and how
# MAGIC far apart they are. This is what goes in the README.

# COMMAND ----------

spark.sql("""
    CREATE OR REPLACE TABLE tagging_quality AS
    WITH human AS (
        SELECT category, sentiment, COUNT(DISTINCT sentence_id) AS human_n
        FROM human_labels GROUP BY category, sentiment
    ),
    llm AS (
        SELECT category, sentiment, COUNT(DISTINCT sentence_id) AS llm_n
        FROM review_facts GROUP BY category, sentiment
    ),
    agreement AS (
        SELECT COALESCE(h.category, l.category) AS category,
               COALESCE(h.sentiment, l.sentiment) AS sentiment,
               COUNT(*) FILTER (WHERE h.sentence_id IS NOT NULL AND l.sentence_id IS NOT NULL) AS tp,
               COUNT(*) FILTER (WHERE h.sentence_id IS NULL) AS fp,
               COUNT(*) FILTER (WHERE l.sentence_id IS NULL) AS fn
        FROM human_labels h
        FULL OUTER JOIN review_facts l
          ON h.sentence_id = l.sentence_id AND h.category = l.category AND h.sentiment = l.sentiment
        GROUP BY 1, 2
    )
    SELECT a.category, a.sentiment,
           COALESCE(human.human_n, 0) AS human_n,
           COALESCE(llm.llm_n, 0) AS llm_n,
           ROUND((COALESCE(llm.llm_n, 0) - COALESCE(human.human_n, 0))
                 / NULLIF(human.human_n, 0), 3) AS rel_error,
           ROUND(a.tp / NULLIF(a.tp + a.fp, 0), 3) AS precision,
           ROUND(a.tp / NULLIF(a.tp + a.fn, 0), 3) AS recall,
           ROUND(2.0 * a.tp / NULLIF(2 * a.tp + a.fp + a.fn, 0), 3) AS f1,
           a.tp, a.fp, a.fn
    FROM agreement a
    LEFT JOIN human ON human.category = a.category AND human.sentiment = a.sentiment
    LEFT JOIN llm ON llm.category = a.category AND llm.sentiment = a.sentiment
    ORDER BY human_n DESC
""")

display(spark.table("tagging_quality"))

# COMMAND ----------

# MAGIC %md ## Full-corpus verdict

# COMMAND ----------

full_ok, _ = report("review_facts")

known = spark.sql("""
    SELECT human_n, llm_n, rel_error FROM tagging_quality
    WHERE category = 'Service#General' AND sentiment = 'NEG'
""").collect()[0]
print(f"\nService#General NEG: human {known['human_n']}, tagger {known['llm_n']}, "
      f"error {known['rel_error']:+.1%}")
assert known["human_n"] == 466, "human ground truth changed — investigate before trusting anything"

unparsed = 5152 - sentences_tagged
print(f"sentences with no usable tags: {unparsed}")
