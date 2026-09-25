"""The LLM-output disease-name guard is shared and does not eat real names.

`_looks_like_disease_name` lived in `ema/__main__.py`, so PMDA and India had no
second line of defence (#59). Moving it into the one parser both extractors already
pass through gives every source the guard — but its "a period means prose" rule
had to be fixed first: measured against the shipped knowledge base, that rule's only
effect was to delete four correct `H. pylori infection` rows.
"""

from __future__ import annotations

from medic.ingest.common import looks_like_disease_name


def test_abbreviated_genus_names_survive():
    assert looks_like_disease_name("H. pylori infection")
    assert looks_like_disease_name("M. avium complex infection")


def test_ordinary_disease_names_survive():
    for name in ("primary biliary cholangitis", "type 2 diabetes mellitus",
                 "Crohn's disease", "COPD"):
        assert looks_like_disease_name(name), name


def test_refusal_prose_is_rejected():
    for prose in ("These are contraindications, not indications for this product.",
                  "The text lists diagnostic procedures rather than diseases.",
                  "I cannot determine the diseases from this text.",
                  "No diseases are mentioned."):
        assert not looks_like_disease_name(prose), prose


def test_sentence_shaped_output_is_rejected():
    assert not looks_like_disease_name(
        "Patients with renal impairment may require a dose adjustment. See section 4.2.")


def test_overlong_strings_are_rejected():
    assert not looks_like_disease_name("x" * 121)


def test_empty_is_rejected():
    assert not looks_like_disease_name("")
    assert not looks_like_disease_name("   ")


def test_the_parser_applies_the_guard():
    """The guard is wired into the single chokepoint both extractors pass through, so
    DailyMed, EMA, PMDA and India inherit it without per-ingester wiring."""
    from medic.ingest.dailymed.__main__ import _parse_llm_disease_list

    out = _parse_llm_disease_list(
        "epilepsy|These are contraindications, not indications.|H. pylori infection")
    assert out == ["epilepsy", "H. pylori infection"]
