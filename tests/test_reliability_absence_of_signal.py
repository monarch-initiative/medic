"""Nothing reaches HIGH by absence of signal (#60).

`reliability.py`'s module docstring states the safety property the whole tier rests on:

    A gate returns ``None`` when it does not apply ...; the provenance gate always
    applies, so nothing reaches HIGH by absence of signal.

Both halves were false. `_worst([])` returned HIGH — the identity element of a min-fold,
correct as arithmetic and wrong as policy — and the provenance gate passes on any one of
five weak signals, so it cannot be the backstop the sentence claims. A record with a
single evidence field and nothing else scored HIGH and entered the published subset.

These tests pin the property itself, not the arithmetic, because the property is what a
consumer is relying on when they filter on the tier.
"""

from __future__ import annotations

import pytest

from medic.reliability import (
    ReliabilityTier,
    StatementType,
    _worst,
    is_reliable,
    score_reliability,
)


# ---------------------------------------------------------------------------
# The fold's identity element
# ---------------------------------------------------------------------------
def test_an_empty_gate_list_is_not_high():
    """`min` over nothing has no floor to fall back to. HIGH is the arithmetic identity
    and the exact opposite of the conservative answer a tier is for."""
    assert _worst([]) is not ReliabilityTier.HIGH


def test_an_all_abstaining_gate_list_is_not_high():
    assert _worst([None, None, None]) is not ReliabilityTier.HIGH


def test_the_worst_of_real_verdicts_is_unchanged():
    assert _worst([ReliabilityTier.HIGH, ReliabilityTier.LOW]) is ReliabilityTier.LOW
    assert _worst([ReliabilityTier.HIGH, None]) is ReliabilityTier.HIGH
    assert _worst([ReliabilityTier.MEDIUM, ReliabilityTier.EXCLUDED]) is ReliabilityTier.EXCLUDED


# ---------------------------------------------------------------------------
# The property, through the public scorer
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("evidence", [
    {"snippet": "x"},
    {"original_drug_id": "anything"},
    {"reference": "http://example.invalid/x"},
    {"source_document_url": "http://example.invalid/y"},
])
def test_a_record_with_only_provenance_does_not_reach_high(evidence):
    """Each of these satisfies `_provenance_gate` on its own. None of them says anything
    about whether the right entity was grounded or the relation was read correctly."""
    record = {"relationship_type": "INDICATION", "evidence": [evidence]}
    assert score_reliability(record) is not ReliabilityTier.HIGH


def test_a_record_with_only_provenance_is_not_in_the_published_subset():
    record = {"relationship_type": "INDICATION", "evidence": [{"snippet": "x"}]}
    assert not is_reliable(record)


def test_a_record_with_no_provenance_at_all_is_still_low_or_worse():
    record = {"relationship_type": "INDICATION", "evidence": [{}]}
    assert score_reliability(record) in (ReliabilityTier.LOW, ReliabilityTier.EXCLUDED)


def test_a_substantive_gate_verdict_still_earns_high():
    """The fix must not make HIGH unreachable — invariant: every statement can reach HIGH
    on its own merits (`reliability.py` docstring)."""
    record = {
        "relationship_type": "INDICATION",
        "evidence": [{"snippet": "indicated for epilepsy"}],
        "disease_grounding": {"grounding_quality": "lexical_exact",
                              "grounded_id": "MONDO:0005027"},
    }
    assert score_reliability(record) is ReliabilityTier.HIGH


def test_a_curator_confirmation_still_overrides_everything():
    """Human review mitigates all concerns — the second stated invariant."""
    record = {"relationship_type": "INDICATION", "evidence": [{"snippet": "x"}]}
    assert score_reliability(record, review_status="CONFIRMED") is ReliabilityTier.HIGH


# ---------------------------------------------------------------------------
# A missing measurement is not a perfect measurement
# ---------------------------------------------------------------------------
def _record_with_grounding_step(**step):
    return {
        "relationship_type": "INDICATION",
        "evidence": [{"snippet": "x"}],
        "disease": {"resolution": {"pipeline": [
            {"category": "GROUNDING", "output_value": "MONDO:0005027", **step}]}},
    }


def test_an_inexact_grounding_with_no_confidence_does_not_reach_high():
    """`conf = float(conf) if conf is not None else 1.0` made "we never scored this"
    indistinguishable from "we scored this perfectly"."""
    record = _record_with_grounding_step(quality="fuzzy")
    assert score_reliability(record) is not ReliabilityTier.HIGH


def test_a_deterministic_step_may_omit_confidence_and_still_reach_high():
    """`ConfidenceBasis.DETERMINISTIC` means the step cannot be wrong, so 1.0 is
    legitimately implied — that is the one case where the old default was right."""
    record = _record_with_grounding_step(
        quality="fuzzy", confidence_basis="DETERMINISTIC")
    assert score_reliability(record) is ReliabilityTier.HIGH


def test_a_measured_high_confidence_still_reaches_high():
    record = _record_with_grounding_step(
        quality="fuzzy", confidence=0.95, confidence_basis="MEASURED")
    assert score_reliability(record) is ReliabilityTier.HIGH


def test_a_measured_low_confidence_is_still_low():
    record = _record_with_grounding_step(
        quality="fuzzy", confidence=0.4, confidence_basis="MEASURED")
    assert score_reliability(record) is ReliabilityTier.LOW


# ---------------------------------------------------------------------------
# Approvals keep their own gate
# ---------------------------------------------------------------------------
def test_a_drug_approval_with_nothing_but_provenance_does_not_reach_high():
    record = {"approvals": [{"authority": "FDA", "status": "APPROVED",
                             "application_number": "014214"}]}
    assert score_reliability(record, StatementType.DRUG_APPROVAL) is not ReliabilityTier.HIGH
