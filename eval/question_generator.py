"""Generate the evaluation question set.

Questions are rendered from templates; their *answers* are computed later by SQL over the human
labels (see `eval/03_build_questions.py`). Nothing here invents an answer.

Everything is deterministic — ids hash the question text, and the dev/test split follows the id — so
re-running reproduces the identical set. That is what makes "the test split is frozen" an enforceable
property rather than a promise.
"""

from __future__ import annotations

import hashlib
from typing import Any

# Natural-language names for the 12 categories. Questions never show the raw category code:
# mapping "the service" back to Service#General is part of what both approaches must get right.
CATEGORY_LABELS: dict[str, str] = {
    "Ambience#General": "the atmosphere",
    "Drinks#Prices": "drink prices",
    "Drinks#Quality": "the drinks",
    "Drinks#Style_Options": "the drinks selection",
    "Food#Prices": "food prices",
    "Food#Quality": "the food",
    "Food#Style_Options": "the menu choices",
    "Location#General": "the location",
    "Restaurant#General": "the restaurant overall",
    "Restaurant#Miscellaneous": "other aspects of the restaurant",
    "Restaurant#Prices": "prices",
    "Service#General": "the service",
}

# Neutral has 110 label rows across 109 sentences, and three categories have none at all — too thin
# to ask about.
SENTIMENTS: tuple[str, ...] = ("POS", "NEG")

# Counting questions need enough support that "within 10%" is a real tolerance. With 3 sentences it
# would mean "exactly right". "Why" questions only need evidence to cite, so they allow less.
MIN_SUPPORT = 30
WHY_MIN_SUPPORT = 20

DEV_FRACTION = 0.30

TOP_N = (3, 5, 10)
TOP_N_OVERALL = (3, 5)

TEMPLATES: dict[str, str] = {
    "count": "How many review sentences mention {label} {adverb}?",
    "share": "What share of all review sentences mention {label} {adverb}?",
    "share_within": "Of all {adjective} comments, what share are about {label}?",
    "compare": "Are there more {adjective} comments about {label_a} or {label_b}?",
    "topn": "What are the top {n} topics in {adjective} comments?",
    "topn_overall": "What are the top {n} topics mentioned in the reviews?",
    "why": "Why do guests {verb} {label}? Show examples.",
}

TONE: dict[str, dict[str, str]] = {
    "POS": {"adverb": "positively", "adjective": "positive", "verb": "praise"},
    "NEG": {"adverb": "negatively", "adjective": "negative", "verb": "complain about"},
}

# How many of each type to keep. Candidates are trimmed by sorted id, so the choice is deterministic.
TARGETS: dict[str, int] = {
    "count": 18,
    "share": 18,
    "share_within": 18,
    "compare": 16,
    "topn": 8,
    "why": 20,
}


def question_id(text: str) -> str:
    """A stable id for a question: the first 12 hex characters of its SHA-256."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _question(qtype: str, template_id: str, text: str, params: dict[str, Any]) -> dict[str, Any]:
    return {
        "question_id": question_id(text),
        "question": text,
        "qtype": qtype,
        "template_id": template_id,
        "params": {k: str(v) for k, v in params.items()},
    }


def _candidates(support: dict[tuple[str, str], int]) -> dict[str, list[dict[str, Any]]]:
    """Every question the data can support, before trimming to the target mix."""
    eligible = sorted(
        (cat, sent)
        for (cat, sent), n in support.items()
        if sent in SENTIMENTS and cat in CATEGORY_LABELS and n >= MIN_SUPPORT
    )
    why_eligible = sorted(
        (cat, sent)
        for (cat, sent), n in support.items()
        if sent in SENTIMENTS and cat in CATEGORY_LABELS and n >= WHY_MIN_SUPPORT
    )

    out: dict[str, list[dict[str, Any]]] = {q: [] for q in TARGETS}

    for cat, sent in eligible:
        label, tone = CATEGORY_LABELS[cat], TONE[sent]
        params = {"category": cat, "sentiment": sent}
        out["count"].append(
            _question("count", "count", TEMPLATES["count"].format(label=label, adverb=tone["adverb"]), params)
        )
        out["share"].append(
            _question("share", "share", TEMPLATES["share"].format(label=label, adverb=tone["adverb"]), params)
        )
        out["share_within"].append(
            _question(
                "share_within",
                "share_within",
                TEMPLATES["share_within"].format(adjective=tone["adjective"], label=label),
                params,
            )
        )

    for sent in SENTIMENTS:
        cats = [c for c, s in eligible if s == sent]
        for i, cat_a in enumerate(cats):
            for cat_b in cats[i + 1 :]:
                out["compare"].append(
                    _question(
                        "compare",
                        "compare",
                        TEMPLATES["compare"].format(
                            adjective=TONE[sent]["adjective"],
                            label_a=CATEGORY_LABELS[cat_a],
                            label_b=CATEGORY_LABELS[cat_b],
                        ),
                        {"category": cat_a, "category_b": cat_b, "sentiment": sent},
                    )
                )

    for sent in SENTIMENTS:
        for n in TOP_N:
            out["topn"].append(
                _question(
                    "topn",
                    "topn",
                    TEMPLATES["topn"].format(n=n, adjective=TONE[sent]["adjective"]),
                    {"sentiment": sent, "n": n},
                )
            )
    for n in TOP_N_OVERALL:
        out["topn"].append(
            _question("topn", "topn_overall", TEMPLATES["topn_overall"].format(n=n), {"n": n})
        )

    for cat, sent in why_eligible:
        out["why"].append(
            _question(
                "why",
                "why",
                TEMPLATES["why"].format(verb=TONE[sent]["verb"], label=CATEGORY_LABELS[cat]),
                {"category": cat, "sentiment": sent},
            )
        )

    return out


def build(support: dict[tuple[str, str], int]) -> list[dict[str, Any]]:
    """Build the frozen question set.

    `support` maps (category, sentiment) to the number of distinct sentences carrying that label,
    which comes from SQL over `human_labels`.

    Returns one dict per question with its id, text, type, template, params and dev/test split.
    Answers are attached later, in the notebook, from SQL.
    """
    questions: list[dict[str, Any]] = []
    for qtype, candidates in _candidates(support).items():
        # Sort by id, not by insertion order, so the selection does not depend on dict ordering.
        chosen = sorted(candidates, key=lambda q: q["question_id"])[: TARGETS[qtype]]
        # Stratified split: the same 30% of each type goes to dev, chosen the same way every run.
        dev_count = round(DEV_FRACTION * len(chosen))
        for i, question in enumerate(chosen):
            questions.append({**question, "split": "dev" if i < dev_count else "test"})
    return sorted(questions, key=lambda q: (q["qtype"], q["question_id"]))
