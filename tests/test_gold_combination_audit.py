"""The combination gold standard, and the scorer that uses it.

PRs #69-#87 hand-curated 1,133 claims over 103 DailyMed SPLs and 102 ingredient sets.
`plan.md` said to wire them in as tests **before** the prompt changes; that did not happen,
so #88 (combination attribution), #89 (context) and #97 all shipped with no regression set
to score them against. These tests guard the recovered data and the scorer's logic — the
scorer itself needs a built `products/`, so the measurement lives behind
`just gold-combination-audit` rather than in the suite.

The attribution cases are the point. A curated claim with no `attributed_to` is
*product-level*: the sentence's subject is the product, so every ingredient of the label
owns it. One with `attributed_to` belongs to the named moiety alone. Getting those two
backwards fails in opposite directions, and a scorer that collapses them into one number
cannot tell which way #88 is wrong.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.gold_combination_audit import (
    GOLD_DIR, RELATION_MAP, TermIndex, load_gold, score)

pytestmark = pytest.mark.skipif(
    not GOLD_DIR.exists(), reason="curation/combinations/ not present")


# ---------------------------------------------------------------------------
# The data itself
# ---------------------------------------------------------------------------
def test_the_gold_standard_is_the_whole_pilot():
    """102 ingredient sets, ~1,100 claims. Pins the size so a partial recovery from branch
    history (the files live on 19 branches with a shared base) is visible rather than
    silently halving the test set."""
    rows = load_gold()
    assert len({r["file"] for r in rows}) == 102
    assert len(rows) > 1_000, len(rows)
    assert len({r["setid"] for r in rows}) > 100


def test_every_claim_has_a_setid_and_a_known_relation():
    for row in load_gold():
        assert len(row["setid"]) >= 36, row
        assert row["relation"] in set(RELATION_MAP.values()), row


def test_the_relation_map_covers_every_curated_relation():
    """A curated relation missing from the map is silently dropped from the score, which
    would read as a smaller test set rather than as an error."""
    import yaml

    seen = set()
    for path in Path(GOLD_DIR).glob("*.yaml"):
        doc = yaml.safe_load(path.read_text()) or {}
        for product in doc.get("products") or []:
            for claim in product.get("claims") or []:
                seen.add(str(claim.get("relation") or ""))
    assert seen <= set(RELATION_MAP), sorted(seen - set(RELATION_MAP))


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
SETID = "11111111-2222-3333-4444-555555555555"


def _gold(**over):
    row = {"file": "a-b.yaml", "setid": SETID, "relation": "INDICATION",
           "disease_id": "MONDO:1", "binding": "EXACT",
           "ingredients": ["CHEBI:A", "CHEBI:B"], "owners": []}
    row.update(over)
    return [row]


def test_a_claim_we_do_not_assert_is_a_miss():
    counts = score(_gold(), {})["counts"]
    assert counts["missed"] == 1 and counts.get("found", 0) == 0


def test_a_product_level_claim_must_reach_every_ingredient():
    build = {(SETID, "INDICATION", "MONDO:1"): {"CHEBI:A", "CHEBI:B"}}
    counts = score(_gold(), build)["counts"]
    assert counts["found"] == 1 and counts["attribution_ok"] == 1


def test_a_product_level_claim_on_only_one_ingredient_is_under_attributed():
    """The claim is right and the split dropped half of it — the opposite failure from
    #88's, and invisible if both are counted as "found"."""
    build = {(SETID, "INDICATION", "MONDO:1"): {"CHEBI:A"}}
    counts = score(_gold(), build)["counts"]
    assert counts["under_attributed"] == 1 and counts.get("attribution_ok", 0) == 0


def test_an_attributed_claim_credited_to_the_partner_is_over_attributed():
    """#88's failure mode exactly: "avibactam treats pyelonephritis" is ceftazidime's claim
    inherited by the wrong moiety."""
    build = {(SETID, "INDICATION", "MONDO:1"): {"CHEBI:A", "CHEBI:B"}}
    counts = score(_gold(owners=["CHEBI:A"]), build)["counts"]
    assert counts["over_attributed"] == 1


def test_an_attributed_claim_on_its_own_moiety_is_correct():
    build = {(SETID, "INDICATION", "MONDO:1"): {"CHEBI:A"}}
    counts = score(_gold(owners=["CHEBI:A"]), build)["counts"]
    assert counts["attribution_ok"] == 1


def test_an_inexactly_bound_disease_is_excluded_rather_than_failed():
    """'HIV-1 infection' bound to MONDO:0005109 'HIV infectious disease' as BROADER is a
    curator's considered compromise about a gap in Mondo, not a target to reproduce. Scoring
    it would charge us for the curator's own caveat."""
    result = score(_gold(binding="BROADER"), {})
    assert result["counts"]["inexact_binding"] == 1
    assert result["counts"].get("scored", 0) == 0


def test_a_claim_with_no_curated_term_is_excluded():
    result = score(_gold(disease_id=""), {})
    assert result["counts"]["no_curated_term"] == 1


def test_the_setid_match_is_case_insensitive():
    build = {(SETID, "INDICATION", "MONDO:1"): {"CHEBI:A", "CHEBI:B"}}
    counts = score(_gold(setid=SETID.upper().lower()), build)["counts"]
    assert counts["found"] == 1


