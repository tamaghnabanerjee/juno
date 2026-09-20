"""The tagging prompt.

Kept in code rather than in the notebook so changes are reviewable and the "no dataset sentences in
the prompt" rule can be tested.

Round 1 (`PROMPT_V1`) over-tagged: the model volunteered secondary categories on almost every
sentence — Drinks#Style_Options +350%, Food#Style_Options +127% — while under-tagging
Restaurant#General by 31% because it preferred a specific category over the general one. Macro-F1
0.51 against a 0.60 gate, and only 20% of count pairs within 10%.

`PROMPT_V2` fixes that with a boundary for each category, an instruction to label only what the
sentence explicitly says, and worked examples of what *not* to tag.
"""

from __future__ import annotations

from juno.counting import CATEGORIES

# What each category covers, and where it stops. The overlaps that caused round 1's errors are
# called out explicitly.
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

_RULES = """
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

# Hand-written, deliberately not taken from the dataset: a real labelled sentence in the prompt would
# leak ground truth into the answering path.
_EXAMPLES = """
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

PROMPT_V2 = (
    "You label restaurant review sentences with the topics they discuss and the sentiment of each.\n\n"
    "Categories (use these exact strings):\n"
    + "\n".join(f"- {c}" for c in CATEGORIES)
    + "\n\nWhat each category covers:\n"
    + CATEGORY_GUIDE
    + _RULES
    + _EXAMPLES
    + "\nSentence: "
)

PROMPT = PROMPT_V2

# The shape the model must return, used to parse the response in SQL.
TAGS_SCHEMA = "array<struct<category:string,sentiment:string>>"
