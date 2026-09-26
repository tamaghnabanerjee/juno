"""Approach A: the standard RAG chatbot Juno has to beat.

Retrieve the 20 closest sentences, hand them to the LLM, return whatever it says. No SQL, no
checking. Built in step 5, before the agent, so there is always a comparison to measure against.
"""

from __future__ import annotations


def answer(question: str) -> dict:
    """Return {answer, sentence_ids, latency_s} for one question."""
    raise NotImplementedError("step 5: retrieve top 20, then answer from them")
