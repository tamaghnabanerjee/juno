"""The tagger's instructions, one named version per attempt.

Kept in code rather than in the notebook so that every change is reviewable, and so that the rule
"no dataset sentences in the instructions" can be checked.

What each version changed, and what happened (all on 500 sentences, 2026-09-20):

* `v1` — a list of the 12 categories, five rules and two examples. It over-tagged: the model
  volunteered secondary categories on almost every sentence (Drinks#Style_Options +350%,
  Food#Style_Options +127%) and under-tagged Restaurant#General by 31%, because it preferred a
  specific category to the general one. Average F1 0.51.
* `v2` — added a boundary for each category and the line "most sentences cover one topic". It
  overcorrected into under-tagging (Restaurant#General NEG -46%, Service#General POS -23%). Average
  F1 0.53. **Its text was overwritten when v3 was written and cannot be recovered**, so there is no
  `INSTRUCTIONS_V2` below.
* `v3` — keeps the boundaries, and asks for every topic a sentence explicitly evaluates, so that a
  sentence giving an overall verdict *and* a specific criticism gets both labels. Strong on large
  categories (Food#Quality 0.83, Service#General 0.84), weak on rare ones
  (Restaurant#Miscellaneous 0.09, Location#General 0.27). Average F1 0.59.

`v1` was recovered from the copy the tagging notebook used to carry. The examples in every version
are written by hand: a real labelled sentence would leak ground truth into the answering path.
"""

from __future__ import annotations

from collections.abc import Iterable

from juno.counting import CATEGORIES

_CATEGORY_LIST = "\n".join(f"- {c}" for c in CATEGORIES)

INSTRUCTIONS_V1 = (
    "You label restaurant review sentences for topic and sentiment.\n\n"
    "Categories (use these exact strings):\n"
    + _CATEGORY_LIST
    + """

Rules:
- One entry per topic the sentence actually discusses. A sentence may cover several.
- sentiment is POS, NEG or NEU, from the writer's point of view.
- The same topic may appear twice with different sentiments if the writer is mixed about it.
- If the sentence discusses none of the categories, return [].
- Return JSON only, no explanation.

Example: "The pasta was cold but our waiter was lovely."
[{"category": "Food#Quality", "sentiment": "NEG"}, {"category": "Service#General", "sentiment": "POS"}]

Example: "We parked round the back."
[]

Sentence: """
)

# What each category covers, and where it stops. The overlaps that caused v1's errors are called out
# explicitly.
CATEGORY_GUIDE = """
Food#Quality          taste, freshness, temperature, cooking, portion quality
Food#Style_Options    the range or style of dishes offered: variety, menu breadth, customisation.
                      NOT how the food tasted - that is Food#Quality
Food#Prices           the cost of food specifically
Drinks#Quality        taste or quality of drinks, coffee, cocktails, wine
Drinks#Style_Options  the range of drinks offered. NOT how a drink tasted
Drinks#Prices         the cost of drinks specifically
Service#General       staff, waiting time, attentiveness, order accuracy, booking handling
Ambience#General      atmosphere, decor, music, noise, lighting, seating comfort
Location#General      where the place is: neighbourhood, transport, parking, convenience of getting there
Restaurant#Prices     overall cost or value of the visit, when not specific to food or drinks
Restaurant#General    the place as a whole: an overall verdict, recommendation, or return intent
Restaurant#Miscellaneous  anything else concrete: opening hours, cleanliness, payment, facilities
"""

_RULES_V3 = """
Rules:
- Label every topic the sentence explicitly evaluates, and only those. Do not infer topics.
- A sentence can carry several: an overall verdict AND a specific topic both count.
- An overall verdict about the place ("great spot", "would come back", "not worth it") is
  Restaurant#General. Include it even when the sentence also praises or criticises something specific.
- Restaurant#Miscellaneous is rare. Use it only for opening hours, cleanliness, payment or facilities.
- Location#General only when the sentence evaluates where the place is or how easy it is to reach.
- sentiment is POS, NEG or NEU from the writer's point of view.
- The same topic may appear twice with different sentiments if the writer is mixed about it.
- If none of the categories is explicitly discussed, return [].
- Return JSON only, no explanation.
"""

_EXAMPLES_V3 = """
Examples:

"The pasta was cold but our waiter was lovely."
[{"category": "Food#Quality", "sentiment": "NEG"}, {"category": "Service#General", "sentiment": "POS"}]

"Great little spot, we will definitely be back."
[{"category": "Restaurant#General", "sentiment": "POS"}]

"Lovely place, though the risotto was bland."
[{"category": "Restaurant#General", "sentiment": "POS"}, {"category": "Food#Quality", "sentiment": "NEG"}]
(an overall verdict and a specific criticism: label both)

"The sushi was fresh."
[{"category": "Food#Quality", "sentiment": "POS"}]
(not Food#Style_Options - nothing is said about the range of dishes)

"They have twelve kinds of dumpling."
[{"category": "Food#Style_Options", "sentiment": "POS"}]
(not Food#Quality - nothing is said about how they taste)

"We parked round the back and walked in."
[]
(no topic is being evaluated)

"Thirty pounds a head felt steep for what it was."
[{"category": "Restaurant#Prices", "sentiment": "NEG"}]
"""

INSTRUCTIONS_V3 = (
    "You label restaurant review sentences with the topics they discuss and the sentiment of each.\n\n"
    "Categories (use these exact strings):\n"
    + _CATEGORY_LIST
    + "\n\nWhat each category covers:\n"
    + CATEGORY_GUIDE
    + _RULES_V3
    + _EXAMPLES_V3
    + "\nSentence: "
)

VERSIONS: dict[str, str] = {"v1": INSTRUCTIONS_V1, "v3": INSTRUCTIONS_V3}
CURRENT_VERSION = "v3"
INSTRUCTIONS = VERSIONS[CURRENT_VERSION]

# The shape the model must return, used to parse the response in SQL.
TAGS_SCHEMA = "array<struct<category:string,sentiment:string>>"

# A dataset sentence shorter than this is not looked for inside the instructions: "Yum." or "OK"
# would match by accident. A judgement number, not derived from anything.
MIN_LEAK_CHECK_CHARS = 25


def get(version: str) -> str:
    """The instructions for one version. Raises if the version was never kept."""
    if version not in VERSIONS:
        raise ValueError(f"unknown instructions version {version!r}. Kept: {', '.join(VERSIONS)}")
    return VERSIONS[version]


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


def leaked_sentences(instructions: str, sentences: Iterable[str]) -> list[str]:
    """Dataset sentences that appear word for word inside the instructions.

    The notebook calls this with every sentence of the corpus before it labels anything, and stops
    if the list is not empty. Case and spacing are ignored.
    """
    haystack = _normalise(instructions)
    return [
        s
        for s in sentences
        if len(s.strip()) >= MIN_LEAK_CHECK_CHARS and _normalise(s) in haystack
    ]
