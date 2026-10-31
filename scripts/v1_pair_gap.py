#!/usr/bin/env python3
"""Compare v1.0.0's grounded drug-disease pairs with the current build, hierarchy-aware.

    just v1-pair-gap            # needs products/ built and cache/ontologies/mondo.json

**Why this exists.** The v1.0.0 release assets carry only drug lists, so comparisons stopped
at the drug level for a long time. Its *grounded* pair lists are in the old pipeline's
reporting output on `main` — 11,071 indication and 3,981 contraindication pairs with a final
normalized drug id and disease id — which this script reads directly from git.

**Why hierarchy-aware.** Matching on id, or on id plus exact label, counts a pair as missing
whenever the two releases named the disease at a different level of specificity:

    v1 "urinary tract infection"      ours "Recurrent urinary tract infections"
    v1 "Acute insomnia"               ours "Insomnia"
    v1 "metastatic colorectal cancer" ours "Colorectal cancer"

That is 20.2% of the apparent gap. Two of those classes are not losses at all:

* **ancestor** — we hold a parent of v1's disease for the same drug. v1 propagated
  indications *down* the Mondo hierarchy, so a drug approved for a category gained a pair for
  every subtype. `docs/architecture.md` §5.7 records that this was removed deliberately:
  annotations travel up a hierarchy, not down.
* **descendant** — we assert something *more* specific than v1 did. Scoring that as a loss
  punishes an improvement.

**Two more classes, added after measuring them.** Neither is a specificity difference:

* **equivalent** — the same condition in another vocabulary. v1's disease ids are MONDO
  8,720 / UMLS 1,310 / HP 812 / EFO 113 / NCIT 101 and ours are MONDO 54,667 / UMLS 25,110 /
  HP 15,393, so the join is cross-vocabulary by construction; Mondo alone carries 32,514
  UMLS and 574 HP xrefs to settle it. 205 indication and 54 contraindication pairs.
* **moiety** — v1 minted rows for combination *products* ('Orkambi', 'dapagliflozin /
  saxagliptin Oral Product') where the pipeline resolves to active moieties, so the pair
  matched no drug of ours by name and landed in `drug_absent` even where we assert the same
  disease for every ingredient. 345 indication and 281 contraindication pairs, and it is the
  same reclassification `v1_drug_gap` makes at the drug level.

Reporting the strict number alone overstated the regression, repeatedly and by me — by 16.5
points on indications and 13.6 on contraindications. A strict join is still printed, because
it is the right number for "can a consumer look this exact pair up", but it is no longer the
only one.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd
import yaml

from scripts.term_index import load_terms

V1_DIR = "medi/indications/data/08_reporting/indications_medi_coverage"
V1_FILES = {
    "indication": f"{V1_DIR}/matrix_indication_list.xlsx",
    "contraindication": f"{V1_DIR}/matrix_contraindication_list.xlsx",
}
MONDO = Path("cache/ontologies/mondo.json")
#: How far up the hierarchy to look. Mondo is deep; beyond a handful of steps an "ancestor"
#: is too general to mean the two releases agreed about anything.
MAX_DEPTH = 6


def norm(s: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())


def _from_git(path: str, ref: str) -> Path:
    """Extract a file from a git ref to a temp path. Keeps v1's data un-duplicated."""
    out = Path(tempfile.gettempdir()) / f"medic_v1_{Path(path).name}"
    with out.open("wb") as fh:
        res = subprocess.run(["git", "show", f"{ref}:{path}"], stdout=fh,
                             stderr=subprocess.PIPE, check=False)
    if res.returncode != 0 or not out.stat().st_size:
        raise SystemExit(f"could not read {path} from {ref}: "
                         f"{res.stderr.decode()[:200]}")
    return out


def mondo_parents() -> dict[str, set[str]]:
    """child CURIE -> direct parent CURIEs, from the Mondo obographs build input."""
    if not MONDO.exists():
        raise SystemExit(f"missing {MONDO} — run `just download-grounding-ontologies`")
    graph = json.loads(MONDO.read_text())["graphs"][0]
    parents: dict[str, set[str]] = collections.defaultdict(set)
    for e in graph.get("edges", ()):
        if e.get("pred") != "is_a":
            continue
        sub, obj = str(e.get("sub", "")), str(e.get("obj", ""))
        if "MONDO_" in sub and "MONDO_" in obj:
            parents[f"MONDO:{sub.rsplit('MONDO_', 1)[1]}"].add(
                f"MONDO:{obj.rsplit('MONDO_', 1)[1]}")
    return parents


