"""Filtered vector search: the evidence half of an answer.

Built in step 4, once the Vector Search index exists. Approach A calls this with k=20 and no
filters; the Juno agent calls it with a category/sentiment filter and at most 10 results, which is
the context limit the design doc commits to.
"""

from __future__ import annotations

MAX_EVIDENCE_SENTENCES = 10
BASELINE_K = 20


def find_examples(question: str, *, category: str | None = None, sentiment: str | None = None,
                  k: int = MAX_EVIDENCE_SENTENCES) -> list[dict]:
    """Return up to k sentences as {sentence_id, text, category, sentiment}."""
    raise NotImplementedError("step 4: implement against the Vector Search index")
