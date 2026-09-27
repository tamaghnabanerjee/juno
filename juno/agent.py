from __future__ import annotations

import json
import time
from typing import Any, Literal

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from juno.categories import CATEGORIES, SENTIMENTS
from juno.rag_baseline import parse_response
from juno.retrieval import build_search_sql
from juno.sql_count_tool import build_count_sql

Category = Literal[CATEGORIES]
Sentiment = Literal[SENTIMENTS]

SYSTEM_PROMPT = """You answer questions about restaurant reviews. You have two tools.

count_sentences counts review sentences over the whole collection. Use it for every number:
how many, what share, which of two is bigger, and the top categories. Never estimate a number
yourself. State the number exactly as the tool returned it.
- "What share of all review sentences ..." is pct_of_all_sentences.
- "Of all positive (or negative) comments, what share ..." is pct_within_sentiment.
- For the top categories, call it with rank_by_category=true.

find_examples returns up to 10 review sentences carrying one category and one sentiment. Use it
for "why" questions, and cite the ids of the sentences you rely on.

Categories: {categories}
Sentiments: POS (positive), NEG (negative), NEU (neutral).

For a question comparing two categories, put both in ranked_categories, the larger first.
When you have the answer, respond with JSON only, in this shape:
{{"answer_text": "<one or two sentences>",
  "number": <the number the question asks for, or null>,
  "unit": "sentences" or "percent" or null,
  "ranked_categories": [<category strings, largest first, when the question asks about categories>],
  "cited_sentence_ids": [<ids of the example sentences you relied on>]}}
""".format(categories=", ".join(CATEGORIES))

RETRY_MESSAGE = (
    "The number you stated, {stated}, is not one the count tool returned. The tool returned: "
    "{returned}. Respond again with the same JSON shape, stating one of the tool's numbers exactly."
)


def make_tools(run_sql: Any, tables: dict[str, str]) -> list[Any]:
    @tool
    def count_sentences(
        category: Category | None = None,
        sentiment: Sentiment | None = None,
        rank_by_category: bool = False,
        top_n: int | None = None,
    ) -> str:
        """Count review sentences carrying a category and/or a sentiment, over all sentences.

        Returns n, pct_of_all_sentences and, when a sentiment is given, pct_within_sentiment.
        With rank_by_category=true, returns one row per category, largest first, limited to top_n.
        """
        sql, params = build_count_sql(
            tables["labels"],
            sentences_table=tables["sentences"],
            category=category,
            sentiment=sentiment,
            group_by="category" if rank_by_category else None,
            top_n=top_n,
        )
        return json.dumps(run_sql(sql, params), default=float)

    @tool
    def find_examples(question: str, category: Category, sentiment: Sentiment) -> str:
        """Return up to 10 review sentences carrying the category and sentiment, closest to the question."""
        sql, params = build_search_sql(
            question,
            embeddings_table=tables["embeddings"],
            sentences_table=tables["sentences"],
            labels_table=tables["labels"],
            k=10,
            category=category,
            sentiment=sentiment,
        )
        return json.dumps(run_sql(sql, params), default=float)

    return [count_sentences, find_examples]


def build_agent(llm: Any, run_sql: Any, tables: dict[str, str]) -> Any:
    return create_react_agent(llm, make_tools(run_sql, tables), prompt=SYSTEM_PROMPT)


def tool_results(messages: list[Any]) -> tuple[list[float], list[str]]:
    numbers: list[float] = []
    example_ids: list[str] = []
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        try:
            rows = json.loads(message.content)
        except (TypeError, json.JSONDecodeError):
            continue
        for row in rows if isinstance(rows, list) else []:
            if message.name == "count_sentences":
                numbers += [float(row[k]) for k in ("n", "pct_of_all_sentences", "pct_within_sentiment")
                            if row.get(k) is not None]
            elif message.name == "find_examples" and "sentence_id" in row:
                example_ids.append(row["sentence_id"])
    return numbers, example_ids


def run_juno(question: str, *, agent: Any, recursion_limit: int = 12) -> dict[str, Any]:
    start = time.perf_counter()
    config = {"recursion_limit": recursion_limit}
    messages = agent.invoke({"messages": [HumanMessage(question)]}, config)["messages"]
    result = parse_response(messages[-1].content)
    numbers, example_ids = tool_results(messages)
    retried = False
    if result["number"] is not None and numbers and result["number"] not in numbers:
        retried = True
        retry = HumanMessage(RETRY_MESSAGE.format(stated=result["number"], returned=numbers))
        messages = agent.invoke({"messages": [*messages, retry]}, config)["messages"]
        result = parse_response(messages[-1].content)
        numbers, example_ids = tool_results(messages)
    result["response_text"] = messages[-1].content
    result["tool_numbers"] = numbers
    result["retrieved_sentence_ids"] = example_ids
    result["retried"] = retried
    result["seconds"] = round(time.perf_counter() - start, 2)
    return result
