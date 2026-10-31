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


def test_the_literal_None_still_gets_through_which_is_108():
    """Pins current behaviour rather than the behaviour I expected.

    `looks_like_disease_name("None")` returns True, so a model answering with the bare word
    survives this filter and goes on to ground — against UMLS "None (qualifier value)",
    which is #108. Not introduced here and not fixed here; asserted so that closing #108
    has to come past this test rather than quietly changing what this path emits.
    """
    kept = disease_claims([Claim(target="None")])
    assert [c.target for c in kept] == ["None"]


def test_an_empty_extraction_filters_to_nothing_rather_than_raising():
    assert disease_claims([]) == []


def test_every_claim_field_the_path_reads_exists_on_claim():
    """Guard against the same drift again: these are the fields the EMA loop touches."""
    claim = Claim(target="x")
    for field in ("target", "target_verbatim"):
        assert hasattr(claim, field), field
