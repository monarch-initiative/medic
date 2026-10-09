"""Corroboration must not lower a pair's tier (#61).

Every gate folded with `_worst` across a pair's assertions, so a pair attested by three
regulators was scored by whichever read worst. `confidence.corroboration()` is built on
the opposite premise — independent sources make the linking *more* likely to be right —
and both numbers ship on the same record and the same KGX edge. Measured over the
products, 82.2% of single-source pairs reached HIGH against 0% of four-source pairs.

`_worst` is still right *within* one assertion: a claim is as good as its weakest link.
Across assertions it is not, so the two folds are now separate.
"""

from __future__ import annotations

import itertools

import pytest

from medic.reliability import (
    ReliabilityTier,
    StatementType,
    _aggregate_pair,
    _TIER_ORDER,
    score_reliability,
)

TIERS = [ReliabilityTier.EXCLUDED, ReliabilityTier.LOW,
         ReliabilityTier.MEDIUM, ReliabilityTier.HIGH]


def _assertion(quality="lexical_exact", confidence=0.99, source="EMA"):
    """One source attestation, with a disease mention whose grounding drives the tier."""
    return {
        "source": source,
        "document": f"{source}:doc",
        # One row per source document, singular — the shape `assoc_evidence` reads.
        "evidence": {"snippet": "is indicated for invasive aspergillosis",
                     "reference": f"https://example.invalid/{source}"},
        "assertion": {"confidence": {"overall": 0.9}},
        "disease": {"resolved_id": "MONDO:0000240", "resolution": {"pipeline": [
            {"category": "GROUNDING", "quality": quality,
             "output_value": "MONDO:0000240",
             "confidence": confidence, "confidence_basis": "MEASURED"}]}},
    }


def _pair(*assertions):
    return {"drug_id": "CHEBI:10023", "disease_id": "MONDO:0000240",
            "relationship_type": "INDICATION", "assertions": list(assertions)}


# ---------------------------------------------------------------------------
# The invariant the issue asks for, stated as a property
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("existing,added", [
    (combo, extra)
    for n in (1, 2)
    for combo in itertools.combinations_with_replacement(TIERS, n)
    for extra in TIERS
])
def test_adding_an_attestation_never_lowers_the_tier(existing, added):
    before = _aggregate_pair(list(existing))
    after = _aggregate_pair([*existing, added])
    assert _TIER_ORDER[after] >= _TIER_ORDER[before], (
        f"{existing} scored {before}, adding {added} dropped it to {after}")


def test_the_pair_takes_its_strongest_attestation():
    assert _aggregate_pair([ReliabilityTier.LOW, ReliabilityTier.HIGH]) is ReliabilityTier.HIGH
    assert _aggregate_pair(
        [ReliabilityTier.EXCLUDED, ReliabilityTier.MEDIUM]) is ReliabilityTier.MEDIUM


def test_a_pair_with_no_good_attestation_stays_weak():
    assert _aggregate_pair([ReliabilityTier.LOW, ReliabilityTier.LOW]) is ReliabilityTier.LOW
    assert _aggregate_pair(
        [ReliabilityTier.EXCLUDED, ReliabilityTier.EXCLUDED]) is ReliabilityTier.EXCLUDED


# ---------------------------------------------------------------------------
# Through the public scorer
# ---------------------------------------------------------------------------
def test_a_weak_source_no_longer_demotes_a_strong_one():
    """The India case: combining a poorly-grounding source with a strong one produced
    0% HIGH. Adding a source can no longer degrade the existing subset."""
    strong = _pair(_assertion())
    both = _pair(_assertion(), _assertion(quality="fuzzy", confidence=0.4, source="INDIA"))
    assert score_reliability(strong, StatementType.INDICATION) is ReliabilityTier.HIGH
    assert score_reliability(both, StatementType.INDICATION) is ReliabilityTier.HIGH


def test_a_single_assertion_pair_is_unchanged():
    weak = _pair(_assertion(quality="fuzzy", confidence=0.4))
    assert score_reliability(weak, StatementType.INDICATION) is ReliabilityTier.LOW


def test_every_attestation_weak_leaves_the_pair_weak():
    weak = _pair(_assertion(quality="fuzzy", confidence=0.4),
                 _assertion(quality="fuzzy", confidence=0.4, source="PMDA"))
    assert score_reliability(weak, StatementType.INDICATION) is ReliabilityTier.LOW


def test_corroboration_moves_the_tier_the_same_way_as_confidence():
    """The two quality numbers on the record must not point in opposite directions."""
    tiers = [
        score_reliability(_pair(*[_assertion(source=f"S{i}") for i in range(n)]),
                          StatementType.INDICATION)
        for n in (1, 2, 3, 4)
    ]
    orders = [_TIER_ORDER[t] for t in tiers]
    assert orders == sorted(orders), f"tier fell as sources were added: {tiers}"
