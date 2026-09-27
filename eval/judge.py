from __future__ import annotations

import json
import re

GRADING_GUIDE = """5 - Answers the "why" directly with specific reasons, every reason is supported by the
    quoted sentences, and nothing is invented.
4 - Answers the "why" with reasons supported by the sentences, but is vaguer or misses an obvious
    reason the sentences show.
3 - Partly answers: some reasons are supported, some are generic or only loosely supported.
2 - Mostly generic or mostly unsupported by the sentences.
1 - Does not answer the question, contradicts the sentences, or cites no sentences."""

JUDGE_PROMPT = """You grade answers to questions about restaurant reviews.

Question: {question}

Answer to grade:
{answer_text}

Review sentences the answer cites:
{cited_sentences}

Grade the answer from 1 to 5 with this guide:
{guide}

Respond with JSON only: {{"grade": <1 to 5>, "reason": "<one sentence>"}}
"""


def build_judge_prompt(question: str, answer_text: str | None, cited: list[dict[str, str]]) -> str:
    return JUDGE_PROMPT.format(
        question=question,
        answer_text=answer_text or "(no answer)",
        cited_sentences="\n".join(f"[{c['sentence_id']}] {c['text']}" for c in cited) or "(none)",
        guide=GRADING_GUIDE,
    )


def parse_grade(text: str) -> tuple[int | None, str | None]:
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if match is None:
        return None, None
    try:
        reply = json.loads(match.group(0))
        grade = int(reply.get("grade"))
    except (json.JSONDecodeError, TypeError, ValueError):
        return None, None
    if grade < 1 or grade > 5:
        return None, None
    return grade, reply.get("reason")
