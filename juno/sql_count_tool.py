"""The counting tool behind every "how many" answer.

The LLM never writes SQL. It chooses a category, a sentiment and a grouping, and this module
assembles a fixed template from them. Anything it does not recognise raises ValueError, so a
prompt-injected string cannot reach the warehouse.
"""

from __future__ import annotations

from typing import Any

from juno.categories import CATEGORIES, SENTIMENTS

GROUPABLE: tuple[str, ...] = ("category", "sentiment")


def _check(value: str, allowed: tuple[str, ...], what: str) -> str:
    if value not in allowed:
        raise ValueError(f"unknown {what}: {value!r}. Allowed: {', '.join(allowed)}")
    return value


def build_count_sql(
    table: str,
    *,
    sentences_table: str,
    category: str | None = None,
    sentiment: str | None = None,
    group_by: str | None = None,
    top_n: int | None = None,
) -> tuple[str, dict[str, Any]]:
    """Return (sql, parameters) for a count of sentences.

    Every count is of distinct sentences, the unit the test set counts. `table` and
    `sentences_table` come from the calling code, never from the LLM.

    Without `group_by`: the count, its share of all sentences, and, when a sentiment is given, its
    share of the sentences carrying that sentiment. With `group_by`: one row per category or
    sentiment, largest first, ties broken by name, for "top topics" questions.
    """
    if group_by is not None:
        _check(group_by, GROUPABLE, "group_by")
    if top_n is not None and (not isinstance(top_n, int) or top_n < 1 or top_n > 50):
        raise ValueError(f"top_n must be an int between 1 and 50, got {top_n!r}")

    params: dict[str, Any] = {}
    filters: list[str] = []
    if category is not None:
        params["category"] = _check(category, CATEGORIES, "category")
        filters.append("category = :category")
    if sentiment is not None:
        params["sentiment"] = _check(sentiment, SENTIMENTS, "sentiment")
        filters.append("sentiment = :sentiment")
    where = f"WHERE {' AND '.join(filters)}" if filters else ""

    n = "COUNT(DISTINCT sentence_id)"
    if group_by is None:
        columns = [
            f"{n} AS n",
            (
                f"ROUND(100.0 * {n} / NULLIF((SELECT COUNT(*) FROM {sentences_table}), 0), 1)"
                " AS pct_of_all_sentences"
            ),
        ]
        if sentiment is not None:
            columns.append(
                f"ROUND(100.0 * {n} / NULLIF((SELECT {n} FROM {table}"
                " WHERE sentiment = :sentiment), 0), 1) AS pct_within_sentiment"
            )
        sql = "SELECT " + ",\n       ".join(columns) + f"\nFROM {table}\n{where}"
    else:
        sql = (
            f"SELECT {group_by} AS group_value, {n} AS n\n"
            f"FROM {table}\n"
            f"{where}\n"
            f"GROUP BY {group_by}\n"
            f"ORDER BY n DESC, {group_by} ASC"
        )
        if top_n is not None:
            sql += f"\nLIMIT {int(top_n)}"

    return sql.strip(), params
