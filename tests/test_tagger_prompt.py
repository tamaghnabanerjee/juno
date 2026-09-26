import pytest

from juno.categories import CATEGORIES
from tagger import prompt


def test_the_current_version_is_one_that_was_kept():
    assert prompt.CURRENT_VERSION in prompt.VERSIONS
    assert prompt.INSTRUCTIONS == prompt.get(prompt.CURRENT_VERSION)


def test_a_version_not_in_the_file_raises():
    with pytest.raises(ValueError, match="unknown instructions version"):
        prompt.get("v3")


@pytest.mark.parametrize("version", sorted(prompt.VERSIONS))
def test_every_version_names_all_12_categories_and_ends_ready_for_a_sentence(version):
    text = prompt.get(version)
    assert all(f"- {category}" in text for category in CATEGORIES)
    assert text.endswith("Sentence: ")


def test_a_dataset_sentence_inside_the_instructions_is_found():
    corpus = [
        "The pasta was cold but our waiter was lovely.",   # word for word in the prompt
        "  the PASTA was cold   but our waiter was lovely. ",  # same, different case and spacing
        "The lamb was overcooked and the bill was wrong.",  # not in the instructions
    ]
    assert prompt.leaked_sentences(prompt.INSTRUCTIONS, corpus) == corpus[:2]


def test_short_sentences_are_not_looked_for():
    # "Return JSON only" is in the instructions, but a sentence that short would match by accident.
    assert prompt.leaked_sentences(prompt.INSTRUCTIONS, ["Return JSON only"]) == []


def test_clean_instructions_report_nothing():
    corpus = ["The lamb was overcooked and the bill was wrong.", "Parking was impossible on a Friday."]
    assert prompt.leaked_sentences(prompt.INSTRUCTIONS, corpus) == []
