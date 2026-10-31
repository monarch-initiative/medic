"""The merge-side polarity check anchors on the same string the ingest screen did (#63 review).

`original_disease_verbatim` is written by every ingester but was never read outside
`ingest/`, so `_polarity_flags` and `entailment_score` still searched for the canonical
name. Over the rebuilt DailyMed kb, 1,108 of 6,772 rows are locatable *only* via the
verbatim, which split the two halves of the polarity check apart.

The consequence is not cosmetic. #66 stopped dropping limitation-only rows at ingest on the
explicit understanding that this function "reaches the same conclusion and marks the claim
`negated_inversion`". That only holds if both halves search for the same string. When the
ingest located a disease in a negated limitation via its verbatim and the canonical name is
absent from the text, the row was kept at ingest *and* unflagged here — shipping a negated
statement as a positive indication, which is the exact failure #59 exists to prevent.
"""

from __future__ import annotations

from medic.merge.on_label_merge import _build_disease_provenance

# The label writes "MI"; the LLM returns "myocardial infarction". The restriction spells it
# out, so only the verbatim can locate the disease in either span.
ABBREVIATED = (
    "1 INDICATIONS AND USAGE PRODUCT is indicated for reducing the combined risk of death "
    "and nonfatal MI in patients with a previous MI. Limitations of Use : Not for use "
    "during onset of acute myocardial infarction."
)

# Only mention of the disease anywhere is inside a negated limitation, and only the
# verbatim form occurs. This is the row #66 relies on the merge to catch.
LIMITATION_ONLY = (
    "1 INDICATIONS AND USAGE PRODUCT is indicated for migraine. "
    "Limitations of Use PRODUCT is not indicated for CH."
)


def _assoc(text, disease, verbatim=None, parts=None):
    record = {"source": "DAILYMED", "indications_text": text, "set_id": "fd9f9458"}
    if parts is not None:
        record["indications_text_parts"] = parts
    ev = {"original_disease_label": disease, "snippet": text, "setid": "fd9f9458"}
    if verbatim is not None:
        ev["original_disease_verbatim"] = verbatim
    assoc = {"relationship_type": "INDICATION", "evidence": [ev]}
    return _build_disease_provenance(record, assoc, "MONDO:0005068", disease)


def test_a_limitation_only_row_is_flagged_when_only_the_verbatim_locates_it():
    """The #66 safety net. Without this the row ships as a positive indication."""
    _m, assertion = _assoc(LIMITATION_ONLY, "cluster headache", verbatim="CH")
    assert "negated_inversion" in (assertion.get("flags") or []) or assertion.get("negated")


def test_the_same_row_was_invisible_when_anchored_on_the_name_alone():
    """Pins the defect: with no verbatim recorded, nothing here can see it."""
    _m, assertion = _assoc(LIMITATION_ONLY, "cluster headache")
    assert not assertion.get("negated")
    assert "polarity_unverified" in (assertion.get("flags") or [])


def test_an_abbreviated_positive_indication_is_not_flagged_unverified():
    """1,108 rows were earning polarity_unverified although the ingest screen had reached a
    verdict on them. The verbatim locates the disease, so the check runs."""
    _m, assertion = _assoc(ABBREVIATED, "myocardial infarction", verbatim="MI")
    flags = assertion.get("flags") or []
    assert "polarity_unverified" not in flags
    assert not assertion.get("negated")


def test_a_hallucinated_verbatim_falls_back_to_the_name():
    """An unfindable quote must not make a row less evaluable than the name alone."""
    _m, assertion = _assoc(
        "PRODUCT is not indicated for the treatment of migraine.",
        "migraine", verbatim="sugar sickness")
    assert assertion.get("negated") or "negated_inversion" in (assertion.get("flags") or [])


def test_entailment_uses_the_verbatim_too():
    """`relationship_confidence` is the entailment score; anchoring it on a string the
    source never wrote scored real support as zero."""
    _m, assertion = _assoc(ABBREVIATED, "myocardial infarction", verbatim="MI")
    conf = assertion.get("confidence") or {}
    assert (conf.get("relationship") or 0) > 0.0


def test_a_row_with_no_verbatim_behaves_exactly_as_before():
    """Records merged from a kb built before #64 carry no verbatim."""
    _m, assertion = _assoc(
        "PRODUCT is indicated for the acute treatment of migraine.", "migraine")
    assert not assertion.get("negated")
    assert "polarity_unverified" not in (assertion.get("flags") or [])
