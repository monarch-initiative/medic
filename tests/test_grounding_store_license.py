"""The in-repo SSSOM decision stores carry the same licence position as the export.

`mappings/*_grounding.sssom.tsv` declared a blanket CC0, but `subject_label` and
`match_string` reproduce verbatim source strings (e.g. `"Golden Star" Balm`) that stay under
the source terms. Same defect as the export header, same fix.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from medic.grounding.store import LiteralMappingStore

#: The stores as actually committed. Tests that only ever inspect a freshly written temp file
#: cannot see a stale artefact — which is exactly what happened: the writer was changed to
#: CC BY, the committed stores kept their CC0 header for weeks, and this suite stayed green
#: the whole time. Every assertion about the licence now runs against both.
#:
#: **Discovered by glob, not enumerated.** This list used to name the two `*_grounding` stores
#: literally, so the two `*_normalization` stores shipped with no licence header at all and the
#: suite could not see it — a fix written specifically to close the licence gap missed half the
#: files it applied to (#48). A hardcoded list of the files a policy covers will always drift
#: from the files that exist; a new store now cannot be added without a licence decision.
COMMITTED_STORES = sorted(Path("mappings").glob("*.sssom.tsv"))

#: Babelon is deliberately not in the list above. `babelon.utils.parse_babelon` is a bare
#: `pd.read_csv(sep="\t")` with no comment handling, so a `#` header makes the table
#: unparseable; its terms live in a sidecar instead.
BABELON_STORES = sorted(Path("mappings").glob("*.babelon.tsv"))


def _header(tmp_path):
    store = LiteralMappingStore(str(tmp_path / "s.sssom.tsv"), entity_type="drugs")
    store.save()
    return (tmp_path / "s.sssom.tsv").read_text()


def _committed_header(path: Path) -> str:
    lines = []
    with open(path) as fh:
        for line in fh:
            if not line.startswith("#"):
                break
            lines.append(line)
    return "".join(lines)


@pytest.mark.parametrize("path", COMMITTED_STORES, ids=lambda p: p.name)
def test_committed_store_declares_cc_by_not_cc0(path):
    """The artefact, not the writer. CC0 would waive rights over verbatim source strings."""
    header = _committed_header(path)
    assert "# license: https://creativecommons.org/licenses/by/4.0/" in header
    assert "publicdomain/zero" not in header.split("# comment:")[0]


def _expected_header_for(path: Path) -> str:
    """Each store is pinned to *its own* writer, not to one canonical header.

    The two kinds say different things about why they are not CC0 — grounding reproduces
    verbatim source strings, normalization reproduces Mondo/ChEBI labels — so comparing every
    store against the grounding header would either fail or force the two to lie alike.
    """
    if "_normalization" in path.name:
        from medic.normalization.store import _license_header
    else:
        from medic.grounding.store import _license_header
    return "".join(_license_header())


@pytest.mark.parametrize("path", COMMITTED_STORES, ids=lambda p: p.name)
def test_committed_store_matches_what_the_writer_would_emit(path):
    """Pins writer and artefact together, so changing one without regenerating the other fails."""
    assert _expected_header_for(path) in _committed_header(path)


def test_every_committed_sssom_store_is_covered():
    """The glob must actually be finding files — an empty parametrize passes vacuously."""
    names = {p.name for p in COMMITTED_STORES}
    assert len(names) >= 4, f"expected all four SSSOM stores, found {sorted(names)}"


@pytest.mark.parametrize("path", BABELON_STORES, ids=lambda p: p.name)
def test_babelon_table_declares_its_terms_in_a_sidecar(path):
    """It cannot carry a `#` header, so the terms must exist somewhere a consumer can read."""
    import yaml

    from medic.mapping_headers import babelon_sidecar_path

    sidecar = babelon_sidecar_path(path)
    assert sidecar.exists(), f"{path.name} has no licence sidecar at {sidecar.name}"
    doc = yaml.safe_load(sidecar.read_text())
    assert doc.get("license", "").startswith("http"), "sidecar declares no licence"
    # The one thing only this file has to say: what its subject strings actually are.
    assert "source_value" in doc.get("comment", ""), "sidecar does not describe source_value"


@pytest.mark.parametrize("path", BABELON_STORES, ids=lambda p: p.name)
def test_babelon_table_has_no_hash_header(path):
    """A `#` line here would break `babelon.utils.parse_babelon`, which reads it as the header."""
    first = path.read_text().splitlines()[0]
    assert not first.startswith("#"), "babelon TSV must stay clean; terms go in the sidecar"


def test_store_declares_cc_by_not_cc0(tmp_path):
    assert "# license: https://creativecommons.org/licenses/by/4.0/" in _header(tmp_path)


def test_store_records_the_verbatim_string_carve_out(tmp_path):
    header = _header(tmp_path)
    assert "subject_label" in header
    assert "remains in force" in header


def test_store_header_lines_are_comments(tmp_path):
    for line in _header(tmp_path).splitlines():
        if line.startswith("subject_type"):
            break
        assert line.startswith("#"), line