def ancestors(curie: str, parents, depth: int = MAX_DEPTH) -> set[str]:
    seen: set[str] = set()
    frontier = {curie}
    for _ in range(depth):
        nxt: set[str] = set()
        for node in frontier:
            for par in parents.get(node, ()):
                if par not in seen:
                    seen.add(par)
                    nxt.add(par)
        frontier = nxt
        if not frontier:
            break
    return seen


def load_v1(kind: str, ref: str) -> list[dict]:
    d = pd.read_excel(_from_git(V1_FILES[kind], ref), dtype=str).fillna("")
    return [{"drug": r["final normalized drug label"],
             "drug_id": r["final normalized drug id"],
             "dis": r["final normalized disease label"],
             "dis_id": r["final normalized disease id"]}
            for _, r in d.iterrows()]


def load_now(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text()) if path.exists() else {}
    return [{"drug": a.get("drug_label") or "", "drug_id": a.get("drug_id") or "",
             "dis": a.get("disease_label") or "", "dis_id": a.get("disease_id") or "",
             "tier": a.get("reliability") or ""}
            for a in (data.get("associations") or [])]


#: v1 packs several ingredient names into one cell, variously quoted and bracketed.
_INGREDIENT_SPLIT = re.compile(r"[;,|\[\]'\"]+")


def load_moieties(path: Path) -> dict[str, set[str]]:
    """Normalised v1 drug name -> the normalised names of its ingredients.

    Read from v1's own drug list, which `just compare-release` downloads, so the product
    decomposition is v1's rather than one we invent for it. Missing file is not fatal: the
    class is then simply not counted.
    """
    if not Path(path).exists():
        return {}
    frame = pd.read_csv(path, dtype=str).fillna("")
    out: dict[str, set[str]] = collections.defaultdict(set)
    for _, row in frame.iterrows():
        name = norm(row.get("curie_label", ""))
        if not name:
            continue
        for col in ("combination_therapy_ingredients", "source_ingredients"):
            parts = [p.strip() for p in _INGREDIENT_SPLIT.split(str(row.get(col, "")))
                     if p.strip()]
            if parts:
                out[name] |= {norm(p) for p in parts}
                break
        out[name].discard(name)
        out[name].discard("")
    return {k: v for k, v in out.items() if v}


def _moiety_holds_it(drug: str, dis_id: str, dis_name: str, by_drug_ids, by_drug_names,
                     terms, moieties: dict[str, set[str]] | None) -> bool:
    """Does some moiety of this v1 product carry the same disease?

    Only an exact or equivalent disease match counts. Allowing the hierarchy here would
    stack two approximations — a product standing for its ingredient *and* a disease
    standing for its parent — and a bucket that loose stops being evidence of anything.
    """
    if not moieties:
        return False
    for moiety in moieties.get(drug, ()):
        ids = by_drug_ids.get(moiety, set())
        if dis_id in ids or dis_name in by_drug_names.get(moiety, set()):
            return True
        if terms is not None and terms.any_same_condition(dis_id, ids):
            return True
    return False


def classify(v1: list[dict], now: list[dict], parents, terms=None,
             moieties: dict[str, set[str]] | None = None
             ) -> tuple[collections.Counter, list]:
    """Bucket every v1 pair.

    ``terms`` is an optional :class:`~scripts.term_index.TermIndex`. Without it the
    cross-vocabulary class is simply not counted, and the result is the pessimistic join —
    the right behaviour for a gate whose ontology cache may be absent, as long as it is not
    reported as the whole story.

    ``moieties`` maps a normalised v1 drug name to the normalised names of the substances it
    is made of. v1 minted rows for combination *products* ('dapagliflozin / saxagliptin Oral
    Product', 'Orkambi') where the pipeline resolves to active moieties, so a pair on such a
    product matches no drug of ours by name and lands in `drug_absent` even when we assert
    the same disease for every one of its ingredients.
    """
    now_ids = {(r["drug_id"], r["dis_id"]) for r in now}
    now_names = {(norm(r["drug"]), norm(r["dis"])) for r in now}
    by_drug_ids: dict[str, set[str]] = collections.defaultdict(set)
    by_drug_names: dict[str, set[str]] = collections.defaultdict(set)
    for r in now:
        by_drug_ids[norm(r["drug"])].add(r["dis_id"])
        by_drug_names[norm(r["drug"])].add(norm(r["dis"]))

    counts: collections.Counter = collections.Counter()
    examples: list[tuple[str, str, str]] = []
    for r in v1:
        dn, zid, zn = norm(r["drug"]), r["dis_id"], norm(r["dis"])
        if (r["drug_id"], zid) in now_ids:
            counts["exact"] += 1
            continue
        if (dn, zn) in now_names:
            counts["requalified"] += 1
            continue
        mine_ids, mine_names = by_drug_ids.get(dn, set()), by_drug_names.get(dn, set())
        if not mine_ids and not mine_names:
            if _moiety_holds_it(dn, zid, zn, by_drug_ids, by_drug_names, terms, moieties):
                counts["moiety"] += 1
            else:
                counts["drug_absent"] += 1
            continue
        # Same condition, different vocabulary. Tested before the hierarchy: v1's list is
        # MONDO/UMLS/HP/EFO/NCIT and ours is MONDO/UMLS/HP, so a pair that differs only by
        # vocabulary is the same term twice, not a specificity difference, and the other
        # order files it as the weaker result.
        if terms is not None and terms.any_same_condition(zid, mine_ids):
            counts["equivalent"] += 1
            continue
        if ancestors(zid, parents) & mine_ids:
            counts["ancestor"] += 1
        elif any(zid in ancestors(m, parents) for m in list(mine_ids)[:80]):
            counts["descendant"] += 1
        elif any(zn and len(x) > 4 and (zn in x or x in zn) for x in mine_names):
            counts["wording"] += 1
            if len(examples) < 6:
                examples.append(("wording", r["drug"], r["dis"]))
        else:
            counts["absent"] += 1
    return counts, examples


