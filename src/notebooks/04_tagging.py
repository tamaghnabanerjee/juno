# Databricks notebook source
# MAGIC %md
# MAGIC # 04 — Label every sentence, and prove how far the labels can be trusted
# MAGIC
# MAGIC Juno counts rows in `review_facts`. If the labels are wrong, Juno is wrong — however good the
# MAGIC agent is. `docs/design.md` sets the rules this notebook follows. It runs in one of two stages.
# MAGIC
# MAGIC **`stage = trial`** — label the first `trial_size` sentences and hold **checkpoint 1**:
# MAGIC
# MAGIC 1. of the "how many" questions with at least 30 sentences in the trial, at least 80% must have
# MAGIC    a tagger count within 10% of the human count;
# MAGIC 2. the average F1 score over the 12 categories must be at least 0.60.
# MAGIC
# MAGIC The result is saved as one row in `tagging_trials`. A failed checkpoint is a result, not a
# MAGIC crash: adjust the instructions in `src/juno/tagging.py` and run the trial again.
# MAGIC
# MAGIC **`stage = full`** — label all 5,152 sentences, once, into `review_facts`. It refuses to start
# MAGIC unless the latest trial for the same model and instructions passed. It then holds
# MAGIC **checkpoint 2**: all 18 "how many" questions marked on the full data, saved to `checkpoint2`.
# MAGIC After this the tagger is not changed.
# MAGIC
# MAGIC The tagger sees one sentence and the list of categories. It never sees the human labels or the
# MAGIC evaluation questions.

# COMMAND ----------

dbutils.widgets.text("catalog", "juno")
dbutils.widgets.text("schema", "restaurant")
dbutils.widgets.text("model", "databricks-meta-llama-3-3-70b-instruct")
dbutils.widgets.text("trial_size", "1500")
dbutils.widgets.dropdown("stage", "trial", ["trial", "full"])
dbutils.widgets.text("instructions_version", "")
dbutils.widgets.text("preferred_order", "")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
model = dbutils.widgets.get("model").strip()
trial_size = int(dbutils.widgets.get("trial_size"))
stage = dbutils.widgets.get("stage")

spark.sql(f"USE CATALOG {catalog}")
spark.sql(f"USE SCHEMA {schema}")

import os
import re
import sys
from datetime import datetime, timezone

notebook_path = (
    dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
)
src_dir = "/Workspace" + os.path.dirname(os.path.dirname(notebook_path))
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from juno import scoring, tagging  # noqa: E402
from juno.counting import CATEGORIES, SENTIMENTS  # noqa: E402

version = dbutils.widgets.get("instructions_version").strip() or tagging.CURRENT_VERSION
INSTRUCTIONS = tagging.get(version)
preferred_order = [m.strip() for m in dbutils.widgets.get("preferred_order").split(",") if m.strip()]

# The model name goes into SQL text, so it may only be what an endpoint name can be.
assert re.fullmatch(r"[A-Za-z0-9._-]+", model), f"not a valid endpoint name: {model!r}"

TOTAL_SENTENCES = 5152

print(f"stage={stage} model={model} instructions={version} trial_size={trial_size}")

# COMMAND ----------

# MAGIC %md ## No dataset sentence inside the instructions
# MAGIC The examples in the instructions are written by hand. A real labelled sentence would leak
# MAGIC ground truth into the answering path, so this stops the run before anything is labelled.

# COMMAND ----------

corpus = spark.table("sentences").select("sentence_id", "text").collect()
leaked = set(tagging.leaked_sentences(INSTRUCTIONS, [r["text"] for r in corpus]))
leaked_ids = sorted(r["sentence_id"] for r in corpus if r["text"] in leaked)
assert not leaked_ids, (
    f"{len(leaked_ids)} dataset sentence(s) appear word for word inside instructions {version}: "
    f"{leaked_ids}. Rewrite those examples by hand before labelling anything."
)
print(f"checked {len(corpus)} sentences against instructions {version}: none appears inside them")

