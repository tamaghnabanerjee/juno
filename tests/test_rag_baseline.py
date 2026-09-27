import json

import pytest

from juno.categories import CATEGORIES
from juno.rag_baseline import build_prompt, parse_response, run_rag_baseline

RETRIEVED = [
    {"sentence_id": "aaaa000000000001", "text": "The waiter ignored us for twenty minutes."},
    {"sentence_id": "aaaa000000000002", "text": "Staff were rude when we asked for water."},
]
QUESTION = "Why do guests complain about the service? Show examples."


def test_prompt_holds_the_question_the_retrieved_sentences_with_ids_and_all_categories():
    prompt = build_prompt(QUESTION, RETRIEVED)
    assert f"Question: {QUESTION}" in prompt
    assert "[aaaa000000000001] The waiter ignored us for twenty minutes." in prompt
    assert all(f"- {c}" in prompt for c in CATEGORIES)


def test_parse_reads_plain_json():
    reply = parse_response('{"answer_text": "Slow and rude staff.", "number": null, "unit": null, '
                           '"ranked_categories": [], "cited_sentence_ids": ["aaaa000000000001"]}')
    assert reply["answer_text"] == "Slow and rude staff."
    assert reply["cited_sentence_ids"] == ["aaaa000000000001"]


def test_parse_reads_json_wrapped_in_a_code_fence():
    reply = parse_response('```json\n{"answer_text": "About 12.", "number": 12, "unit": "sentences"}\n```')
    assert reply["number"] == 12
    assert reply["ranked_categories"] == []


def test_a_response_with_no_json_is_recorded_not_raised():
    reply = parse_response("I cannot answer that.")
    assert reply["parse_error"] == "no JSON object in the response"
    assert reply["answer_text"] is None and reply["ranked_categories"] == []


def test_malformed_json_is_recorded_not_raised():
    reply = parse_response('{"answer_text": "They said "great" food", "number": 3}')
    assert reply["parse_error"].startswith("invalid JSON")
    assert reply["number"] is None


def test_a_readable_response_has_no_parse_error():
    assert parse_response('{"answer_text": "ok"}')["parse_error"] is None


@pytest.mark.parametrize("raw, expected", [(62, 62.0), ("62", 62.0), ("about 60", None), (None, None), (True, None)])
def test_number_becomes_a_float_or_none(raw, expected):
    assert parse_response(json.dumps({"number": raw}))["number"] == expected


def test_run_searches_once_calls_the_llm_once_and_keeps_the_retrieved_sentence_ids():
    calls = {"search": 0, "llm": 0}

    def search(q):
        calls["search"] += 1
        return RETRIEVED

    def call_llm(prompt):
        calls["llm"] += 1
        assert "[aaaa000000000002]" in prompt
        return json.dumps({"answer_text": "Rude, slow staff.", "number": None, "unit": None,
                           "ranked_categories": ["Service#General"],
                           "cited_sentence_ids": ["aaaa000000000002"]})

    result = run_rag_baseline(QUESTION, search=search, call_llm=call_llm)
    assert calls == {"search": 1, "llm": 1}
    assert result["retrieved_sentence_ids"] == ["aaaa000000000001", "aaaa000000000002"]
    assert result["cited_sentence_ids"] == ["aaaa000000000002"]
    assert result["ranked_categories"] == ["Service#General"]
    assert result["seconds"] >= 0
    assert result["parse_error"] is None
    assert result["response_text"].startswith("{")


def test_prompt_says_how_to_answer_a_comparison():
    from juno.rag_baseline import PROMPT as prompt
    assert "put both in ranked_categories, the larger first" in prompt
