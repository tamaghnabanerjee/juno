"""Measure the tagger against the human labels.

Two things matter, and they are not the same:

* **Row agreement** — did the tagger put the right label on the right sentence? (precision/recall/F1)
* **Count error** — is the *number* it would report close to the truth? Juno answers with counts, so
  this is what bounds its accuracy. Misses and false positives can cancel out, leaving a good count
  on mediocre rows.

Pure functions over sets of `(sentence_id, category, sentiment)` triples, so they run in tests
without Spark. The rules they implement are set out in `docs/design.md`, sections 4 and 7.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

Triple = tuple[str, str, str]
Pair = tuple[str, str]

# Juno's target is "within 10% on at least 80% of count questions". The tagger has to clear that
# first, or the target is unreachable regardless of how good the agent is.
COUNT_TOLERANCE = 0.10
MIN_PAIRS_WITHIN_TOLERANCE = 0.80

# A judgement number with no recorded reason (design.md section 4.3). Kept on 2026-09-20.
MIN_MACRO_F1 = 0.60

# A question is only marked in a trial run if the humans found at least this many of its sentences
# there. Below it, one or two borderline sentences decide the mark. A judgement number, checked by
# simulation (design.md section 4.2 and Appendix B).
MIN_TRIAL_SUPPORT = 30


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


def within_tolerance(error: float) -> bool:
    """Does one count earn a tick?"""
    return abs(error) <= COUNT_TOLERANCE


@dataclass(frozen=True)
class Checkpoint1:
    """The verdict on one trial run, and what it rests on."""

    ticks: int
    marked: tuple[Pair, ...]
    skipped: tuple[Pair, ...]
    macro_f1: float

    @property
    def counts_ok(self) -> bool:
        """Condition 1. With nothing big enough to mark, there is no evidence, so it is not met."""
        return bool(self.marked) and self.ticks / len(self.marked) >= MIN_PAIRS_WITHIN_TOLERANCE

    @property
    def f1_ok(self) -> bool:
        """Condition 2."""
        return self.macro_f1 >= MIN_MACRO_F1

    @property
    def passed(self) -> bool:
        return self.counts_ok and self.f1_ok

    def lines(self) -> list[str]:
        share = self.ticks / len(self.marked) if self.marked else 0.0
        checks = [
            (
                self.counts_ok,
                (
                    f"count within {COUNT_TOLERANCE:.0%} on {self.ticks} of {len(self.marked)} "
                    f"marked questions = {share:.0%} (need {MIN_PAIRS_WITHIN_TOLERANCE:.0%}); "
                    f"{len(self.skipped)} skipped for having fewer than {MIN_TRIAL_SUPPORT} sentences"
                ),
            ),
            (self.f1_ok, f"average F1 {self.macro_f1:.2f} (need {MIN_MACRO_F1:.2f})"),
        ]
        return [f"{'ok  ' if ok else 'FAIL'} {text}" for ok, text in checks]


def checkpoint1(
    errors: Mapping[Pair, float],
    support: Mapping[Pair, int],
    scores: Mapping[str, Score],
    min_support: int = MIN_TRIAL_SUPPORT,
) -> Checkpoint1:
    """Is the tagger good enough to stop adjusting and label everything?

    `errors` maps (category, sentiment) to relative count error for the "how many" questions.
    `support` maps the same pairs to the human count inside the trial run. A pair is marked only if
    that count reaches `min_support`; the rest are reported and do not count towards the verdict.
    """
    marked = tuple(p for p in sorted(errors) if support.get(p, 0) >= min_support)
    skipped = tuple(p for p in sorted(errors) if support.get(p, 0) < min_support)
    ticks = sum(within_tolerance(errors[p]) for p in marked)
    return Checkpoint1(ticks=ticks, marked=marked, skipped=skipped, macro_f1=macro_f1(scores))


def pick_winner(
    results: Mapping[str, Checkpoint1], preferred_order: Sequence[str]
) -> tuple[str, str]:
    """Pick the better tagger model from trial runs made under identical conditions.

    The order was fixed before any result existed (design.md section 7):

    1. a model that meets both conditions beats one that does not;
    2. then the higher average F1, compared to two decimal places;
    3. then more ticks;
    4. then the preferred order.

    Returns the winning model and the step that decided it.
    """
    if not results:
        raise ValueError("no trial results to compare")
    missing = [m for m in results if m not in preferred_order]
    if missing:
        raise ValueError(f"no preferred order given for: {', '.join(sorted(missing))}")

    def key(model: str) -> tuple[bool, float, int, int]:
        r = results[model]
        return (r.passed, round(r.macro_f1, 2), r.ticks, -preferred_order.index(model))

    ranked = sorted(results, key=key, reverse=True)
    winner = ranked[0]
    if len(ranked) == 1:
        return winner, "the only model tried"

    first, second = key(winner), key(ranked[1])
    steps = (
        "step 1: it meets both conditions and the other does not",
        "step 2: higher average F1",
        "step 3: equal average F1 to two decimal places, more ticks",
        "step 4: equal on everything else, preferred order",
    )
    decided = next(i for i in range(4) if first[i] != second[i])
    return winner, steps[decided]