# COMMAND ----------

# MAGIC %md ## Helpers
# MAGIC The trial and the full run are labelled and measured the same way, so the numbers are
# MAGIC comparable.

# COMMAND ----------


def safe(name: str) -> str:
    """A model name as part of a table name."""
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()


def label(source_table: str, target_table: str) -> dict[str, int]:
    """Run the tagger over a table of sentences: one row per (sentence, category, sentiment).

    The raw replies are kept in `<target>_raw` so a badly formatted reply can be looked at. A
    sentence that fails does not stop the run; it is counted. With `failOnError => false` the reply
    is a struct; it is read through JSON so that the name of its text field does not matter.
    """
    raw = f"{target_table}_raw"
    spark.sql(
        f"""
        CREATE OR REPLACE TABLE {raw} AS
        SELECT sentence_id,
               TO_JSON(ai_query('{model}', CONCAT(:instructions, text), failOnError => false)) AS reply
        FROM {source_table}
        """,
        args={"instructions": INSTRUCTIONS},
    )
    reply_text = "COALESCE(GET_JSON_OBJECT(reply, '$.response'), GET_JSON_OBJECT(reply, '$.result'))"
    spark.sql(f"""
        CREATE OR REPLACE TABLE {target_table} AS
        WITH parsed AS (
            SELECT sentence_id, FROM_JSON({reply_text}, '{tagging.TAGS_SCHEMA}') AS tags
            FROM {raw}
        )
        SELECT DISTINCT
               sentence_id,
               tag.category AS category,
               tag.sentiment AS sentiment,
               '{model}' AS model,
               '{version}' AS instructions_version,
               CURRENT_TIMESTAMP() AS tagged_at
        FROM parsed
        LATERAL VIEW EXPLODE(tags) t AS tag
        WHERE tag.category IN ({",".join(f"'{c}'" for c in CATEGORIES)})
          AND tag.sentiment IN ({",".join(f"'{s}'" for s in SENTIMENTS)})
    """)
    stats = spark.sql(f"""
        SELECT COUNT(*) AS n,
               COUNT_IF(GET_JSON_OBJECT(reply, '$.errorMessage') IS NOT NULL) AS failed,
               COUNT_IF(GET_JSON_OBJECT(reply, '$.errorMessage') IS NULL
                        AND FROM_JSON({reply_text}, '{tagging.TAGS_SCHEMA}') IS NULL) AS unreadable
        FROM {raw}
    """).collect()[0]
    print(f"{stats['n']} sentences sent; {stats['failed']} failed; "
          f"{stats['unreadable']} came back in a form that could not be read")
    return {"failed": stats["failed"], "unreadable": stats["unreadable"]}


def _restrict(restrict_to: str | None, word: str) -> str:
    return f"{word} sentence_id IN (SELECT sentence_id FROM {restrict_to})" if restrict_to else ""


def triples(table: str, restrict_to: str | None = None) -> set[tuple[str, str, str]]:
    rows = spark.sql(
        f"SELECT sentence_id, category, sentiment FROM {table} {_restrict(restrict_to, 'WHERE')}"
    ).collect()
    return {(r["sentence_id"], r["category"], r["sentiment"]) for r in rows}


def how_many_questions() -> list:
    """The 18 "how many" questions: the only ones count closeness is marked on."""
    return spark.sql("""
        SELECT question_id, question, split,
               params['category'] AS category, params['sentiment'] AS sentiment
        FROM eval_questions WHERE qtype = 'count'
        ORDER BY question_id
    """).collect()


def counts(table: str, restrict_to: str | None = None) -> dict[tuple[str, str], int]:
    rows = spark.sql(f"""
        SELECT category, sentiment, COUNT(DISTINCT sentence_id) AS n
        FROM {table} WHERE 1=1 {_restrict(restrict_to, 'AND')} GROUP BY category, sentiment
    """).collect()
    return {(r["category"], r["sentiment"]): r["n"] for r in rows}


