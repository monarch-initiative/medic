"""The v1 drug-coverage classifier.

The gap against v1.0.0 has been quoted three different ways in this repo, each lower than
the last was wrong: 45.2% by id join, 68.0% reachable by label, and 84.0% counting the
substance. The buckets below are the difference between them, and each one is a case the
earlier numbers got wrong in the pessimistic direction — which is this project's recurring
failure mode, so they are pinned.
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.v1_drug_gap import classify, known_names, substances_of, truthy

OLD_COLS = ["curie", "curie_label", "source_ingredients", "is_combination_therapy",
            "combination_therapy_ingredients", "combination_therapy_ingredients_curies",
            "approved_usa", "approved_india"]
NEW_COLS = ["curie", "curie_label", "source_ingredients",
            "combination_therapy_ingredients", "synonyms"]


def _old(**over) -> pd.DataFrame:
    row = {c: "" for c in OLD_COLS}
    row.update({"curie": "RXCUI:1", "curie_label": "Something"})
    row.update(over)
    return pd.DataFrame([row])


def _new(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{**{c: "" for c in NEW_COLS}, **r} for r in rows])


def _bucket(result: dict) -> str:
    present = [k for k, v in result["buckets"].items() if v]
    assert len(present) == 1, present
    return present[0]


def test_a_shared_id_is_an_overlap():
    result = classify(_old(curie="CHEBI:1"), _new([{"curie": "CHEBI:1"}]))
    assert _bucket(result) == "overlap"


def test_the_same_drug_under_a_different_id_is_not_absent():
    """v1 identified many drugs by UNII/RXCUI where we use CHEBI. An id join alone reads
    that as a 55% loss."""
    result = classify(_old(curie="RXCUI:1", curie_label="Voriconazole"),
                      _new([{"curie": "CHEBI:10023", "curie_label": "voriconazole"}]))
    assert _bucket(result) == "label_known"


def test_a_combination_product_we_hold_as_moieties_is_not_a_substance_gap():
    """v1 RXCUI:1925495 'dapagliflozin / saxagliptin Oral Product' against our two separate
    moieties. `docs/architecture.md` records resolving a product to its moieties as
    deliberate, so scoring it as lost coverage charges us for the decision."""
    result = classify(
        _old(curie="RXCUI:1925495", curie_label="dapagliflozin / saxagliptin Oral Product",
             is_combination_therapy="TRUE",
             combination_therapy_ingredients="Dapagliflozin, Saxagliptin"),
        _new([{"curie": "CHEBI:1", "curie_label": "dapagliflozin"},
              {"curie": "CHEBI:2", "curie_label": "saxagliptin"}]))
    assert _bucket(result) == "combination_covered"


def test_a_moiety_we_hold_only_as_its_salt_is_not_a_substance_gap():
    """v1 CHEBI:135161 'hydroxystilbamidine', whose source ingredient is the isethionate —
    which is the string our export carries. Matching on `curie_label` alone misses it."""
    result = classify(
        _old(curie="CHEBI:135161", curie_label="hydroxystilbamidine",
             source_ingredients="HYDROXYSTILBAMIDINE ISETHIONATE"),
        _new([{"curie": "CHEBI:9", "curie_label": "something else",
               "source_ingredients": "Hydroxystilbamidine isethionate"}]))
    assert _bucket(result) == "ingredient_known"


def test_a_combination_with_only_one_ingredient_covered_is_partial():
    result = classify(
        _old(curie="RXCUI:2", is_combination_therapy="TRUE",
             combination_therapy_ingredients="Lumacaftor, Ivacaftor"),
        _new([{"curie": "CHEBI:1", "curie_label": "ivacaftor"}]))
    assert _bucket(result) == "partly_covered"


def test_a_drug_with_no_substance_anywhere_is_absent():
    result = classify(_old(curie="CHEBI:9", curie_label="Garenoxacin",
                           source_ingredients="GARENOXACIN"),
                      _new([{"curie": "CHEBI:1", "curie_label": "voriconazole"}]))
    assert _bucket(result) == "absent"


def test_a_row_with_no_ingredient_columns_at_all_is_absent_not_covered():
    """The guard against the substance bucket swallowing the gap: an empty ingredient list
    must not vacuously satisfy "every ingredient is covered"."""
    result = classify(_old(curie="CHEBI:9", curie_label="Garenoxacin"),
                      _new([{"curie": "CHEBI:1", "curie_label": "voriconazole"}]))
    assert _bucket(result) == "absent"


def test_the_buckets_partition_the_reference_release():
    """Every v1 drug lands in exactly one bucket, so the percentages are of a whole."""
    old = pd.concat([
        _old(curie="CHEBI:1"),
        _old(curie="RXCUI:7", curie_label="Voriconazole"),
        _old(curie="CHEBI:9", curie_label="Garenoxacin"),
    ], ignore_index=True)
    result = classify(old, _new([{"curie": "CHEBI:1", "curie_label": "voriconazole"}]))
    assert sum(len(v) for v in result["buckets"].values()) == 3


@pytest.mark.parametrize("value", ["TRUE", "true", "1", "1.0", "yes", "Yes"])
def test_approval_and_combination_flags_survive_v1s_spellings(value):
    """v1 writes booleans at least four ways; a stricter reader silently files every
    combination product as a single-moiety row."""
    assert truthy(value)


@pytest.mark.parametrize("value", ["", "FALSE", "false", "0", "no", None])
def test_nothing_else_is_truthy(value):
    assert not truthy(value)


def test_combination_ingredients_win_over_the_source_string():
    row = _old(source_ingredients="A SALT",
               combination_therapy_ingredients="Alpha, Beta").iloc[0]
    assert substances_of(row) == ["Alpha", "Beta"]


def test_our_names_come_from_every_column_a_drug_may_be_named_in():
    known = known_names(_new([{"curie": "CHEBI:1", "curie_label": "Alpha",
                               "synonyms": "Beta|Gamma",
                               "source_ingredients": "DELTA SALT"}]))
    assert {"alpha", "beta", "gamma", "deltasalt"} <= known
