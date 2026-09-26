import pytest

from juno.scoring import (
    Checkpoint1,
    Score,
    by_category,
    checkpoint1,
    full_run_allowed,
    macro_f1,
    pick_winner,
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


# Every pair below has plenty of sentences, so nothing is skipped unless a test says otherwise.
def _plenty(errors):
    return {pair: 100 for pair in errors}


def test_checkpoint1_passes_when_counts_and_f1_are_good():
    # Four of five pairs within tolerance is exactly the 80% bar.
    errors = {
        ("a", "NEG"): 0.02, ("b", "POS"): -0.05, ("c", "NEG"): 0.09,
        ("d", "POS"): 0.08, ("e", "NEG"): 0.30,
    }
    scores = {"a": Score(8, 2, 2), "b": Score(8, 2, 2)}  # f1 = 0.8
    result = checkpoint1(errors, _plenty(errors), scores)
    assert result.passed, result.lines()
    assert (result.ticks, len(result.marked), len(result.skipped)) == (4, 5, 0)
    assert all(line.startswith("ok") for line in result.lines())


def test_checkpoint1_fails_on_count_error_even_with_good_f1():
    errors = {("a", "NEG"): 0.4, ("b", "POS"): 0.5, ("c", "NEG"): 0.02, ("d", "POS"): 0.01}
    scores = {"a": Score(9, 1, 1)}
    result = checkpoint1(errors, _plenty(errors), scores)
    assert not result.passed
    assert not result.counts_ok and result.f1_ok
    assert any("count within" in line and line.startswith("FAIL") for line in result.lines())


def test_checkpoint1_fails_on_low_f1_even_when_counts_look_fine():
    # Misses and false positives cancel out, so the count is right for the wrong reasons.
    errors = {("a", "NEG"): 0.0, ("b", "POS"): 0.0}
    scores = {"a": Score(tp=2, fp=8, fn=8)}
    result = checkpoint1(errors, _plenty(errors), scores)
    assert not result.passed
    assert result.counts_ok and not result.f1_ok
    assert any("average F1" in line and line.startswith("FAIL") for line in result.lines())


def test_small_questions_are_skipped_not_failed():
    # The design's own case: a good tagger is off by 2 on a 10-sentence question (20%). Marked, that
    # cross would sink it; skipped, it does not count either way.
    errors = {("big", "POS"): 0.02, ("big", "NEG"): -0.04, ("small", "POS"): 0.20}
    support = {("big", "POS"): 550, ("big", "NEG"): 136, ("small", "POS"): 10}
    scores = {"big": Score(8, 2, 2)}
    result = checkpoint1(errors, support, scores)
    assert result.marked == (("big", "NEG"), ("big", "POS"))
    assert result.skipped == (("small", "POS"),)
    assert result.ticks == 2 and result.passed


def test_thirty_sentences_is_marked_and_twenty_nine_is_not():
    errors = {("a", "POS"): 0.0, ("b", "POS"): 0.0}
    result = checkpoint1(errors, {("a", "POS"): 30, ("b", "POS"): 29}, {"a": Score(8, 2, 2)})
    assert result.marked == (("a", "POS"),)
    assert result.skipped == (("b", "POS"),)


def test_a_question_missing_from_the_support_map_is_skipped():
    errors = {("a", "POS"): 0.0}
    assert checkpoint1(errors, {}, {"a": Score(8, 2, 2)}).skipped == (("a", "POS"),)


def test_nothing_big_enough_to_mark_is_not_a_pass():
    errors = {("a", "POS"): 0.0}
    result = checkpoint1(errors, {("a", "POS"): 5}, {"a": Score(9, 1, 1)})
    assert not result.counts_ok and not result.passed


def _trial(ticks, f1, marked=10):
    pairs = tuple((f"q{i}", "POS") for i in range(marked))
    return Checkpoint1(ticks=ticks, marked=pairs, skipped=(), macro_f1=f1)


ORDER = ["preferred", "open"]


def test_winner_step_1_passing_beats_failing_even_with_a_lower_f1():
    results = {"preferred": _trial(7, 0.90), "open": _trial(8, 0.61)}  # 7 of 10 fails condition 1
    winner, reason = pick_winner(results, ORDER)
    assert winner == "open" and reason.startswith("step 1")


def test_winner_step_2_higher_f1_beats_more_ticks():
    # The made-up case in design.md section 7: X has 9 ticks and 0.61, Y has 8 ticks and 0.70.
    results = {"preferred": _trial(9, 0.61), "open": _trial(8, 0.70)}
    winner, reason = pick_winner(results, ORDER)
    assert winner == "open" and reason.startswith("step 2")


def test_winner_step_2_also_applies_when_neither_passes():
    results = {"preferred": _trial(5, 0.40), "open": _trial(6, 0.55)}
    winner, reason = pick_winner(results, ORDER)
    assert winner == "open" and reason.startswith("step 2")


def test_winner_step_3_ticks_decide_when_f1_is_equal_to_two_places():
    results = {"preferred": _trial(8, 0.662), "open": _trial(9, 0.658)}  # both round to 0.66
    winner, reason = pick_winner(results, ORDER)
    assert winner == "open" and reason.startswith("step 3")


def test_winner_step_4_preferred_order_is_the_last_resort():
    results = {"open": _trial(9, 0.66), "preferred": _trial(9, 0.66)}
    winner, reason = pick_winner(results, ORDER)
    assert winner == "preferred" and reason.startswith("step 4")


def test_winner_with_one_model_says_so():
    assert pick_winner({"open": _trial(9, 0.66)}, ORDER) == ("open", "the only model tried")


def test_winner_refuses_a_model_with_no_place_in_the_preferred_order():
    with pytest.raises(ValueError, match="no preferred order"):
        pick_winner({"stranger": _trial(9, 0.66)}, ORDER)


TEN_PAIRS = tuple((f"Topic{i}#General", "POS") for i in range(10))
PASSED_TRIAL = Checkpoint1(ticks=9, marked=TEN_PAIRS, skipped=(), macro_f1=0.70)
FAILED_TRIAL = Checkpoint1(ticks=6, marked=TEN_PAIRS, skipped=(), macro_f1=0.62)  # 24 Sep, v4


def test_full_run_starts_after_a_pass_with_no_reason_needed():
    allowed, why = full_run_allowed(PASSED_TRIAL, "")
    assert allowed
    assert why == "checkpoint 1 passed"


def test_full_run_refuses_a_failed_checkpoint_without_a_written_reason():
    allowed, why = full_run_allowed(FAILED_TRIAL, "   ")
    assert not allowed
    assert "no override reason" in why


def test_full_run_starts_after_a_fail_only_with_a_reason_and_keeps_it():
    allowed, why = full_run_allowed(FAILED_TRIAL, "last adjusting round, decided 2026-09-24")
    assert allowed
    assert why.startswith("checkpoint 1 FAILED")
    assert "decided 2026-09-24" in why


def test_full_run_never_starts_without_any_trial_even_with_a_reason():
    allowed, why = full_run_allowed(None, "any reason at all")
    assert not allowed
    assert "no trial run" in why
