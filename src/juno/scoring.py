"""Measure the tagger against the human labels.

Two things matter, and they are not the same:

* **Row agreement** — did the tagger put the right label on the right sentence? (precision/recall/F1)
* **Count error** — is the *number* it would report close to the truth? Juno answers with counts, so
  this is what bounds its accuracy. Misses and false positives can cancel out, leaving a good count
  on mediocre rows.

Pure functions over sets of `(sentence_id, category, sentiment)` triples, so they run in tests
without Spark.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

Triple = tuple[str, str, str]

# Juno's target is "within 10% on at least 80% of count questions". The tagger has to clear that
# first, or the target is unreachable regardless of how good the agent is.
COUNT_TOLERANCE = 0.10
MIN_PAIRS_WITHIN_TOLERANCE = 0.80
MIN_MACRO_F1 = 0.60


@dataclass(frozen=True)
class Score:
    tp: int
    fp: int
    fn: int

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


def score(predicted: Iterable[Triple], actual: Iterable[Triple]) -> Score:
    """Row-level agreement between two sets of labels."""
    pred, act = set(predicted), set(actual)
    return Score(tp=len(pred & act), fp=len(pred - act), fn=len(act - pred))


def by_category(predicted: Iterable[Triple], actual: Iterable[Triple]) -> dict[str, Score]:
    """One score per category, over every category either side used."""
    pred, act = set(predicted), set(actual)
    categories = {c for _, c, _ in pred} | {c for _, c, _ in act}
    return {
        category: score(
            {t for t in pred if t[1] == category},
            {t for t in act if t[1] == category},
        )
        for category in sorted(categories)
    }


def macro_f1(scores: Mapping[str, Score]) -> float:
    """Unweighted mean F1, so a small category counts as much as a large one."""
    return sum(s.f1 for s in scores.values()) / len(scores) if scores else 0.0


def relative_error(llm_n: int, human_n: int) -> float:
    """Signed error in the count the tagger would report. Positive means over-counting."""
    if human_n == 0:
        return 0.0 if llm_n == 0 else float("inf")
    return (llm_n - human_n) / human_n


def passes_gate(
    errors: Mapping[tuple[str, str], float],
    scores: Mapping[str, Score],
) -> tuple[bool, list[str]]:
    """Is the tagger good enough to build on?

    `errors` maps (category, sentiment) to relative count error, for the pairs the evaluation
    actually asks about. Returns the verdict and a line per check.
    """
    within = [e for e in errors.values() if abs(e) <= COUNT_TOLERANCE]
    share_within = len(within) / len(errors) if errors else 0.0
    mf1 = macro_f1(scores)

    checks = [
        (
            share_within >= MIN_PAIRS_WITHIN_TOLERANCE,
            f"count error within {COUNT_TOLERANCE:.0%} on {share_within:.0%} of pairs "
            f"(need {MIN_PAIRS_WITHIN_TOLERANCE:.0%})",
        ),
        (mf1 >= MIN_MACRO_F1, f"macro-F1 {mf1:.2f} (need {MIN_MACRO_F1:.2f})"),
    ]
    return all(ok for ok, _ in checks), [f"{'ok  ' if ok else 'FAIL'} {text}" for ok, text in checks]
