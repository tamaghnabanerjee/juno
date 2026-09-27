import pytest

from eval.scorers import score, within_10_percent


def question(qtype, number=None, categories=None, ids=None):
    return {"qtype": qtype, "answer_number": number, "answer_categories": categories or [],
            "answer_sentence_ids": ids or []}


def answer(number=None, categories=None, cited=None):
    return {"number": number, "ranked_categories": categories or [], "cited_sentence_ids": cited or []}


def test_count_within_10_percent_scores_1():
    assert score(question("count", 466), answer(480)) == {"count_accuracy": 1.0}


def test_count_more_than_10_percent_off_scores_0():
    assert score(question("count", 466), answer(520)) == {"count_accuracy": 0.0}


def test_no_number_scores_0():
    assert within_10_percent(None, 466) == 0.0


def test_share_uses_the_same_rule():
    assert score(question("share", 9.0), answer(9.3)) == {"share_accuracy": 1.0}
    assert score(question("share", 9.0), answer(7.0)) == {"share_accuracy": 0.0}


def test_compare_needs_the_winner_first():
    q = question("compare", 1083, ["Restaurant#General", "Restaurant#Prices"])
    assert score(q, answer(categories=["Restaurant#General"])) == {"compare_accuracy": 1.0}
    assert score(q, answer(categories=["Restaurant#Prices", "Restaurant#General"])) == {"compare_accuracy": 0.0}


def test_top3_match_counts_the_true_top_3_found_in_the_stated_top_3():
    q = question("topn", categories=["Food#Quality", "Service#General", "Restaurant#General", "Ambience#General"])
    stated = ["Food#Quality", "Ambience#General", "Service#General"]
    assert score(q, answer(categories=stated)) == {"top3_match": pytest.approx(2 / 3)}


def test_citation_accuracy_is_the_share_of_cited_ids_in_the_true_set():
    q = question("why", ids=["a", "b", "c"])
    assert score(q, answer(cited=["a", "b", "x", "y"])) == {"citation_accuracy": 0.5}


def test_citing_nothing_scores_0():
    assert score(question("why", ids=["a"]), answer(cited=[])) == {"citation_accuracy": 0.0}


def test_unknown_question_type_is_rejected():
    with pytest.raises(ValueError, match="unknown question type"):
        score(question("essay"), answer())
