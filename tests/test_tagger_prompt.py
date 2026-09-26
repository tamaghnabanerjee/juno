import pytest

from juno import tagger_prompt
from juno.counting import CATEGORIES


def test_the_current_version_is_one_that_was_kept():
    assert tagger_prompt.CURRENT_VERSION in tagger_prompt.VERSIONS
    assert tagger_prompt.INSTRUCTIONS == tagger_prompt.get(tagger_prompt.CURRENT_VERSION)


def test_a_version_not_in_the_file_raises():
    with pytest.raises(ValueError, match="unknown instructions version"):
        tagger_prompt.get("v3")


@pytest.mark.parametrize("version", sorted(tagger_prompt.VERSIONS))
def test_every_version_names_all_12_categories_and_ends_ready_for_a_sentence(version):
    text = tagger_prompt.get(version)
    assert all(f"- {category}" in text for category in CATEGORIES)
    assert text.endswith("Sentence: ")


def test_a_dataset_sentence_inside_the_instructions_is_found():
    corpus = [
        "The pasta was cold but our waiter was lovely.",   # word for word in the prompt
        "  the PASTA was cold   but our waiter was lovely. ",  # same, different case and spacing
        "The lamb was overcooked and the bill was wrong.",  # not in the instructions
    ]
    assert tagger_prompt.leaked_sentences(tagger_prompt.INSTRUCTIONS, corpus) == corpus[:2]


def test_short_sentences_are_not_looked_for():
    # "Return JSON only" is in the instructions, but a sentence that short would match by accident.
    assert tagger_prompt.leaked_sentences(tagger_prompt.INSTRUCTIONS, ["Return JSON only"]) == []


def test_clean_instructions_report_nothing():
    corpus = ["The lamb was overcooked and the bill was wrong.", "Parking was impossible on a Friday."]
    assert tagger_prompt.leaked_sentences(tagger_prompt.INSTRUCTIONS, corpus) == []
