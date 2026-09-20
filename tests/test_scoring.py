import pytest

from juno.scoring import (
    Score,
    by_category,
    macro_f1,
    passes_gate,
    relative_error,
    score,
)

HUMAN = {
    ("s1", "Service#General", "NEG"),
    ("s2", "Service#General", "NEG"),
    ("s3", "Food#Quality", "POS"),
}


def test_perfect_agreement():
    s = score(HUMAN, HUMAN)
    assert (s.tp, s.fp, s.fn) == (3, 0, 0)
    assert s.f1 == 1.0


def test_missed_and_invented_labels():
    predicted = {
        ("s1", "Service#General", "NEG"),          # hit
        ("s9", "Drinks#Quality", "POS"),           # invented
    }                                              # s2 and s3 missed
    s = score(predicted, HUMAN)
    assert (s.tp, s.fp, s.fn) == (1, 1, 2)
    assert s.precision == 0.5
    assert s.recall == pytest.approx(1 / 3)


def test_sentiment_must_match_too():
    predicted = {("s1", "Service#General", "POS")}  # right topic, wrong sentiment
    s = score(predicted, {("s1", "Service#General", "NEG")})
    assert (s.tp, s.fp, s.fn) == (0, 1, 1)


def test_empty_prediction_scores_zero_without_dividing_by_zero():
    s = score(set(), HUMAN)
    assert (s.precision, s.recall, s.f1) == (0.0, 0.0, 0.0)


def test_by_category_covers_both_sides():
    predicted = {("s1", "Service#General", "NEG"), ("s9", "Drinks#Quality", "POS")}
    scores = by_category(predicted, HUMAN)
    assert set(scores) == {"Service#General", "Food#Quality", "Drinks#Quality"}
    assert scores["Food#Quality"].fn == 1       # human-only category
    assert scores["Drinks#Quality"].fp == 1     # tagger-only category


def test_macro_f1_treats_small_categories_equally():
    scores = {"big": Score(tp=100, fp=0, fn=0), "small": Score(tp=0, fp=1, fn=1)}
    assert macro_f1(scores) == 0.5


def test_relative_error_signs_and_edges():
    assert relative_error(471, 466) == pytest.approx(0.0107, abs=1e-4)   # over-counting
    assert relative_error(400, 466) == pytest.approx(-0.1416, abs=1e-4)  # under-counting
    assert relative_error(0, 0) == 0.0
    assert relative_error(5, 0) == float("inf")


def test_gate_passes_when_counts_and_f1_are_good():
    # Four of five pairs within tolerance is exactly the 80% bar.
    errors = {
        ("a", "NEG"): 0.02, ("b", "POS"): -0.05, ("c", "NEG"): 0.09,
        ("d", "POS"): 0.08, ("e", "NEG"): 0.30,
    }
    scores = {"a": Score(8, 2, 2), "b": Score(8, 2, 2)}  # f1 = 0.8
    ok, lines = passes_gate(errors, scores)
    assert ok, lines
    assert all(line.startswith("ok") for line in lines)


def test_gate_fails_on_count_error_even_with_good_f1():
    errors = {("a", "NEG"): 0.4, ("b", "POS"): 0.5, ("c", "NEG"): 0.02, ("d", "POS"): 0.01}
    scores = {"a": Score(9, 1, 1)}
    ok, lines = passes_gate(errors, scores)
    assert not ok
    assert any("count error" in line and line.startswith("FAIL") for line in lines)


def test_gate_fails_on_low_f1_even_when_counts_look_fine():
    # Misses and false positives cancel out, so the count is right for the wrong reasons.
    errors = {("a", "NEG"): 0.0, ("b", "POS"): 0.0}
    scores = {"a": Score(tp=2, fp=8, fn=8)}
    ok, lines = passes_gate(errors, scores)
    assert not ok
    assert any("macro-F1" in line and line.startswith("FAIL") for line in lines)
