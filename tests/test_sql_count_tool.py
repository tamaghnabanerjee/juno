import pytest

from juno.sql_count_tool import build_count_sql

TABLE = "juno.restaurant.review_facts"
SENTENCES = "juno.restaurant.sentences"


def test_filters_become_parameters_not_literals():
    sql, params = build_count_sql(TABLE, sentences_table=SENTENCES, category="Service#General", sentiment="NEG")
    assert params == {"category": "Service#General", "sentiment": "NEG"}
    assert "Service#General" not in sql  # the value travels as a parameter, never inlined
    assert "category = :category" in sql and "sentiment = :sentiment" in sql


def test_unfiltered_count_has_no_where_clause():
    sql, params = build_count_sql(TABLE, sentences_table=SENTENCES)
    assert params == {}
    assert "WHERE" not in sql


def test_group_by_orders_by_count_and_limits():
    sql, _ = build_count_sql(TABLE, sentences_table=SENTENCES, sentiment="NEG", group_by="category", top_n=3)
    assert "GROUP BY category" in sql
    assert "ORDER BY n DESC" in sql
    assert sql.endswith("LIMIT 3")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"category": "Food#Quality; DROP TABLE juno.restaurant.review_facts"},
        {"category": "Nonexistent#Category"},
        {"sentiment": "POSITIVE"},
        {"group_by": "sentence_id"},
        {"group_by": "category", "top_n": 0},
    ],
)
def test_unrecognised_input_is_rejected(kwargs):
    with pytest.raises(ValueError):
        build_count_sql(TABLE, sentences_table=SENTENCES, **kwargs)


def test_counts_sentences_not_label_rows():
    sql, _ = build_count_sql(TABLE, sentences_table=SENTENCES, category="Service#General")
    assert "COUNT(DISTINCT sentence_id) AS n" in sql
    assert "COUNT(*) AS n" not in sql


def test_share_of_all_divides_by_the_sentences_table():
    sql, _ = build_count_sql(TABLE, sentences_table=SENTENCES, category="Service#General", sentiment="NEG")
    assert f"(SELECT COUNT(*) FROM {SENTENCES})" in sql
    assert f"(SELECT COUNT(*) FROM {TABLE})" not in sql


def test_share_within_a_sentiment_divides_by_sentences_with_that_sentiment():
    sql, _ = build_count_sql(TABLE, sentences_table=SENTENCES, category="Service#General", sentiment="NEG")
    assert (
        f"(SELECT COUNT(DISTINCT sentence_id) FROM {TABLE} WHERE sentiment = :sentiment)" in sql
    )
    assert "AS pct_within_sentiment" in sql


def test_no_share_within_a_sentiment_when_no_sentiment_is_given():
    sql, _ = build_count_sql(TABLE, sentences_table=SENTENCES, category="Service#General")
    assert "pct_within_sentiment" not in sql


def test_ranking_counts_sentences_and_breaks_ties_by_name():
    sql, _ = build_count_sql(TABLE, sentences_table=SENTENCES, group_by="category", top_n=5)
    assert "COUNT(DISTINCT sentence_id) AS n" in sql
    assert "ORDER BY n DESC, category ASC" in sql


def test_the_sentences_table_is_required():
    with pytest.raises(TypeError):
        build_count_sql(TABLE, category="Service#General")
