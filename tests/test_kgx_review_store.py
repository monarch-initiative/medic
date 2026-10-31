"""The KGX export must honour the curator review store (#62).

`score_reliability` takes a `review_status` and its docstring says a human verdict wins
first — CONFIRM forces HIGH, REJECT forces EXCLUDED. Every caller in the repo supplied it
except the four in the export, which recomputed the tier from the automated gates alone.
A curator's REJECTED was therefore discarded at the exact point the graph is published,
and the record shipped as `medic_reliability: HIGH`.

These tests drive the public builders, not the private helpers, because the defect was
that the *wiring* never reached them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from medic.reliability import StatementReviewStore


class _Store(StatementReviewStore):
    """An in-memory review store keyed the way the real one is."""

    def __init__(self, verdicts: dict[str, str]):
        super().__init__(path="")
        self._rows = dict(verdicts)


DRUG = "CHEBI:10023"
DISEASE = "MONDO:0000240"


def _assertion(**kw):
    from tests.test_kgx_export import _assertion as base
    return base(**kw)


@pytest.fixture
def pair():
    from tests.test_kgx_export import PAIR
    return PAIR


# ---------------------------------------------------------------------------
# Indication / contraindication edges
# ---------------------------------------------------------------------------
def test_a_rejected_pair_does_not_ship_as_high(pair):
    from medic.export.kgx import edges

    review = _Store({f"{DRUG}|{DISEASE}|INDICATION": "REJECTED"})
    built, _ = edges.build_edges([pair], [], [], [], review=review)
    assert built, "expected the pair to still produce edges"
    assert {e["medic_reliability"] for e in built} == {"EXCLUDED"}


def test_a_confirmed_pair_ships_as_high(pair):
    from medic.export.kgx import edges

    review = _Store({f"{DRUG}|{DISEASE}|INDICATION": "CONFIRMED"})
    built, _ = edges.build_edges([pair], [], [], [], review=review)
    assert {e["medic_reliability"] for e in built} == {"HIGH"}


def test_an_empty_store_leaves_the_gate_verdict_untouched(pair):
    """Regression guard: the store is empty today, so this must be a no-op."""
    from medic.export.kgx import edges

    with_store, _ = edges.build_edges([pair], [], [], [], review=_Store({}))
    without, _ = edges.build_edges([pair], [], [], [])
    assert [e["medic_reliability"] for e in with_store] == \
           [e["medic_reliability"] for e in without]


def test_a_rejected_contraindication_is_excluded_too(pair):
    from medic.export.kgx import edges

    contra = {**pair, "relationship_type": "CONTRAINDICATION"}
    review = _Store({f"{DRUG}|{DISEASE}|CONTRAINDICATION": "REJECTED"})
    built, _ = edges.build_edges([], [contra], [], [], review=review)
    assert {e["medic_reliability"] for e in built} == {"EXCLUDED"}


# ---------------------------------------------------------------------------
# Research and adverse-event edges
# ---------------------------------------------------------------------------
def test_a_rejected_research_association_is_excluded():
    from medic.export.kgx import edges
    from tests.test_kgx_export import RESEARCH

    key = f"{RESEARCH['drug_id']}|{RESEARCH['disease_id']}|RESEARCH_ASSOCIATION"
    built, _ = edges.build_edges([], [], [RESEARCH], [], review=_Store({key: "REJECTED"}))
    assert built
    assert {e["medic_reliability"] for e in built} == {"EXCLUDED"}


# ---------------------------------------------------------------------------
# Drug nodes
# ---------------------------------------------------------------------------
def test_a_rejected_drug_node_is_excluded():
    from medic.export.kgx import nodes
    from tests.test_kgx_export import DRUG_RECORD

    review = _Store({"CHEBI:100147|DRUG_APPROVAL": "REJECTED"})
    built = nodes.build_nodes([DRUG_RECORD], [], review=review)
    node = next(n for n in built if n["id"] == "CHEBI:100147")
    assert node["medic_reliability"] == "EXCLUDED"


# ---------------------------------------------------------------------------
# The wiring itself — this is the class of bug, not one instance of it
# ---------------------------------------------------------------------------
def test_no_export_call_site_scores_reliability_without_a_review_status():
    """The four call sites were individually correct-looking; the omission was invisible
    because nothing asserted it. Pin the property, not the four lines."""
    offenders = []
    for path in sorted(Path("src/medic/export").rglob("*.py")):
        src = path.read_text()
        for match in re.finditer(r"score_reliability\(", src):
            tail = src[match.end():match.end() + 400]
            depth, arglist = 1, []
            for ch in tail:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        break
                arglist.append(ch)
            if "review_status" not in "".join(arglist):
                line = src[:match.start()].count("\n") + 1
                offenders.append(f"{path}:{line}")
    assert not offenders, (
        "score_reliability called without review_status in the export — a curator's "
        f"REJECTED would be discarded at these sites: {offenders}"
    )
