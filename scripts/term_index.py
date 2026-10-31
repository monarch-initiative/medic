"""Telling "a different id" from "a different condition", for the QC comparisons.

Every comparison in this repo joins two sets of grounded disease ids — ours against v1.0.0,
ours against the combination curation pilot — and a plain id join counts a claim as missing
whenever the two sides named the same condition in different vocabularies. Both sides are
mixed: v1's indication list is MONDO 8,720 / UMLS 1,310 / HP 812 / EFO 113 / NCIT 101, and
our edge objects are MONDO 54,667 / UMLS 25,110 / HP 15,393. So the join is cross-vocabulary
by construction, and reading a vocabulary difference as a recall loss has been this
project's most repeated measurement error.

The evidence to resolve it is already on disk in the pinned ontology releases:

* **xrefs** — Mondo alone carries 32,514 UMLS and 574 HP cross-references.
* **exact synonyms** — MONDO:0000004 'adrenocortical insufficiency' lists `adrenal
  insufficiency`, which is HP:0000846's primary label. Neither carries an xref to the other.

Only `hasExactSynonym` and primary labels count. Broad and related synonyms collide
unrelated terms, which is the failure the grounding cascade's own predicate rules exist to
avoid — and a scorer that over-matches turns a recall gap into a flattering number, which is
worse than the pessimistic one it replaces.
"""

from __future__ import annotations

import collections
import dataclasses
import json
import re
from pathlib import Path

ONTOLOGY_DIR = Path("cache/ontologies")

#: The obographs builds to read, and the CURIE prefix each one mints.
SOURCES = (("MONDO", "mondo.json"), ("HP", "hp.json"))

#: Prefixes an xref may carry and still name a disease either side might have grounded to.
#: Deliberately a closed list: Mondo xrefs to dozens of vocabularies, most of which neither
#: release uses, and admitting them all would add collisions for no reachable match.
XREF_PREFIXES = ("MONDO:", "HP:", "UMLS:", "EFO:", "NCIT:", "DOID:", "OMIM:")

#: How far up the hierarchy an "ancestor" may sit and still mean the two sides agreed about
#: the same condition. Mondo is deep; beyond a handful of steps a shared ancestor stops
#: meaning anything.
MAX_DEPTH = 6


def norm(s: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


@dataclasses.dataclass(frozen=True)
class TermIndex:
    """Three plain dicts rather than an ontology object, so a test can state one fact."""

    #: curie -> normalised primary label and `hasExactSynonym` values
    strings: dict[str, set[str]]
    #: curie -> curies it is cross-referenced with, recorded in both directions
    xrefs: dict[str, set[str]]
    #: child curie -> direct parent curies
    parents: dict[str, set[str]]

    def same_condition(self, a: str, b: str) -> bool:
        if a == b:
            return True
        if b in self.xrefs.get(a, ()) or a in self.xrefs.get(b, ()):
            return True
        sa, sb = self.strings.get(a), self.strings.get(b)
        return bool(sa and sb and sa & sb)

    def any_same_condition(self, curie: str, others) -> str:
        """The first of ``others`` naming the same condition as ``curie``, or ``""``."""
        for other in sorted(others):
            if self.same_condition(curie, other):
                return other
        return ""

    def ancestors(self, curie: str, depth: int = MAX_DEPTH) -> set[str]:
        seen: set[str] = set()
        frontier = {curie}
        for _ in range(depth):
            nxt: set[str] = set()
            for node in frontier:
                for parent in self.parents.get(node, ()):
                    if parent not in seen:
                        seen.add(parent)
                        nxt.add(parent)
            frontier = nxt
            if not frontier:
                break
        return seen


def load_terms(ontology_dir: Path = ONTOLOGY_DIR) -> TermIndex | None:
    """Build a :class:`TermIndex` from the cached obographs releases, or ``None``.

    ``None`` rather than an exit: the cache is ~130MB and untracked, and the callers are
    gates. Without it a strict id join is still a real number — it is just the pessimistic
    one, and the caller says so rather than reporting it as the whole story.
    """
    strings: dict[str, set[str]] = collections.defaultdict(set)
    xrefs: dict[str, set[str]] = collections.defaultdict(set)
    parents: dict[str, set[str]] = collections.defaultdict(set)
    found = False
    for prefix, filename in SOURCES:
        path = Path(ontology_dir) / filename
        if not path.exists():
            continue
        found = True
        graph = json.loads(path.read_text())["graphs"][0]
        token = f"{prefix}_"
        for node in graph.get("nodes", ()):
            raw = str(node.get("id", ""))
            if token not in raw:
                continue
            curie = f"{prefix}:{raw.rsplit(token, 1)[1]}"
            meta = node.get("meta") or {}
            if node.get("lbl"):
                strings[curie].add(norm(node["lbl"]))
            for syn in meta.get("synonyms") or ():
                if syn.get("pred") == "hasExactSynonym" and syn.get("val"):
                    strings[curie].add(norm(syn["val"]))
            for xref in meta.get("xrefs") or ():
                val = str(xref.get("val") or "")
                if val.startswith(XREF_PREFIXES):
                    xrefs[curie].add(val)
                    xrefs[val].add(curie)
        for edge in graph.get("edges", ()):
            if edge.get("pred") != "is_a":
                continue
            sub, obj = str(edge.get("sub", "")), str(edge.get("obj", ""))
            if token in sub and token in obj:
                parents[f"{prefix}:{sub.rsplit(token, 1)[1]}"].add(
                    f"{prefix}:{obj.rsplit(token, 1)[1]}")
    if not found:
        return None
    return TermIndex(strings=dict(strings), xrefs=dict(xrefs), parents=dict(parents))
