"""Span boundaries follow the SPL's own element boundaries (#65).

An SPL indications section carries the Full Prescribing Information body and the
Highlights summary as two sibling `<text>` elements. `_flatten_section_text` joined them
with a space, and `split_dailymed_section` then tried to rebuild the boundary with a
regex on the concatenation — so a `Limitations of Use` marker in the first element put
the *second* element's positive indication text inside a LIMITATION_STATEMENT span.

Measured over the 306 SPL labels carrying the marker, that affected 203 of them. Keeping
the element boundaries takes it to 9. The splitter was never really wrong; it was
reconstructing structure thrown away one function earlier.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from medic.ingest.dailymed.__main__ import (
    LOINC_INDICATIONS,
    _extract_section_chunks_from_root,
    _flatten_section_text,
    _row_from_spl_root,
    _section_chunks,
)
from medic.spans import spans_for_source

# The shape that produces the defect: FPI body, then the Highlights summary, which
# re-asserts the indication *after* the limitation sentence.
SPL = """<document xmlns="urn:hl7-org:v3">
  <setId root="fd9f9458"/>
  <component><structuredBody><component><section>
    <code code="34067-9"/>
    <title>1 INDICATIONS AND USAGE</title>
    <text>REZVOGLAR is indicated to improve glycemic control in patients with diabetes
    mellitus. Limitations of Use REZVOGLAR is not recommended for the treatment of
    diabetic ketoacidosis.</text>
    <text>REZVOGLAR is a long-acting human insulin analog indicated to improve glycemic
    control in adult and pediatric patients with diabetes mellitus. ( 1 )</text>
  </section></component></structuredBody></component>
  <component><structuredBody><component><section>
    <code code="34070-3"/>
    <text>Contraindicated in hypersensitivity to insulin glargine.</text>
  </section></component></structuredBody></component>
</document>"""


def _root():
    return ET.fromstring(SPL)


# ---------------------------------------------------------------------------
# The chunks themselves
# ---------------------------------------------------------------------------
def test_section_chunks_keeps_one_entry_per_element():
    section = next(s for s in _root().iter("{urn:hl7-org:v3}section")
                   if (c := s.find("{urn:hl7-org:v3}code")) is not None
                   and c.get("code") == LOINC_INDICATIONS)
    chunks = _section_chunks(section)
    assert len(chunks) == 3  # title + two text elements
    assert chunks[0] == "1 INDICATIONS AND USAGE"
    assert "Limitations of Use" in chunks[1]
    assert "long-acting human insulin analog" in chunks[2]


def test_flatten_still_returns_the_joined_string():
    """The flat form stays — the LLM should still be shown the whole section."""
    section = next(s for s in _root().iter("{urn:hl7-org:v3}section")
                   if (c := s.find("{urn:hl7-org:v3}code")) is not None
                   and c.get("code") == LOINC_INDICATIONS)
    assert _flatten_section_text(section) == " ".join(_section_chunks(section))


def test_chunks_are_extracted_by_loinc_code():
    chunks = _extract_section_chunks_from_root(_root(), LOINC_INDICATIONS)
    assert len(chunks) == 3
    assert _extract_section_chunks_from_root(_root(), "99999-9") == []


def test_a_mined_row_carries_the_parts_alongside_the_flat_text():
    root = _root()
    # _row_from_spl_root needs an ingredient to return a row at all.
    moiety = ET.SubElement(root, "{urn:hl7-org:v3}activeMoiety")
    name = ET.SubElement(moiety, "{urn:hl7-org:v3}name")
    name.text = "INSULIN GLARGINE"
    row = _row_from_spl_root(root)
    assert row is not None
    assert row["indications_text"] == " ".join(row["indications_text_parts"])
    assert len(row["indications_text_parts"]) == 3
    assert len(row["contraindications_text_parts"]) == 1


# ---------------------------------------------------------------------------
# What the boundaries buy: the defect itself
# ---------------------------------------------------------------------------
def _roles_and_limitation(**kw):
    spans = spans_for_source("DAILYMED", kw.pop("text"), document="d",
                             section_code="34067-9", **kw)
    limitation = " ".join(s["text"] for s in spans
                          if s["role"] == "LIMITATION_STATEMENT")
    return [s["role"] for s in spans], limitation


def test_without_parts_the_highlights_text_lands_in_the_limitation_span():
    """The defect, pinned so the fix is visibly a fix and not a no-op."""
    chunks = _extract_section_chunks_from_root(_root(), LOINC_INDICATIONS)
    _roles, limitation = _roles_and_limitation(text=" ".join(chunks))
    assert "long-acting human insulin analog" in limitation


def test_with_parts_the_highlights_text_stays_section_text():
    chunks = _extract_section_chunks_from_root(_root(), LOINC_INDICATIONS)
    _roles, limitation = _roles_and_limitation(text=" ".join(chunks), parts=chunks)
    assert "long-acting human insulin analog" not in limitation
    assert "diabetic ketoacidosis" in limitation  # the real limitation survives


def test_parts_splitting_is_still_lossless():
    """I-7: joining the span texts reproduces the input, so no source text is dropped."""
    chunks = _extract_section_chunks_from_root(_root(), LOINC_INDICATIONS)
    spans = spans_for_source("DAILYMED", " ".join(chunks), document="d",
                             section_code="34067-9", parts=chunks)
    assert " ".join(s["text"] for s in spans) == " ".join(
        " ".join(c.split()) for c in chunks)


def test_absent_parts_behaves_exactly_as_before():
    text = ("1 INDICATIONS AND USAGE PRODUCT is indicated for migraine. "
            "Limitations of Use PRODUCT is not indicated for cluster headache.")
    without = spans_for_source("DAILYMED", text, document="d", section_code="x")
    explicit = spans_for_source("DAILYMED", text, document="d", section_code="x",
                                parts=None)
    assert [s["role"] for s in without] == [s["role"] for s in explicit]
    assert "LIMITATION_STATEMENT" in [s["role"] for s in without]


def test_a_non_dailymed_source_ignores_parts():
    spans = spans_for_source("EMA", "Indicated for anxiety", document="d",
                             section_code="", parts=["Indicated for", "anxiety"])
    assert [s["role"] for s in spans] == ["STRUCTURED_FIELD"]
