from __future__ import annotations

from collections.abc import Iterable

from juno.categories import CATEGORIES

_CATEGORY_LIST = "\n".join(f"- {c}" for c in CATEGORIES)

CATEGORY_GUIDE_V4 = """
Food#Quality          how the food tasted or was cooked: taste, freshness, texture, temperature,
                      seasoning. Praising several dishes is still Food#Quality, once.
Food#Style_Options    the offering rather than the taste: portion size, menu variety and choice,
                      specials, presentation, how creative or plain the dishes are.
                      "Huge portions" and "great menu" belong here, not in Food#Quality.
Food#Prices           the cost of food or of a meal
Drinks#Quality        how a drink tasted: beer, wine, coffee, cocktails. "Great beers" is here.
Drinks#Style_Options  only the range of drinks on offer: the wine list, the beer selection,
                      how many choices. NOT how a drink tasted.
Drinks#Prices         the cost of drinks
Service#General       staff, waiting time, attentiveness, order accuracy, bookings, delivery,
                      the bill
Ambience#General      the feel of the room: atmosphere, vibe, decor, music, noise, lighting,
                      cleanliness, comfort, how cosy or romantic it is
Location#General      only a judgement of where the place is: convenient, close to something,
                      hard to find, a nice view. Naming a street, city or neighbourhood as a
                      fact is not a judgement of the location.
Restaurant#Prices     the overall cost or value of the visit, when not about food or drinks
                      specifically
Restaurant#General    a verdict on the place as a whole (great place, recommend, will be back,
                      favourite, not worth it, best in town), and the practical side of the
                      place: parking, seating, tables, space, outdoor area, bathrooms
Restaurant#Miscellaneous  rare. The place judged for a particular use: good for a date, for
                      groups, for kids, for a quick lunch. Never for staff, the room or facilities.
"""

_RULES_V4 = """
Rules:
- Label every topic the sentence gives an opinion on, and only those.
- The topic is often implicit: "Delicious!" is about the food, "Will be back" is about the place,
  "So attentive" is about the service. Every sentence in this collection was chosen because it
  gives at least one opinion, so return [] only when you truly find none.
- Praise or criticism of the food, the drinks, the service or the room is that topic only. Do not
  add Restaurant#General because good food implies a good place. Add Restaurant#General only when
  the writer judges the place, the restaurant or the visit as a whole.
- "Great place", "nice spot" or "love this restaurant", with nothing said about the feel of the
  room, is Restaurant#General, not Ambience#General.
- sentiment is POS or NEG from the writer's point of view. NEU is rare: only when the writer says
  it was average, okay or mixed. A plain factual mention with no judgement gets no label.
- The same topic may appear twice with different sentiments if the writer is mixed about it.
- Return JSON only, no explanation.
"""

_EXAMPLES_V4 = """
Examples:

"The pasta was cold but our waiter was lovely."
[{"category": "Food#Quality", "sentiment": "NEG"}, {"category": "Service#General", "sentiment": "POS"}]

"Great little spot, we will definitely be back."
[{"category": "Restaurant#General", "sentiment": "POS"}]

"Lovely place, though the risotto was bland."
[{"category": "Restaurant#General", "sentiment": "POS"}, {"category": "Food#Quality", "sentiment": "NEG"}]
(an overall verdict and a specific criticism: label both)

"The lamb, the hummus and the flatbread were all superb."
[{"category": "Food#Quality", "sentiment": "POS"}]
(several dishes praised for taste: Food#Quality once; no verdict on the place was given, so no
Restaurant#General)

"Portions are enormous and the menu changes every week."
[{"category": "Food#Style_Options", "sentiment": "POS"}]
(portion size and menu variety, nothing about taste)

"Plenty of parking and a big outdoor terrace."
[{"category": "Restaurant#General", "sentiment": "POS"}]
(practical features of the place)

"The music was so loud that we gave up talking."
[{"category": "Ambience#General", "sentiment": "NEG"}]

"Perfect spot for a first date or a birthday group."
[{"category": "Restaurant#Miscellaneous", "sentiment": "POS"}]
(the place judged for a particular use)

"It is on Fifth Street, opposite the old cinema."
[]
(a fact about where it is, with no judgement)

"Thirty pounds a head felt steep for what it was."
[{"category": "Restaurant#Prices", "sentiment": "NEG"}]
"""

INSTRUCTIONS_V4 = (
    "You label restaurant review sentences with the topics they discuss and the sentiment of each.\n\n"
    "Categories (use these exact strings):\n"
    + _CATEGORY_LIST
    + "\n\nWhat each category covers:\n"
    + CATEGORY_GUIDE_V4
    + _RULES_V4
    + _EXAMPLES_V4
    + "\nSentence: "
)

VERSIONS: dict[str, str] = {"v4": INSTRUCTIONS_V4}
CURRENT_VERSION = "v4"
INSTRUCTIONS = VERSIONS[CURRENT_VERSION]

TAGS_SCHEMA = "array<struct<category:string,sentiment:string>>"

MIN_LEAK_CHECK_CHARS = 25


def get(version: str) -> str:
    if version not in VERSIONS:
        raise ValueError(f"unknown instructions version {version!r}. Kept: {', '.join(VERSIONS)}")
    return VERSIONS[version]


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


def leaked_sentences(instructions: str, sentences: Iterable[str]) -> list[str]:
    haystack = _normalise(instructions)
    return [
        s
        for s in sentences
        if len(s.strip()) >= MIN_LEAK_CHECK_CHARS and _normalise(s) in haystack
    ]
