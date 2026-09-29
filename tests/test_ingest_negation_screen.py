"""The ingest-time negation screen is span-scoped (issue #59).

`screen_indications` is the only *destructive* negation gate — it decides at ingest
whether an extracted disease ever becomes a published indication. `test_negation_scoping.py`
fixed span scoping for the *reporting* half (`on_label_merge._build_disease_provenance`);
these tests hold the destructive half to the same semantics, and pin the four
false drops measured against the shipped DailyMed knowledge base.
"""

from __future__ import annotations

from medic.spans import readable_span_indices, readable_spans, spans_for_source
from medic.validation.extraction_fidelity import (
    screen_contraindications,
    screen_indications,
)

# The §4.3 fixture from test_negation_scoping.py: a positive claim followed by a
# Limitations-of-Use sentence that negates a *different* use of the same drug.
UBRELVY = (
    "UBRELVY is indicated for the acute treatment of migraine with or without aura in "
    "adults. Limitations of Use UBRELVY is not indicated for the preventive treatment of "
    "migraine."
)


# ---------------------------------------------------------------------------
# readable_spans — the shared definition merge and ingest both read
# ---------------------------------------------------------------------------
def test_readable_spans_excludes_headers_and_limitations():
    spans = spans_for_source("DAILYMED", UBRELVY, document="d", section_code="34067-9")
    roles = [s["role"] for s in readable_spans(spans)]
    assert roles == ["SECTION_TEXT"]


def test_readable_span_indices_are_positions_in_the_original_list():
    spans = spans_for_source("DAILYMED", UBRELVY, document="d", section_code="34067-9")
    idx = readable_span_indices(spans)
    assert [spans[i]["role"] for i in idx] == ["SECTION_TEXT"]
    limitation = [s["role"] for s in spans].index("LIMITATION_STATEMENT")
    assert limitation not in idx


def test_readable_spans_of_a_structureless_source_is_the_whole_text():
    spans = spans_for_source("EMA", "Indicated for anxiety", document="d", section_code="")
    assert [s["role"] for s in readable_spans(spans)] == ["STRUCTURED_FIELD"]


# ---------------------------------------------------------------------------
# screen_indications — span scoping
# ---------------------------------------------------------------------------
def test_a_limitations_clause_does_not_drop_the_positive_claim():
    """The destructive half of the §4.3 bug: the limitation must not kill the approval."""
    result = screen_indications(["migraine with aura"], UBRELVY)
    assert result.kept == ["migraine with aura"]
    assert result.dropped == []


def test_a_disease_stated_only_inside_a_limitation_is_dropped():
    """A disease whose sole textual basis is a negated Limitations-of-Use sentence was
    never indicated — the mirror of on_label_merge._polarity_flags' third check."""
    text = (
        "PRODUCT is indicated for the acute treatment of migraine. Limitations of Use "
        "PRODUCT is not indicated for cluster headache."
    )
    result = screen_indications(["cluster headache"], text)
    assert result.kept == []
    assert [d["disease"] for d in result.dropped] == ["cluster headache"]


def test_a_genuinely_negated_claim_is_still_dropped():
    result = screen_indications(
        ["migraine with aura"],
        "PRODUCT is not indicated for the treatment of migraine with aura.")
    assert result.kept == []
    assert result.dropped[0]["reason"]


# ---------------------------------------------------------------------------
# Regression: the four false drops measured on kb/indications/dailymed
# ---------------------------------------------------------------------------
def test_rezvoglar_diabetic_ketoacidosis_is_not_dropped():
    """A 'not recommended' belonging to a different clause killed a real approval."""
    text = (
        "1 INDICATIONS AND USAGE REZVOGLAR is indicated to improve glycemic control in "
        "adult and pediatric patients with diabetes mellitus. It is also indicated for "
        "the treatment of diabetic ketoacidosis; intravenous insulin is not recommended "
        "for routine outpatient use."
    )
    assert screen_indications(["diabetic ketoacidosis"], text).kept == ["diabetic ketoacidosis"]


def test_aspirin_omeprazole_cardiac_indications_are_not_dropped():
    """'not for use' scoped to a different sentence must not reach the indications."""
    text = (
        "1 INDICATIONS AND USAGE ASPIRIN AND OMEPRAZOLE DELAYED-RELEASE TABLETS is "
        "indicated for patients who require aspirin for secondary prevention of "
        "myocardial infarction and acute coronary syndrome. Limitations of Use This "
        "product is not for use in the initial treatment of acute myocardial infarction."
    )
    result = screen_indications(
        ["myocardial infarction", "acute coronary syndrome"], text)
    assert result.kept == ["myocardial infarction", "acute coronary syndrome"]
    assert result.dropped == []


# ---------------------------------------------------------------------------
# The unlocatable bucket — no longer laundered into a clean pass
# ---------------------------------------------------------------------------
def test_a_canonicalised_disease_is_reported_as_unlocatable_not_as_checked():
    """The LLM's own canonicalisation makes the phrase unfindable; the screen cannot
    judge polarity, and must say so rather than silently pass the row (#59)."""
    text = "XYZ is not indicated for the treatment of patients with type 2 diabetes."
    result = screen_indications(["type 2 diabetes mellitus"], text)
    assert result.kept == ["type 2 diabetes mellitus"]  # conservative: still kept
    assert result.unlocatable == ["type 2 diabetes mellitus"]  # but no longer silent


def test_a_located_disease_is_not_reported_as_unlocatable():
    result = screen_indications(["epilepsy"], "PRODUCT is indicated for epilepsy.")
    assert result.kept == ["epilepsy"]
    assert result.unlocatable == []


def test_a_dropped_disease_is_not_also_unlocatable():
    result = screen_indications(["asthma"], "Not indicated for the treatment of asthma.")
    assert result.unlocatable == []


# ---------------------------------------------------------------------------
# screen_contraindications — its own polarity, not the indication cue list
# ---------------------------------------------------------------------------
def test_contraindication_cues_are_not_the_indication_cues():
    """'contraindicated in X' is the *positive* trigger in a §4.3 section. Screening it
    with the indication cue list (which contains 'contraindicat') would drop everything."""
    text = "PRODUCT is contraindicated in patients with severe hepatic impairment."
    result = screen_contraindications(["severe hepatic impairment"], text)
    assert result.kept == ["severe hepatic impairment"]
    assert result.dropped == []


def test_an_explicitly_non_contraindicated_condition_is_dropped():
    text = "PRODUCT is not contraindicated in patients with renal impairment."
    result = screen_contraindications(["renal impairment"], text)
    assert result.kept == []
    assert [d["disease"] for d in result.dropped] == ["renal impairment"]


def test_an_excepted_condition_is_dropped_from_contraindications():
    text = "Contraindicated in all hepatic disease; except mild hepatic steatosis."
    result = screen_contraindications(["mild hepatic steatosis"], text)
    assert result.kept == []


def test_should_not_be_used_stays_a_contraindication():
    """A 'should not' phrase is how a contraindication is *stated*, not how it is negated."""
    text = "PRODUCT should not be used in patients with active tuberculosis."
    assert screen_contraindications(["active tuberculosis"], text).kept == [
        "active tuberculosis"]
