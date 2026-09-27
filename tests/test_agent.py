import json

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from juno.agent import build_agent, make_tools, run_juno, tool_results

TABLES = {
    "labels": "juno.restaurant.review_facts",
    "sentences": "juno.restaurant.sentences",
    "embeddings": "juno.restaurant.sentence_embeddings",
}
QUESTION = "How many review sentences mention the service negatively?"


class ScriptedModel(BaseChatModel):
    replies: list

    @property
    def _llm_type(self):
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=self.replies.pop(0))])


def final(number):
    return AIMessage(json.dumps({"answer_text": f"{number} sentences.", "number": number,
                                 "unit": "sentences", "ranked_categories": [], "cited_sentence_ids": []}))


def count_call():
    return AIMessage("", tool_calls=[{"name": "count_sentences", "id": "c1",
                                      "args": {"category": "Service#General", "sentiment": "NEG"}}])


def fake_sql(calls):
    def run_sql(sql, params):
        calls.append((sql, params))
        return [{"n": 480, "pct_of_all_sentences": 9.3, "pct_within_sentiment": 31.9}]
    return run_sql


def test_count_tool_builds_the_count_sql_with_parameters():
    calls = []
    count_sentences, _ = make_tools(fake_sql(calls), TABLES)
    out = json.loads(count_sentences.invoke({"category": "Service#General", "sentiment": "NEG"}))
    sql, params = calls[0]
    assert params == {"category": "Service#General", "sentiment": "NEG"}
    assert "FROM juno.restaurant.review_facts" in sql
    assert out[0]["n"] == 480


def test_find_examples_filters_by_label_and_keeps_10():
    calls = []
    _, find_examples = make_tools(fake_sql(calls), TABLES)
    find_examples.invoke({"question": "Why?", "category": "Service#General", "sentiment": "NEG"})
    sql, params = calls[0]
    assert params["category"] == "Service#General" and sql.endswith("LIMIT 10")


def test_tool_results_collects_count_numbers_and_example_ids():
    messages = [
        ToolMessage(json.dumps([{"n": 480, "pct_of_all_sentences": 9.3}]), tool_call_id="1", name="count_sentences"),
        ToolMessage(json.dumps([{"sentence_id": "abc", "text": "t"}]), tool_call_id="2", name="find_examples"),
    ]
    assert tool_results(messages) == ([480.0, 9.3], ["abc"])


def test_agent_calls_the_count_tool_then_answers_with_its_number():
    calls = []
    agent = build_agent(ScriptedModel(replies=[count_call(), final(480)]), fake_sql(calls), TABLES)
    result = run_juno(QUESTION, agent=agent)
    assert len(calls) == 1
    assert result["number"] == 480.0
    assert 480.0 in result["tool_numbers"]
    assert result["retried"] is False


def test_a_number_the_tool_never_returned_gets_one_retry():
    agent = build_agent(ScriptedModel(replies=[count_call(), final(500), final(480)]), fake_sql([]), TABLES)
    result = run_juno(QUESTION, agent=agent)
    assert result["retried"] is True
    assert result["number"] == 480.0


def test_after_one_retry_the_answer_is_kept_as_it_is():
    agent = build_agent(ScriptedModel(replies=[count_call(), final(500), final(510)]), fake_sql([]), TABLES)
    result = run_juno(QUESTION, agent=agent)
    assert result["retried"] is True
    assert result["number"] == 510.0
    assert result["number"] not in result["tool_numbers"]


def test_prompt_says_how_to_answer_a_comparison():
    from juno.agent import SYSTEM_PROMPT as prompt
    assert "put both in ranked_categories, the larger first" in prompt
