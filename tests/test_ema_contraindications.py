"""The EMA §4.3 contraindication path.

EMA has contributed no contraindications (#25), and the reason was not a missing feature:
the extraction is fully implemented behind ``--extract-contras``, which `build-all` does not
call, and the one line nobody could reach read ``d.name`` where the extractor returns a
``Claim`` whose field is ``target``. Running the recipe downloaded every EPAR PDF and then
raised ``AttributeError: 'Claim' object has no attribute 'name'``.

A flag nothing exercises is a flag that rots, so the filter is a named function with a test
on it rather than a comprehension inside a multi-hour run.
"""

from __future__ import annotations

import pytest

from medic.ingest.dailymed.__main__ import Claim
from medic.ingest.ema.__main__ import disease_claims


def test_a_claim_is_filtered_on_its_target_not_a_name_attribute():
    """The regression. `Claim` has `target`; it has never had `name`."""
    kept = disease_claims([Claim(target="angioedema", target_verbatim="angioedema")])
    assert [c.target for c in kept] == ["angioedema"]


def test_refusal_prose_is_dropped():
    """The extractor is tuned for indications and sometimes returns commentary instead of
    a condition; §4.3 text is where that shows up."""
    claims = [
        Claim(target="angioedema"),
        Claim(target="no contraindications are known"),
    ]
    kept = {c.target for c in disease_claims(claims)}
    assert kept == {"angioedema"}


def test_an_empty_extraction_filters_to_nothing_rather_than_raising():
    assert disease_claims([]) == []


def test_every_claim_field_the_path_reads_exists_on_claim():
    """Guard against the same drift again: these are the fields the EMA loop touches."""
    claim = Claim(target="x")
    for field in ("target", "target_verbatim"):
        assert hasattr(claim, field), field


# ---------------------------------------------------------------------------
# The literal `None` (#108, and the test failure behind #106)
# ---------------------------------------------------------------------------
def test_the_literal_None_is_rejected_now():
    """Was the opposite assertion until the cause was found.

    A model answering with the bare word got `None` grounded against UMLS:C0549184
    "None (qualifier value)" — the disease vocabulary really does hold that SNOMED
    qualifier. The row then broke every pandas-based reader of the grounding store, because
    `None` is in pandas' default `na_values`: `parse_sssom_table` read its `subject_label`
    as `NaN` and SSSOM JSON-schema validation failed the whole file on that one row.
    """
    assert disease_claims([Claim(target="None")]) == []


@pytest.mark.parametrize("token", ["None", "none", "NA", "n/a", "NULL", "NaN", "<NA>"])
def test_no_pandas_missing_value_token_survives_as_a_disease(token):
    """Whole-string and case-insensitive. Any of these reaching the store reintroduces the
    same unreadable row under a different spelling."""
    assert disease_claims([Claim(target=token)]) == []


@pytest.mark.parametrize("name", ["anaemia", "Nanjing encephalitis", "NAFLD"])
def test_a_real_name_that_merely_contains_such_a_token_is_kept(name):
    """The check is whole-string for a reason — 'NA' inside a word is not a missing value."""
    assert [c.target for c in disease_claims([Claim(target=name)])] == [name]
