"""Licence declarations for the git-tracked stores under ``mappings/``.

Every store in ``mappings/`` carries some amount of verbatim upstream content, so every one
of them owes a consumer a licence statement. Three of the five carried none: the two
normalization stores and the Babelon translation table — and the Babelon table is the file
with the *most* to say about terms, because its ``source_value`` column is verbatim Russian
GRLS and Chinese CDE register content (issue #48).

The terms come from ``conf/release_assets.yaml`` so a store header cannot drift from what the
release actually declares, and a missing or unreadable manifest never fails a build.

Two formats, because the two file types differ in what they can carry:

* **SSSOM TSV** takes ``#``-prefixed front-matter, which ``sssom-py`` parses.
* **Babelon TSV cannot.** ``babelon.utils.parse_babelon`` is a bare
  ``pd.read_csv(sep="\\t")`` with no ``comment=`` handling, so a ``#`` line is read as the
  header row and the file fails to parse ("Expected 1 fields in line 3, saw 6"). Babelon 0.3.6
  also defines no external-metadata convention. So the translation table keeps a clean TSV and
  its terms travel in a **sidecar** ``*.meta.yaml`` instead — which `parse_babelon` never
  reads, so the round-trip through ``babelon.translate.translate_profile`` still works.
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_LICENSE = "https://creativecommons.org/licenses/by/4.0/"
DEFAULT_ASSERTIONS = "https://creativecommons.org/publicdomain/zero/1.0/"


def license_terms() -> tuple[str, str, str]:
    """``(license_url, assertions_url, passthrough)`` from the release manifest."""
    from medic import release_assets

    license_url, assertions_url, passthrough = DEFAULT_LICENSE, DEFAULT_ASSERTIONS, ""
    try:
        lic = release_assets.load().license
        if lic:
            license_url = lic.medic_contribution or license_url
            assertions_url = lic.medic_assertions_offered_as or assertions_url
            passthrough = lic.passthrough
    except (OSError, ValueError):  # never fail a build over the manifest
        pass
    return license_url, assertions_url, passthrough


def sssom_license_lines(why_not_cc0: str) -> list[str]:
    """``# license:`` / ``# comment:`` front-matter for an SSSOM store.

    ``why_not_cc0`` names the columns that carry upstream content, which is what stops the set
    being declared CC0 outright: MeDIC cannot waive rights it never held, and a file-level CC0
    would tell a consumer attribution is optional when EMA and PMDA both require it.
    """
    license_url, assertions_url, passthrough = license_terms()
    comment = (
        f"The mapping decisions in this file are MeDIC's own contribution and are offered as "
        f"{assertions_url}. The set is declared {license_url} because {why_not_cc0} "
        f"{passthrough}"
    ).strip()
    return [f"# license: {license_url}\n", f"# comment: {comment}\n"]


def babelon_sidecar_path(tsv_path: str | Path) -> Path:
    """The metadata file that carries a Babelon table's terms."""
    p = Path(tsv_path)
    return p.with_name(p.name.replace(".babelon.tsv", "") + ".babelon.meta.yaml")


def write_babelon_sidecar(tsv_path: str | Path, *, source_languages: list[str]) -> Path:
    """Write the licence sidecar for a Babelon translation table.

    Says plainly what the subject strings are. ``mappings/`` is blanket-declared CC BY 4.0,
    but that is a claim about *MeDIC's contribution* — the translations — and not about the
    Russian and Chinese register strings in ``source_value``, which are reproduced verbatim
    from sources that grant no open licence at all. Conflating the two is the specific thing
    this file exists to stop.
    """
    import yaml

    license_url, assertions_url, passthrough = license_terms()
    langs = ", ".join(sorted(source_languages)) or "non-English"
    doc = {
        "translation_set_id": "https://w3id.org/monarch-initiative/medic/mappings/drug_translation",
        "title": "MeDIC drug-name translations",
        "license": license_url,
        "source_language": sorted(source_languages),
        "comment": (
            f"The translations in this file are MeDIC's own contribution (DeepL machine output, "
            f"post-edited where a curator has reviewed it) and are offered as {assertions_url}. "
            f"The set is declared {license_url} because `source_value` reproduces verbatim "
            f"{langs} strings from the Russian GRLS and Chinese CDE registers. Those registers "
            f"declare no open licence: MeDIC republishes derived per-drug records from them as a "
            f"recorded decision (see LICENSING.md), and cannot license their content onward. "
            f"Treat `source_value` as upstream content and `translation_value` as MeDIC's. "
            f"{passthrough}"
        ).strip(),
        "note": (
            "Terms live here rather than in the TSV because babelon's own reader "
            "(babelon.utils.parse_babelon) is a bare pandas read_csv with no comment handling, "
            "so a '#' front-matter line makes the table unparseable. Keep the TSV clean."
        ),
    }
    out = babelon_sidecar_path(tsv_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100))
    return out
