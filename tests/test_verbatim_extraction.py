"""The extractor returns the verbatim source substring, not only a canonical name (#64).

The prompt asks the LLM to canonicalise ("type 2 diabetes mellitus" not "diabetes"), and
every downstream check then searches the source for that canonicalised string. When it is
not there, `assertion_negated` returns `total == 0`, polarity is not evaluable, and the
destructive screen passes the row untouched — 1,414 of 11,696 shipped INDICATIONs (12%).
`provenance_build._extraction_step` computes `char_start`/`char_end` with the same literal
`find`, so those rows get no offsets either.

Asking for the substring alongside the name removes the lexical dependence: the verbatim
form is in the text by construction, so it can always be located and scoped.
"""

from __future__ import annotations

from medic.ingest.dailymed.__main__ import Extracted, _parse_llm_disease_list
from medic.validation.extraction_fidelity import screen_indications

NEG = "XYZ is not indicated for the treatment of patients with type 2 diabetes."


# ---------------------------------------------------------------------------
# Parsing the new contract
# ---------------------------------------------------------------------------
def test_a_name_and_verbatim_pair_is_parsed():
    out = _parse_llm_disease_list("type 2 diabetes mellitus :: type 2 diabetes")
    assert out == [Extracted("type 2 diabetes mellitus", "type 2 diabetes")]


def test_several_pairs_are_parsed():
    out = _parse_llm_disease_list(
        "epilepsy :: epilepsy|myocardial infarction :: MI")
    assert [e.name for e in out] == ["epilepsy", "myocardial infarction"]
    assert [e.verbatim for e in out] == ["epilepsy", "MI"]


def test_a_bare_name_still_parses_with_no_verbatim():
    """Cached answers from the old prompt, and a model that ignores the format."""
    out = _parse_llm_disease_list("epilepsy|asthma")
    assert [e.name for e in out] == ["epilepsy", "asthma"]
    assert [e.verbatim for e in out] == ["", ""]


def test_none_is_still_empty():
    assert _parse_llm_disease_list("None") == []
    assert _parse_llm_disease_list("") == []


def test_the_disease_name_guard_still_applies_to_the_name_half():
    out = _parse_llm_disease_list(
        "epilepsy :: epilepsy|These are contraindications, not indications. :: x")
    assert [e.name for e in out] == ["epilepsy"]


def test_an_empty_verbatim_half_is_tolerated():
    out = _parse_llm_disease_list("epilepsy ::")
    assert out == [Extracted("epilepsy", "")]


def test_a_verbatim_longer_than_the_name_limit_is_kept():
    """The verbatim is quoted source text, not a disease name, so the 200-char name cap
    must not apply to it."""
    long_quote = "patients with " + ("very " * 50) + "severe epilepsy"
    out = _parse_llm_disease_list(f"epilepsy :: {long_quote}")
    assert out[0].name == "epilepsy"
    assert out[0].verbatim == long_quote


# ---------------------------------------------------------------------------
# What it buys: the screen can finally locate the disease
# ---------------------------------------------------------------------------
def test_a_canonicalised_name_with_its_verbatim_is_now_evaluable():
    """The headline #59 case. The canonical name is absent from the source, so the screen
    could not judge polarity; the verbatim form is present and negated."""
    result = screen_indications(
        ["type 2 diabetes mellitus"], NEG,
        verbatims={"type 2 diabetes mellitus": "type 2 diabetes"})
    assert result.kept == []
    assert [d["disease"] for d in result.dropped] == ["type 2 diabetes mellitus"]
    assert result.unlocatable == []


def test_without_a_verbatim_it_remains_unevaluable():
    """Pins the pre-#64 behaviour, so the improvement is visibly an improvement."""
    result = screen_indications(["type 2 diabetes mellitus"], NEG)
    assert result.kept == ["type 2 diabetes mellitus"]
    assert result.unlocatable == ["type 2 diabetes mellitus"]


def test_a_verbatim_that_is_positively_stated_is_kept():
    text = "XYZ is indicated for the treatment of patients with type 2 diabetes."
    result = screen_indications(
        ["type 2 diabetes mellitus"], text,
        verbatims={"type 2 diabetes mellitus": "type 2 diabetes"})
    assert result.kept == ["type 2 diabetes mellitus"]
    assert result.unlocatable == []


def test_a_verbatim_the_source_does_not_contain_falls_back_to_the_name():
    """A model can hallucinate the quote too. An unfindable verbatim must not make the
    row *less* evaluable than it was."""
    result = screen_indications(
        ["type 2 diabetes mellitus"], NEG,
        verbatims={"type 2 diabetes mellitus": "sugar sickness"})
    assert result.kept == ["type 2 diabetes mellitus"]
    assert result.unlocatable == ["type 2 diabetes mellitus"]


def test_the_abbreviation_case_from_66_is_located_by_its_verbatim():
    """aspirin/omeprazole: the claim span says "MI". With the verbatim recorded, the
    disease is locatable in the claim span and the limitation never governs it."""
    text = (
        "1 INDICATIONS AND USAGE ASPIRIN AND OMEPRAZOLE is indicated for reducing the "
        "combined risk of death and nonfatal MI in patients with a previous MI. "
        "Limitations of Use : Not for use during onset of acute myocardial infarction."
    )
    result = screen_indications(
        ["myocardial infarction"], text,
        verbatims={"myocardial infarction": "MI"})
    assert result.kept == ["myocardial infarction"]
    assert result.limitation_only == []
    assert result.unlocatable == []