# ---------------------------------------------------------------------------
# Scoring the same condition under a different id (#105)
# ---------------------------------------------------------------------------
# A pure `(setid, relation, disease_id)` join counts a claim as missing whenever the curator
# and the pipeline named the condition at a different specificity or in a different
# ontology. Measured over the 626 scored claims, that is 88 of the 324 apparent misses: 72
# cross-ontology equivalents and 16 hierarchy or wording. `v1_pair_gap.py` was fixed for the
# same defect; these are the cases that fix has to cover here.


def _terms(**over) -> TermIndex:
    index = TermIndex(strings={}, xrefs={}, parents={})
    for key, value in over.items():
        getattr(index, key).update(value)
    return index


def test_a_cross_ontology_equivalent_is_not_a_miss():
    """The real case: curated MONDO:0000004 'adrenocortical insufficiency' against our
    HP:0000846 'Adrenal insufficiency'. The id join scores it twice wrong — a missed curated
    claim, and our correct extraction as an unrelated extra."""
    build = {(SETID, "INDICATION", "HP:1"): {"CHEBI:A", "CHEBI:B"}}
    terms = _terms(xrefs={"MONDO:1": {"HP:1"}, "HP:1": {"MONDO:1"}})
    counts = score(_gold(), build, terms)["counts"]
    assert counts["found_equivalent"] == 1
    assert counts.get("missed", 0) == 0


def test_an_equivalent_by_exact_synonym_counts_too():
    """Mondo records 'adrenal insufficiency' as a `hasExactSynonym` of MONDO:0000004, which
    is HP:0000846's primary label — so the two are the same condition even where neither
    carries an xref to the other."""
    build = {(SETID, "INDICATION", "HP:1"): {"CHEBI:A", "CHEBI:B"}}
    terms = _terms(strings={"MONDO:1": {"adrenal insufficiency"},
                            "HP:1": {"adrenal insufficiency"}})
    counts = score(_gold(), build, terms)["counts"]
    assert counts["found_equivalent"] == 1


def test_an_object_of_ours_that_is_more_specific_is_not_a_miss():
    build = {(SETID, "INDICATION", "MONDO:2"): {"CHEBI:A", "CHEBI:B"}}
    counts = score(_gold(), build, _terms(parents={"MONDO:2": {"MONDO:1"}}))["counts"]
    assert counts["found_descendant"] == 1


def test_an_object_of_ours_that_is_coarser_is_counted_separately():
    """Reported apart from the finer case on purpose: against a curator, asserting the
    parent is less specific than the ground truth, where asserting the child is more. They
    are both partial hits and they are not the same result."""
    build = {(SETID, "INDICATION", "MONDO:0"): {"CHEBI:A", "CHEBI:B"}}
    counts = score(_gold(), build, _terms(parents={"MONDO:1": {"MONDO:0"}}))["counts"]
    assert counts["found_coarser"] == 1
    assert counts.get("found_descendant", 0) == 0


def test_an_unrelated_object_on_the_same_document_is_still_a_miss():
    """The guard against the buckets swallowing the gap: a different condition on the same
    label must not be scored as a hit just because something was asserted there."""
    build = {(SETID, "INDICATION", "MONDO:9"): {"CHEBI:A", "CHEBI:B"}}
    counts = score(_gold(), build, _terms())["counts"]
    assert counts["missed"] == 1


def test_the_strict_count_still_only_holds_exact_id_matches():
    """`found` keeps its old meaning so the strict number stays comparable across builds."""
    build = {(SETID, "INDICATION", "HP:1"): {"CHEBI:A", "CHEBI:B"}}
    terms = _terms(xrefs={"MONDO:1": {"HP:1"}, "HP:1": {"MONDO:1"}})
    counts = score(_gold(), build, terms)["counts"]
    assert counts.get("found", 0) == 0


def test_without_a_term_index_scoring_is_the_strict_join():
    """The ontology cache is 130MB and untracked, so the gate has to work without it."""
    build = {(SETID, "INDICATION", "HP:1"): {"CHEBI:A", "CHEBI:B"}}
    counts = score(_gold(), build)["counts"]
    assert counts["missed"] == 1
    assert counts.get("found_equivalent", 0) == 0


def test_attribution_is_scored_on_an_equivalent_match_too():
    """Whether the right moieties were credited is answerable for any claim we did assert,
    whichever id we asserted it under."""
    build = {(SETID, "INDICATION", "HP:1"): {"CHEBI:A"}}
    terms = _terms(xrefs={"MONDO:1": {"HP:1"}, "HP:1": {"MONDO:1"}})
    counts = score(_gold(), build, terms)["counts"]
    assert counts["under_attributed"] == 1


def test_a_hierarchy_walk_stops_before_the_root():
    """Mondo is deep. Beyond a handful of steps a shared ancestor stops meaning the two
    sides agreed about anything — the same bound `v1_pair_gap` settled on."""
    chain = {f"MONDO:{i}": {f"MONDO:{i - 1}"} for i in range(1, 12)}
    build = {(SETID, "INDICATION", "MONDO:11"): {"CHEBI:A", "CHEBI:B"}}
    counts = score(_gold(), build, _terms(parents=chain))["counts"]
    assert counts["missed"] == 1
