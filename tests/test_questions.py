import pytest

from juno.counting import CATEGORIES, SENTIMENTS as ALL_SENTIMENTS
from juno.questions import (
    CATEGORY_LABELS,
    DEV_FRACTION,
    MIN_SUPPORT,
    TARGETS,
    WHY_MIN_SUPPORT,
    build,
    question_id,
)

# The real distribution, measured from juno.restaurant.human_labels.
SUPPORT = {
    ("Food#Quality", "POS"): 1889, ("Food#Quality", "NEG"): 510, ("Food#Quality", "NEU"): 59,
    ("Restaurant#General", "POS"): 1083, ("Restaurant#General", "NEG"): 296, ("Restaurant#General", "NEU"): 29,
    ("Service#General", "POS"): 799, ("Service#General", "NEG"): 466, ("Service#General", "NEU"): 8,
    ("Ambience#General", "POS"): 350, ("Ambience#General", "NEG"): 124, ("Ambience#General", "NEU"): 4,
    ("Food#Style_Options", "POS"): 229, ("Food#Style_Options", "NEG"): 62, ("Food#Style_Options", "NEU"): 1,
    ("Drinks#Quality", "POS"): 198, ("Drinks#Quality", "NEG"): 28, ("Drinks#Quality", "NEU"): 6,
    ("Food#Prices", "POS"): 75, ("Food#Prices", "NEG"): 44, ("Food#Prices", "NEU"): 1,
    ("Location#General", "POS"): 64, ("Location#General", "NEG"): 17, ("Location#General", "NEU"): 1,
    ("Restaurant#Prices", "POS"): 45, ("Restaurant#Prices", "NEG"): 36,
    ("Restaurant#Miscellaneous", "POS"): 42, ("Restaurant#Miscellaneous", "NEG"): 10,
    ("Drinks#Style_Options", "POS"): 35, ("Drinks#Style_Options", "NEG"): 3,
    ("Drinks#Prices", "POS"): 20, ("Drinks#Prices", "NEG"): 12, ("Drinks#Prices", "NEU"): 1,
}


@pytest.fixture(scope="module")
def questions():
    return build(SUPPORT)


def test_every_label_maps_to_a_real_category():
    assert set(CATEGORY_LABELS) == set(CATEGORIES)


def test_build_is_deterministic():
    assert build(SUPPORT) == build(SUPPORT)


def test_ids_are_unique_and_derived_from_the_text(questions):
    ids = [q["question_id"] for q in questions]
    assert len(ids) == len(set(ids))
    assert all(q["question_id"] == question_id(q["question"]) for q in questions)


def test_dict_ordering_does_not_change_the_result():
    shuffled = dict(reversed(list(SUPPORT.items())))
    assert build(shuffled) == build(SUPPORT)


def test_type_mix_matches_targets(questions):
    counts = {qtype: sum(1 for q in questions if q["qtype"] == qtype) for qtype in TARGETS}
    for qtype, target in TARGETS.items():
        assert counts[qtype] == target, f"{qtype}: {counts[qtype]} != {target}"
    assert len(questions) == sum(TARGETS.values())


def test_split_is_stratified_and_roughly_thirty_percent(questions):
    for qtype in TARGETS:
        of_type = [q for q in questions if q["qtype"] == qtype]
        dev = [q for q in of_type if q["split"] == "dev"]
        assert 0.25 <= len(dev) / len(of_type) <= 0.35, f"{qtype}: {len(dev)}/{len(of_type)}"
    dev_total = sum(1 for q in questions if q["split"] == "dev")
    assert abs(dev_total / len(questions) - DEV_FRACTION) < 0.05


def test_neutral_is_never_asked_about(questions):
    assert all(q["params"].get("sentiment") != "NEU" for q in questions)
    assert "NEU" in ALL_SENTIMENTS  # it exists in the data, it is just not asked about


def test_support_thresholds_are_respected(questions):
    for q in questions:
        params = q["params"]
        if "category" not in params:
            continue
        floor = WHY_MIN_SUPPORT if q["qtype"] == "why" else MIN_SUPPORT
        assert SUPPORT[(params["category"], params["sentiment"])] >= floor
        if "category_b" in params:
            assert SUPPORT[(params["category_b"], params["sentiment"])] >= floor


def test_questions_read_as_english_not_category_codes(questions):
    for q in questions:
        assert "#" not in q["question"], q["question"]
        assert q["question"].endswith(("?", "examples."))


def test_compare_never_pits_a_category_against_itself(questions):
    for q in (q for q in questions if q["qtype"] == "compare"):
        assert q["params"]["category"] != q["params"]["category_b"]