def measure(tagged: str, restrict_to: str | None = None) -> dict:
    """Both measures, for whatever has been labelled."""
    pairs = sorted({(q["category"], q["sentiment"]) for q in how_many_questions()})
    human, llm = counts("human_labels", restrict_to), counts(tagged, restrict_to)
    # A question with no human sentences in this slice has no percentage to be off by.
    errors = {
        p: scoring.relative_error(llm.get(p, 0), human[p]) for p in pairs if human.get(p, 0) > 0
    }
    scores = scoring.by_category(triples(tagged, restrict_to), triples("human_labels", restrict_to))
    return {"human": human, "llm": llm, "errors": errors, "scores": scores}


def show(m: dict, result: scoring.Checkpoint1 | None = None) -> None:
    print(f"{'category':<26}{'P':>6}{'R':>6}{'F1':>6}")
    for category, s in m["scores"].items():
        print(f"{category:<26}{s.precision:>6.2f}{s.recall:>6.2f}{s.f1:>6.2f}")
    print(f"\n{'average F1':<26}{scoring.macro_f1(m['scores']):>18.2f}\n")

    print(f"{'how many question':<30}{'human':>7}{'tagger':>8}{'off by':>9}  mark")
    for pair, err in sorted(m["errors"].items(), key=lambda kv: -m["human"][kv[0]]):
        if result is not None and pair in result.skipped:
            mark = f"skipped (fewer than {scoring.MIN_TRIAL_SUPPORT})"
        else:
            mark = "tick" if scoring.within_tolerance(err) else "cross"
        print(f"{pair[0] + ' ' + pair[1]:<30}{m['human'][pair]:>7}{m['llm'].get(pair, 0):>8}"
              f"{err:>+9.1%}  {mark}")
    if result is not None:
        print()
        for line in result.lines():
            print(line)


