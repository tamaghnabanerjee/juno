import pytest

from eval.judge import GRADING_GUIDE, build_judge_prompt, parse_grade

CITED = [{"sentence_id": "aaaa000000000001", "text": "The waiter ignored us for twenty minutes."}]


def test_prompt_holds_the_question_the_answer_the_cited_sentences_and_the_guide():
    prompt = build_judge_prompt("Why do guests complain about the service?", "Slow staff.", CITED)
    assert "Question: Why do guests complain about the service?" in prompt
    assert "Slow staff." in prompt
    assert "[aaaa000000000001] The waiter ignored us for twenty minutes." in prompt
    assert GRADING_GUIDE in prompt


def test_missing_answer_and_no_citations_are_shown_as_such():
    prompt = build_judge_prompt("Why?", None, [])
    assert "(no answer)" in prompt and "(none)" in prompt


def test_parse_reads_a_grade_and_a_reason():
    assert parse_grade('{"grade": 4, "reason": "Supported but vague."}') == (4, "Supported but vague.")


def test_parse_reads_json_in_a_code_fence():
    assert parse_grade('```json\n{"grade": "5", "reason": "Specific."}\n```') == (5, "Specific.")


@pytest.mark.parametrize("text", ["no json here", '{"grade": 7}', '{"grade": "high"}', '{"reason": "x"}'])
def test_unreadable_or_out_of_range_grades_give_none(text):
    assert parse_grade(text) == (None, None)
