"""How many of a reference release's drugs are genuinely absent, vs merely re-identified?

`just compare-release` reports the drug curie overlap, which against v1.0.0 is 45.2% and
reads like a 55% coverage loss. It is not. v1 identified many drugs by UNII, RXCUI,
PUBCHEM.COMPOUND or DRUGBANK where the current pipeline uses CHEBI, so an id-string join
counts the same drug as a miss. Effective coverage — reachable by id *or* by a name we know
the drug under — is 68.0%.

Both numbers are true and they answer different questions. This script exists because the
id-only number keeps getting quoted as a coverage loss, including by me.

**A third question, added after measuring it.** Effective coverage matches on v1's
`curie_label` alone, so it still counts a drug as absent when v1 minted a row for a
*product* whose moieties we carry separately, or for a moiety whose salt form we carry:

    v1 RXCUI:1925495  'dapagliflozin / saxagliptin Oral Product'  -> we hold both moieties
    v1 PUBCHEM.COMPOUND:71494926 'Orkambi'                         -> lumacaftor + ivacaftor
    v1 CHEBI:135161   'hydroxystilbamidine'                        -> we hold the isethionate

That is 621 of the 1,243 apparently-absent drugs, and it is the modelling difference
`docs/architecture.md` records deliberately: the pipeline resolves a product to its active
moieties rather than minting a node for the pack. Counting it as lost coverage punishes the
decision. So substance coverage is reported beside the other two, and the real gap is 437
drugs — 227 India, 140 Russia, 27 Japan, 14 USA.

The strict and effective numbers are still printed unchanged, because "can a consumer look
this exact drug up" and "do we carry this substance at all" are different questions and only
the first is answered by an id.

Run after a build:

    just v1-drug-gap            # needs tmp/old_release/, populated by `just compare-release`
"""
from __future__ import annotations

import argparse
import collections
import re
from pathlib import Path

import pandas as pd

OLD = Path("tmp/old_release/drug_list_flexible.csv")
NEW = Path("exports/drug_list_flexible.csv")

#: v1 packs several names into one cell, variously quoted and bracketed.
SPLIT = re.compile(r"[;,|\[\]'\"]+")

#: Columns that may name the substances a v1 row stands for.
INGREDIENT_COLS = ("combination_therapy_ingredients", "source_ingredients")

#: Columns of ours that may name a drug we carry.
OUR_NAME_COLS = ("curie_label", "source_ingredients",
                 "combination_therapy_ingredients", "synonyms")


def norm(s: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())


def parts(value: object) -> list[str]:
    return [p.strip() for p in SPLIT.split(str(value or "")) if p.strip()]


def truthy(value: object) -> bool:
    return str(value or "").strip().lower() in ("true", "1", "1.0", "yes")


def known_names(new: pd.DataFrame) -> set[str]:
    """Every normalised string the current export knows some drug under."""
    known: set[str] = set()
    for _, row in new.iterrows():
        for col in OUR_NAME_COLS:
            for part in parts(row.get(col, "")):
                known.add(norm(part))
    known.discard("")
    return known


def substances_of(row: pd.Series) -> list[str]:
    """The substance names a v1 row stands for.

    `combination_therapy_ingredients` when it has them, else the source ingredient strings —
    which for a single-moiety row is usually the salt form ('HYDROXYSTILBAMIDINE
    ISETHIONATE' for 'hydroxystilbamidine').
    """
    for col in INGREDIENT_COLS:
        found = parts(row.get(col, ""))
        if found:
            return found
    return []


def classify(old: pd.DataFrame, new: pd.DataFrame) -> dict:
    """Bucket every v1 drug. Buckets are exclusive and ordered most-reachable first."""
    known = known_names(new)
    new_curies = set(new["curie"])
    old_curies = set(old["curie"])

    buckets: dict[str, list[pd.Series]] = collections.defaultdict(list)
    for _, row in old.iterrows():
        if row["curie"] in new_curies:
            buckets["overlap"].append(row)
            continue
        if norm(row.get("curie_label", "")) in known:
            buckets["label_known"].append(row)
            continue
        names = substances_of(row)
        covered = [n for n in names if norm(n) in known]
        if names and len(covered) == len(names):
            key = ("combination_covered" if truthy(row.get("is_combination_therapy"))
                   else "ingredient_known")
            buckets[key].append(row)
        elif covered:
            buckets["partly_covered"].append(row)
        else:
            buckets["absent"].append(row)
    return {"buckets": dict(buckets), "n_v1": len(old_curies),
            "n_new": len(new_curies), "overlap_ids": len(old_curies & new_curies)}


def flag_breakdown(rows: list[pd.Series], columns: list[str]) -> collections.Counter:
    out: collections.Counter = collections.Counter()
    for row in rows:
        flags = [c.replace("approved_", "") for c in columns if truthy(row.get(c, ""))]
        out[",".join(sorted(flags)) or "(no approval flag)"] += 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--old", default=OLD, type=Path)
    ap.add_argument("--new", default=NEW, type=Path)
    args = ap.parse_args()

    for path, hint in ((args.old, "run `just compare-release` first to download it"),
                       (args.new, "run `just export-legacy` first to build it")):
        if not path.exists():
            raise SystemExit(f"missing {path} - {hint}")

    old = pd.read_csv(args.old, dtype=str).fillna("")
    new = pd.read_csv(args.new, dtype=str).fillna("")
    result = classify(old, new)
    b = result["buckets"]

    def n(key: str) -> int:
        return len(b.get(key, []))

    n_v1 = result["n_v1"]
    missing = n_v1 - result["overlap_ids"]
    matched = n("label_known")
    rest = b.get("absent", [])

    print(f"v1 curies: {n_v1}   current: {result['n_new']}")
    print(f"overlap by id: {result['overlap_ids']} "
          f"({100 * result['overlap_ids'] / max(1, n_v1):.1f}%)")
    print()
    print(f"absent by id: {missing}")
    print(f"  same drug, different id (name known to us): {matched} "
          f"({100 * matched / max(1, missing):.1f}%)")
    not_by_label = missing - matched
    print(f"  not reachable by label:                     {not_by_label} "
          f"({100 * not_by_label / max(1, missing):.1f}%)")
    print(f"    v1 row is a combination product we hold as moieties: "
          f"{n('combination_covered')}")
    print(f"    v1 row's own ingredient string is known to us:       "
          f"{n('ingredient_known')}")
    print(f"    some ingredients known, not all:                     "
          f"{n('partly_covered')}")
    print(f"    no substance of it anywhere in the export:           {len(rest)}")
    print()
    print("  prefixes of the genuinely-absent:",
          dict(collections.Counter(
              str(r["curie"]).split(":")[0] for r in rest).most_common(8)))
    print()
    print("  a sample of genuinely-absent labels:")
    for row in rest[:14]:
        print(f"     {str(row['curie']):26s} {str(row.get('curie_label', ''))[:44]}")

    effective = result["overlap_ids"] + matched
    substance = effective + n("combination_covered") + n("ingredient_known")
    print()
    print(f"effective v1 drug coverage: {effective}/{n_v1} "
          f"({100 * effective / max(1, n_v1):.1f}%)")
    print(f"substance coverage:         {substance}/{n_v1} "
          f"({100 * substance / max(1, n_v1):.1f}%)  "
          f"— counting a product we hold as its moieties")

    approval_cols = [c for c in old.columns if c.startswith("approved_")]
    if approval_cols:
        print()
        print("  genuinely-absent drugs by the reference release's approval flags:")
        for key, count in flag_breakdown(rest, approval_cols).most_common(12):
            print(f"     {count:5d}  {key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
