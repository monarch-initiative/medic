"""The PMDA contraindication evidence item, against the closed EvidenceItem class.

Every key this ingester writes has to be a declared attribute of `EvidenceItem`. It was
not: the path emitted `language`, and `validate-all` rejected
`products/contraindication_list.yaml` with "Additional properties are not allowed
('language' was unexpected)" on the first build that ever reached the code. Nothing caught
it earlier because contraindication extraction is opt-in behind `--extract-contras`, which
`build-all` does not call — the same reason EMA's path still read `Claim.name`.

A flag nothing exercises is a flag that rots, so this reads the schema rather than trusting
a hand-maintained list.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "src/medic/schema/evidence.yaml"
PMDA = ROOT / "src/medic/ingest/pmda/__main__.py"


def declared_evidence_keys() -> set[str]:
    doc = yaml.safe_load(SCHEMA.read_text()) or {}
    cls = (doc.get("classes") or {}).get("EvidenceItem") or {}
    keys = set(cls.get("attributes") or {})
    keys |= set(cls.get("slots") or [])
    return keys


def _evidence_literal_keys(source: str) -> set[str]:
    """Keys of every dict literal in the module that looks like an evidence item.

    Identified by shape rather than by variable name: a dict literal carrying both
    `source_type` and `jurisdiction` is the regulatory evidence shape.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Dict):
            continue
        keys = {k.value for k in node.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        if {"source_type", "jurisdiction"} <= keys:
            found |= keys
    return found


def test_the_schema_declares_the_fields_we_expect():
    """Guard the guard: if this ever returns an empty set the test below passes vacuously."""
    declared = declared_evidence_keys()
    assert {"snippet", "reference", "confidence", "jurisdiction"} <= declared
    assert "language" not in declared


def test_evidence_item_is_the_shape_the_schema_allows():
    emitted = _evidence_literal_keys(PMDA.read_text())
    assert emitted, "found no evidence-shaped dict literal — has the shape changed?"
    undeclared = emitted - declared_evidence_keys()
    assert not undeclared, (
        f"PMDA writes keys EvidenceItem does not declare: {sorted(undeclared)}. "
        "`validate-all` rejects the product file on these."
    )


@pytest.mark.parametrize("module", [
    "src/medic/ingest/ema/__main__.py",
    "src/medic/ingest/india/__main__.py",
])
def test_the_other_on_label_ingesters_are_the_same_shape(module):
    """PMDA is not special. The other opt-in paths get the same check, since the only thing
    that found the PMDA bug was running a build to completion."""
    emitted = _evidence_literal_keys((ROOT / module).read_text())
    if not emitted:
        pytest.skip(f"{module} has no evidence-shaped dict literal")
    undeclared = emitted - declared_evidence_keys()
    assert not undeclared, f"{module} writes undeclared keys: {sorted(undeclared)}"
