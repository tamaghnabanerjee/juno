from __future__ import annotations

from typing import Any

from juno.categories import CATEGORIES, SENTIMENTS


def build_search_sql(
    question: str,
    *,
    embeddings_table: str,
    sentences_table: str,
    labels_table: str,
    k: int,
    category: str | None = None,
    sentiment: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Return (sql, parameters) for the k sentences closest in meaning to the question.

    Without a label: searches all sentences (the RAG baseline). With a category and a sentiment:
    searches only sentences the tagger gave that label (the agent's examples). Closeness is cosine
    similarity between the question's embedding and each sentence's stored embedding.
    """
    if not isinstance(k, int) or k < 1 or k > 20:
        raise ValueError(f"k must be an int between 1 and 20, got {k!r}")
    if (category is None) != (sentiment is None):
        raise ValueError("give both a category and a sentiment, or neither")

    params: dict[str, Any] = {"question": question}
    where = ""
    if category is not None:
        if category not in CATEGORIES:
            raise ValueError(f"unknown category: {category!r}")
        if sentiment not in SENTIMENTS:
            raise ValueError(f"unknown sentiment: {sentiment!r}")
        params["category"] = category
        params["sentiment"] = sentiment
        where = (
            f"WHERE e.sentence_id IN (SELECT sentence_id FROM {labels_table}\n"
            "                        WHERE category = :category AND sentiment = :sentiment)"
        )

    sql = f"""
WITH q AS (SELECT ai_query('databricks-gte-large-en', :question) AS v)
SELECT s.sentence_id,
       s.text,
       AGGREGATE(ZIP_WITH(e.embedding, q.v, (x, y) -> x * y), 0D, (t, p) -> t + p)
         / (SQRT(AGGREGATE(e.embedding, 0D, (t, x) -> t + x * x))
            * SQRT(AGGREGATE(q.v, 0D, (t, x) -> t + x * x))) AS similarity
FROM {embeddings_table} AS e
CROSS JOIN q
JOIN {sentences_table} AS s ON s.sentence_id = e.sentence_id
{where}
ORDER BY similarity DESC, s.sentence_id
LIMIT {k}
"""
    return "\n".join(line for line in sql.strip().splitlines() if line.strip()), params