LABELS = {
    "exact": "exact — same drug id and disease id",
    "requalified": "re-qualified — same pair, at least one different id",
    "equivalent": "same condition in another vocabulary (xref or exact synonym)",
    "ancestor": "we hold an ANCESTOR (v1 downfilled a subtype — not a loss, §5.7)",
    "descendant": "we hold a DESCENDANT (we are more specific — not a loss)",
    "moiety": "v1 named a product; we assert it for that product's moieties",
    "wording": "same disease, different wording or granularity",
    "absent": "genuinely not asserted",
    "drug_absent": "nothing asserted for that drug at all",
}
#: Classes that mean the two releases agree about this drug and disease, even though a
#: strict join does not match them.
RELATED = ("equivalent", "moiety", "ancestor", "descendant", "wording")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ref", default="main", help="git ref holding v1's pair lists")
    ap.add_argument("--products", default="products", type=Path)
    ap.add_argument("--v1-drugs", type=Path,
                    default=Path("tmp/old_release/drug_list_flexible.csv"),
                    help="v1's drug list, for its own product decomposition")
    args = ap.parse_args()

    parents = mondo_parents()
    terms = load_terms()
    moieties = load_moieties(args.v1_drugs)
    if not moieties:
        print(f"no {args.v1_drugs}: pairs on a v1 combination product will count as "
              "'nothing asserted for that drug'\n")
    if terms is None:
        print("no ontology cache: the cross-vocabulary class will not be counted, so the "
              "numbers below are the pessimistic join\n")
    # Which Mondo: the ancestor/descendant classes below are only comparable between runs
    # if the hierarchy is, and the pin (#94) is what makes that checkable.
    from medic.grounding.lexical.sources import pinned_ontologies, release_in_file
    print(f"Mondo subclass edges: {sum(len(v) for v in parents.values()):,} "
          f"(release {release_in_file(MONDO) or 'unknown'}, "
          f"pinned {pinned_ontologies()['mondo'].version})\n")

    for kind, fname in (("indication", "indication_list.yaml"),
                        ("contraindication", "contraindication_list.yaml")):
        v1 = load_v1(kind, args.ref)
        now = load_now(args.products / fname)
        counts, examples = classify(v1, now, parents, terms, moieties)
        strict = counts["exact"] + counts["requalified"]
        related = sum(counts[k] for k in RELATED)

        print(f"=== {kind}s: v1 {len(v1):,} | now {len(now):,} ===")
        for key in ("exact", "requalified", *RELATED, "absent", "drug_absent"):
            if counts[key]:
                print(f"  {counts[key]:6,}  ({100*counts[key]/len(v1):4.1f}%)  {LABELS[key]}")
        print(f"  {'-'*58}")
        print(f"  strict retention        {strict:6,}/{len(v1):,}"
              f"  ({100*strict/len(v1):.1f}%)")
        print(f"  hierarchy-aware         {strict+related:6,}/{len(v1):,}"
              f"  ({100*(strict+related)/len(v1):.1f}%)")
        if examples:
            print("  wording examples:")
            for _k, drug, dis in examples[:4]:
                print(f"     {drug[:26]:28s} -> {dis[:34]}")
        print()

    print("A strict join answers 'can a consumer look this exact pair up'. The "
          "hierarchy-aware\nnumber answers 'do the two releases agree about this drug and "
          "disease'. Quoting only\nthe first overstates the regression by 16.5 points on "
          "indications and 13.6 on\ncontraindications.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