def write_quality(target: str, tagged: str, restrict_to: str | None = None) -> None:
    """One row per (category, sentiment): both counts, how far apart, and the agreement."""
    h_where, l_where = _restrict(restrict_to, "WHERE"), _restrict(restrict_to, "WHERE")
    spark.sql(f"""
        CREATE OR REPLACE TABLE {target} AS
        WITH h AS (SELECT * FROM human_labels {h_where}),
             l AS (SELECT * FROM {tagged} {l_where}),
        human AS (
            SELECT category, sentiment, COUNT(DISTINCT sentence_id) AS human_n
            FROM h GROUP BY category, sentiment
        ),
        llm AS (
            SELECT category, sentiment, COUNT(DISTINCT sentence_id) AS llm_n
            FROM l GROUP BY category, sentiment
        ),
        agreement AS (
            SELECT COALESCE(h.category, l.category) AS category,
                   COALESCE(h.sentiment, l.sentiment) AS sentiment,
                   COUNT(*) FILTER (WHERE h.sentence_id IS NOT NULL AND l.sentence_id IS NOT NULL) AS tp,
                   COUNT(*) FILTER (WHERE h.sentence_id IS NULL) AS fp,
                   COUNT(*) FILTER (WHERE l.sentence_id IS NULL) AS fn
            FROM h
            FULL OUTER JOIN l
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


def pair_name(pair: tuple[str, str]) -> str:
    return f"{pair[0]} {pair[1]}"


TRIALS_SCHEMA = (
    "run_at timestamp, model string, instructions_version string, trial_size int, "
    "marked array<string>, skipped array<string>, ticks int, counts_ok boolean, "
    "macro_f1 double, f1_ok boolean, passed boolean, "
    "sentences_failed int, sentences_unreadable int, "
    "f1_by_category map<string,double>, count_error_by_question map<string,double>, "
    "labels_table string"
)


def latest_trials() -> list:
    """The most recent trial of each model, for these instructions and this trial size."""
    if not spark.catalog.tableExists("tagging_trials"):
        return []
    return spark.sql(
        """
        SELECT * FROM (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY model ORDER BY run_at DESC) AS rn
            FROM tagging_trials
            WHERE instructions_version = :version AND trial_size = :trial_size
        ) WHERE rn = 1
        """,
        args={"version": version, "trial_size": trial_size},
    ).collect()


def as_pairs(names: list[str]) -> tuple[tuple[str, str], ...]:
    """Undo pair_name: 'Service#General NEG' back to ('Service#General', 'NEG')."""
    return tuple(tuple(name.rsplit(" ", 1)) for name in names)


def as_checkpoint1(row) -> scoring.Checkpoint1:
    return scoring.Checkpoint1(
        ticks=row["ticks"], marked=as_pairs(row["marked"]), skipped=as_pairs(row["skipped"]),
        macro_f1=row["macro_f1"],
    )

# COMMAND ----------

# MAGIC %md ## Stage `trial` — checkpoint 1
# MAGIC The trial sentences are the first `trial_size` when sorted by id. The id is a hash of the
# MAGIC text, so the pick is effectively random, the same on every run, and a larger trial contains
# MAGIC every smaller one.

# COMMAND ----------

trial_sentences = f"_trial_sentences_{trial_size}"

if stage == "trial":
    spark.sql(f"""
        CREATE OR REPLACE TABLE {trial_sentences} AS
        SELECT sentence_id, text FROM sentences ORDER BY sentence_id LIMIT {trial_size}
    """)
    labels_table = f"_trial_labels_{safe(model)}_{version}_{trial_size}"
    stats = label(trial_sentences, labels_table)

    m = measure(labels_table, restrict_to=trial_sentences)
    support = {pair: m["human"].get(pair, 0) for pair in m["errors"]}
    result = scoring.checkpoint1(m["errors"], support, m["scores"])
    print()
    show(m, result)

    row = (
        datetime.now(timezone.utc), model, version, trial_size,
        [pair_name(p) for p in result.marked], [pair_name(p) for p in result.skipped],
        result.ticks, result.counts_ok, result.macro_f1, result.f1_ok, result.passed,
        stats["failed"], stats["unreadable"],
        {c: s.f1 for c, s in m["scores"].items()},
        {pair_name(p): e for p, e in m["errors"].items()},
        labels_table,
    )
    spark.createDataFrame([row], TRIALS_SCHEMA).write.mode("append").saveAsTable("tagging_trials")
    print(f"\ncheckpoint 1 {'PASSED' if result.passed else 'FAILED'} — saved to tagging_trials")

# COMMAND ----------

# MAGIC %md ## Where the models stand
# MAGIC Trials made with identical instructions on the same sentences, compared in the order fixed in
# MAGIC `docs/design.md` section 7: meets both conditions, then average F1, then ticks, then the
# MAGIC preferred order.

# COMMAND ----------

if stage == "trial":
    trials = {r["model"]: as_checkpoint1(r) for r in latest_trials()}
    for name, r in trials.items():
        print(f"{name:<40} passed={r.passed!s:<6} average F1={r.macro_f1:.2f} "
              f"ticks={r.ticks} of {len(r.marked)}")
    if len(trials) > 1 and not preferred_order:
        print("\nmore than one model tried: give `preferred_order` to pick the winner")
    elif trials:
        try:
            winner, reason = scoring.pick_winner(trials, preferred_order or list(trials))
            print(f"\nahead: {winner} ({reason})")
        except ValueError as e:
            print(f"\ncannot pick a winner yet: {e}")
    dbutils.notebook.exit("passed" if result.passed else "failed")

# COMMAND ----------

# MAGIC %md ## Stage `full` — the whole corpus, once
# MAGIC Refuses to start unless the **latest** trial for this model and these instructions passed
# MAGIC checkpoint 1. The latest, not any: an earlier lucky pass does not count.

# COMMAND ----------

mine = [r for r in latest_trials() if r["model"] == model]
assert mine and mine[0]["passed"], (
    f"no passing trial for model={model}, instructions={version}, trial_size={trial_size}. "
    "Run this notebook with stage = trial first. The full run does not start on a failed checkpoint 1."
)
print(f"latest trial passed at {mine[0]['run_at']}: average F1 {mine[0]['macro_f1']:.2f}, "
      f"{mine[0]['ticks']} ticks of {len(mine[0]['marked'])}")

stats = label("sentences", "review_facts")

total = spark.table("review_facts").count()
sentences_labelled = spark.table("review_facts").select("sentence_id").distinct().count()
print(f"review_facts: {total} rows over {sentences_labelled} sentences (of {TOTAL_SENTENCES})")
print(f"sentences with no label: {TOTAL_SENTENCES - sentences_labelled} "
      "(a sentence about none of the 12 categories rightly has none)")

# COMMAND ----------

# MAGIC %md ## Checkpoint 2 — all 18 "how many" questions, on all the data
# MAGIC Marked once. Nothing stops on a cross: the table governs what the report says
# MAGIC (`docs/design.md` section 6). **After this the tagger is not changed.**

# COMMAND ----------

full = measure("review_facts")
show(full)

rows = [
    (
        q["question_id"], q["question"], q["split"], q["category"], q["sentiment"],
        full["human"].get((q["category"], q["sentiment"]), 0),
        full["llm"].get((q["category"], q["sentiment"]), 0),
        float(full["errors"][(q["category"], q["sentiment"])]),
        scoring.within_tolerance(full["errors"][(q["category"], q["sentiment"])]),
        model, version,
    )
    for q in how_many_questions()
]
spark.createDataFrame(
    rows,
    "question_id string, question string, split string, category string, sentiment string, "
    "human_n int, tagger_n int, rel_error double, tick boolean, model string, "
    "instructions_version string",
).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable("checkpoint2")

ticks = sum(r[8] for r in rows)
scored = [r for r in rows if r[2] == "test"]
print(f"\ncheckpoint 2: {ticks} ticks and {len(rows) - ticks} crosses over {len(rows)} questions")
print(f"of the {len(scored)} questions Juno is scored on: {sum(r[8] for r in scored)} ticks")
display(spark.table("checkpoint2").orderBy("human_n", ascending=False))

known = next(r for r in rows if (r[3], r[4]) == ("Service#General", "NEG"))
assert known[5] == 466, "human ground truth changed — investigate before trusting anything"

# COMMAND ----------

# MAGIC %md ## The evidence
# MAGIC `tagging_quality` — every (category, sentiment) on all the data.
# MAGIC `tagging_quality_untouched` — the same, on the sentences that were never in a trial run. No
# MAGIC adjusting ever saw them, so this is the honest figure for the tagger's general quality. It is
# MAGIC reported; it is not a pass or fail condition.

# COMMAND ----------

write_quality("tagging_quality", "review_facts")

spark.sql(f"""
    CREATE OR REPLACE TABLE _untouched_sentences AS
    SELECT sentence_id FROM sentences
    WHERE sentence_id NOT IN (
        SELECT sentence_id FROM (SELECT sentence_id FROM sentences ORDER BY sentence_id LIMIT {trial_size})
    )
""")
untouched_n = spark.table("_untouched_sentences").count()
assert untouched_n == TOTAL_SENTENCES - trial_size, f"expected {TOTAL_SENTENCES - trial_size}, got {untouched_n}"

write_quality("tagging_quality_untouched", "review_facts", restrict_to="_untouched_sentences")
print(f"on the {untouched_n} sentences never used for adjusting:\n")
show(measure("review_facts", restrict_to="_untouched_sentences"))

display(spark.table("tagging_quality"))
