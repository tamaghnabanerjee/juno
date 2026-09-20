import pytest

from juno import tagging
from juno.counting import CATEGORIES


def test_the_current_version_is_one_that_was_kept():
    assert tagging.CURRENT_VERSION in tagging.VERSIONS
    assert tagging.INSTRUCTIONS == tagging.get(tagging.CURRENT_VERSION)


def test_versions_are_distinct_texts():
    texts = list(tagging.VERSIONS.values())
    assert len(set(texts)) == len(texts)


def test_v2_was_lost_and_asking_for_it_says_so():
    with pytest.raises(ValueError, match="unknown instructions version"):
        tagging.get("v2")


@pytest.mark.parametrize("version", sorted(tagging.VERSIONS))
def test_every_version_names_all_12_categories_and_ends_ready_for_a_sentence(version):
    text = tagging.get(version)
    assert all(f"- {category}" in text for category in CATEGORIES)
    assert text.endswith("Sentence: ")


def test_a_dataset_sentence_inside_the_instructions_is_found():
    corpus = [
        "The pasta was cold but our waiter was lovely.",   # word for word in every version
        "  the PASTA was cold   but our waiter was lovely. ",  # same, different case and spacing
        "The lamb was overcooked and the bill was wrong.",  # not in the instructions
    ]
    assert tagging.leaked_sentences(tagging.INSTRUCTIONS, corpus) == corpus[:2]


def test_short_sentences_are_not_looked_for():
    # "Return JSON only" is in the instructions, but a sentence that short would match by accident.
    assert tagging.leaked_sentences(tagging.INSTRUCTIONS, ["Return JSON only"]) == []


def test_clean_instructions_report_nothing():
    corpus = ["The lamb was overcooked and the bill was wrong.", "Parking was impossible on a Friday."]
    assert tagging.leaked_sentences(tagging.INSTRUCTIONS, corpus) == []
