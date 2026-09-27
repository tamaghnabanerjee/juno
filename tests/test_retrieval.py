import pytest

from juno.retrieval import build_search_sql

TABLES = {
    "embeddings_table": "juno.restaurant.sentence_embeddings",
    "sentences_table": "juno.restaurant.sentences",
    "labels_table": "juno.restaurant.review_facts",
}
QUESTION = "Why do guests complain about the service? Show examples."


def test_the_question_travels_as_a_parameter():
    sql, params = build_search_sql(QUESTION, k=20, **TABLES)
    assert params == {"question": QUESTION}
    assert QUESTION not in sql
    assert "ai_query('databricks-gte-large-en', :question)" in sql


def test_no_label_searches_all_sentences():
    sql, _ = build_search_sql(QUESTION, k=20, **TABLES)
    assert "WHERE" not in sql
    assert sql.endswith("LIMIT 20")


def test_a_label_filters_on_the_tagger_labels_through_parameters():
    sql, params = build_search_sql(
        QUESTION, k=10, category="Service#General", sentiment="NEG", **TABLES
    )
    assert params == {"question": QUESTION, "category": "Service#General", "sentiment": "NEG"}
    assert "Service#General" not in sql
    assert "FROM juno.restaurant.review_facts" in sql
    assert "WHERE category = :category AND sentiment = :sentiment" in sql
    assert sql.endswith("LIMIT 10")


def test_similarity_divides_by_both_lengths():
    sql, _ = build_search_sql(QUESTION, k=5, **TABLES)
    assert "SQRT(AGGREGATE(e.embedding, 0D, (t, x) -> t + x * x))" in sql
    assert "SQRT(AGGREGATE(q.v, 0D, (t, x) -> t + x * x))" in sql
    assert "ORDER BY similarity DESC, s.sentence_id" in sql


@pytest.mark.parametrize("k", [0, 21, 2.5, "20"])
def test_k_outside_1_to_20_is_rejected(k):
    with pytest.raises(ValueError, match="k must be"):
        build_search_sql(QUESTION, k=k, **TABLES)


@pytest.mark.parametrize(
    "label", [{"category": "Service#General"}, {"sentiment": "NEG"}]
)
def test_half_a_label_is_rejected(label):
    with pytest.raises(ValueError, match="both a category and a sentiment"):
        build_search_sql(QUESTION, k=10, **label, **TABLES)


@pytest.mark.parametrize(
    "category",
    ["Nonexistent#Category", "Service#General') OR 1=1 --"],
)
def test_unknown_or_injected_category_is_rejected(category):
    with pytest.raises(ValueError, match="unknown category"):
        build_search_sql(QUESTION, k=10, category=category, sentiment="NEG", **TABLES)


def test_unknown_sentiment_is_rejected():
    with pytest.raises(ValueError, match="unknown sentiment"):
        build_search_sql(QUESTION, k=10, category="Service#General", sentiment="ANGRY", **TABLES)
