"""The counting tool behind every "how many" answer.

The LLM never writes SQL. It chooses a category, a sentiment and a grouping, and this module
assembles a fixed template from them. Anything it does not recognise raises ValueError, so a
prompt-injected string cannot reach the warehouse.
"""

from __future__ import annotations

from typing import Any

# The 12 MEMD-ABSA Restaurant categories, exactly as they appear in the human labels.
CATEGORIES: tuple[str, ...] = (
    "Ambience#General",
    "Drinks#Prices",
    "Drinks#Quality",
    "Drinks#Style_Options",
    "Food#Prices",
    "Food#Quality",
    "Food#Style_Options",
    "Location#General",
    "Restaurant#General",
    "Restaurant#Miscellaneous",
    "Restaurant#Prices",
    "Service#General",
)

SENTIMENTS: tuple[str, ...] = ("POS", "NEG", "NEU")

GROUPABLE: tuple[str, ...] = ("category", "sentiment")


def _check(value: str, allowed: tuple[str, ...], what: str) -> str:
    if value not in allowed:
        raise ValueError(f"unknown {what}: {value!r}. Allowed: {', '.join(allowed)}")
    return value


def build_count_sql(
    table: str,
    *,
    category: str | None = None,
    sentiment: str | None = None,
    group_by: str | None = None,
    top_n: int | None = None,
) -> tuple[str, dict[str, Any]]:
    """Return (sql, parameters) for a count over every labelled row.

    Counts come back with the share of the filtered total, because most questions ask "what share".
    With `group_by` the result is one row per category or sentiment, ordered by count, which is what
    a "top themes" question needs.
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

    # `table` is never LLM-supplied; it comes from config.
    if group_by is None:
        sql = (
            "SELECT COUNT(*) AS n,\n"
            "       ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM {t}), 1) AS pct_of_all\n"
            "FROM {t}\n"
            "{where}"
        ).format(t=table, where=where)
    else:
        sql = (
            "SELECT {g} AS group_value, COUNT(*) AS n,\n"
            "       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct_of_filtered\n"
            "FROM {t}\n"
            "{where}\n"
            "GROUP BY {g}\n"
            "ORDER BY n DESC"
        ).format(g=group_by, t=table, where=where)
        if top_n is not None:
            sql += f"\nLIMIT {int(top_n)}"

    return sql.strip(), params
