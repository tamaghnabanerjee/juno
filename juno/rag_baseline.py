from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from typing import Any

from juno.categories import CATEGORIES

PROMPT = """You answer questions about restaurant reviews.
Use only the review sentences below. They are the 20 sentences closest in meaning to the question.

Categories (use these exact strings when you name categories):
{categories}

For a question comparing two categories, put both in ranked_categories, the larger first.
Respond with JSON only, in this shape:
{{"answer_text": "<one or two sentences>",
  "number": <the number the question asks for, or null>,
  "unit": "sentences" or "percent" or null,
  "ranked_categories": [<category strings, largest first, when the question asks about categories>],
  "cited_sentence_ids": [<ids of the sentences you relied on>]}}

Question: {question}

Review sentences:
{retrieved_sentences}
"""


def build_prompt(question: str, retrieved_sentences: list[dict[str, str]]) -> str:
    return PROMPT.format(
        categories="\n".join(f"- {c}" for c in CATEGORIES),
        question=question,
        retrieved_sentences="\n".join(
            f"[{s['sentence_id']}] {s['text']}" for s in retrieved_sentences
        ),
    )


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def parse_response(text: str) -> dict[str, Any]:
    empty = {
        "answer_text": None,
        "number": None,
        "unit": None,
        "ranked_categories": [],
        "cited_sentence_ids": [],
    }
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if match is None:
        return {**empty, "parse_error": "no JSON object in the response"}
    try:
        reply = json.loads(match.group(0))
    except json.JSONDecodeError as error:
        return {**empty, "parse_error": f"invalid JSON: {error}"}
    if not isinstance(reply, dict):
        return {**empty, "parse_error": "the JSON is not an object"}
    return {
        "answer_text": reply.get("answer_text"),
        "number": _as_number(reply.get("number")),
        "unit": reply.get("unit"),
        "ranked_categories": list(reply.get("ranked_categories") or []),
        "cited_sentence_ids": list(reply.get("cited_sentence_ids") or []),
        "parse_error": None,
    }


def run_rag_baseline(
    question: str,
    *,
    search: Callable[[str], list[dict[str, str]]],
    call_llm: Callable[[str], str],
) -> dict[str, Any]:
    start = time.perf_counter()
    retrieved_sentences = search(question)
    response_text = call_llm(build_prompt(question, retrieved_sentences))
    result = parse_response(response_text)
    result["response_text"] = response_text
    result["retrieved_sentence_ids"] = [s["sentence_id"] for s in retrieved_sentences]
    result["seconds"] = round(time.perf_counter() - start, 2)
    return result
