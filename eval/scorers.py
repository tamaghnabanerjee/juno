from __future__ import annotations

from typing import Any


def within_10_percent(stated: float | None, true: float) -> float:
    if stated is None:
        return 0.0
    return 1.0 if abs(stated - true) <= 0.10 * true else 0.0


def score(question: dict[str, Any], answer: dict[str, Any]) -> dict[str, float]:
    qtype = question["qtype"]
    true_number = question["answer_number"]
    true_categories = list(question["answer_categories"] or [])
    true_ids = set(question["answer_sentence_ids"] or [])
    stated_categories = list(answer["ranked_categories"] or [])
    cited_ids = list(answer["cited_sentence_ids"] or [])

    if qtype == "count":
        return {"count_accuracy": within_10_percent(answer["number"], true_number)}
    if qtype == "share":
        return {"share_accuracy": within_10_percent(answer["number"], true_number)}
    if qtype == "share_within":
        return {"share_within_accuracy": within_10_percent(answer["number"], true_number)}
    if qtype == "compare":
        return {"compare_accuracy": 1.0 if stated_categories[:1] == true_categories[:1] else 0.0}
    if qtype == "topn":
        return {"top3_match": len(set(stated_categories[:3]) & set(true_categories[:3])) / 3}
    if qtype == "why":
        if not cited_ids:
            return {"citation_accuracy": 0.0}
        return {"citation_accuracy": sum(i in true_ids for i in cited_ids) / len(cited_ids)}
    raise ValueError(f"unknown question type: {qtype!r}")
