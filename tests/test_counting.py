import pytest

from juno.counting import build_count_sql

TABLE = "juno.restaurant.review_facts"


def test_filters_become_parameters_not_literals():
    sql, params = build_count_sql(TABLE, category="Service#General", sentiment="NEG")
    assert params == {"category": "Service#General", "sentiment": "NEG"}
    assert "Service#General" not in sql  # the value travels as a parameter, never inlined
    assert "category = :category" in sql and "sentiment = :sentiment" in sql


def test_unfiltered_count_has_no_where_clause():
    sql, params = build_count_sql(TABLE)
    assert params == {}
    assert "WHERE" not in sql


def test_group_by_orders_by_count_and_limits():
    sql, _ = build_count_sql(TABLE, sentiment="NEG", group_by="category", top_n=3)
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
        build_count_sql(TABLE, **kwargs)
