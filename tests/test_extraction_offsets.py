"""`char_start`/`char_end` locate the text the extraction read (#63 review, #64 follow-up).

The offsets were computed as `span["text"].find(step["output_value"])` — a literal search
for the *canonical* name. The extraction prompt asks for canonicalisation, so that name is
frequently absent from the span, the find returns -1, and no offsets are recorded. Those
are exactly the rows #64 set out to fix: the KGX exporter then drops
`object_location_in_text` rather than ship a wrong one.

The offsets should delimit the substring the extraction actually read, which is the
verbatim quote, not the canonical label it was normalised to. `output_value` stays the
canonical name — that is the step's output — while the offsets point at the source text.
"""

from __future__ import annotations

from medic.provenance_build import _extraction_step

SPAN = {"role": "SECTION_TEXT",
        "text": "PRODUCT is indicated for reducing the risk of nonfatal MI in adults.",
        "document": "DailyMed:x"}


def _step(output, verbatim=None):
    extraction = {"supporting_quote": SPAN["text"], "output_value": output,
                  "method": "LLM", "confidence": 0.5, "span_index": 0, "flags": []}
    if verbatim is not None:
        extraction["verbatim"] = verbatim
    return _extraction_step(extraction, original_literal=output, spans=[SPAN])


def test_a_verbatim_quote_yields_offsets_for_a_canonicalised_name():
    """"myocardial infarction" is not in the span; "MI" is."""
    step = _step("myocardial infarction", verbatim="MI")
    assert "char_start" in step and "char_end" in step
    assert SPAN["text"][step["char_start"]:step["char_end"]] == "MI"


def test_without_a_verbatim_a_canonicalised_name_still_records_no_offsets():
    """Pins the pre-fix behaviour: no quote, nothing findable, no offsets invented."""
    step = _step("myocardial infarction")
    assert "char_start" not in step


def test_a_name_present_verbatim_in_the_span_is_unchanged():
    step = _step("nonfatal MI")
    assert SPAN["text"][step["char_start"]:step["char_end"]] == "nonfatal MI"


def test_a_hallucinated_quote_records_no_offsets_rather_than_wrong_ones():
    """An offset is a verifiable claim about the document. Better absent than fabricated."""
    step = _step("myocardial infarction", verbatim="sugar sickness")
    assert "char_start" not in step


def test_the_output_value_is_still_the_canonical_name():
    """The offsets move to the quote; the step's output does not. The chain stays
    one-in-one-out with the canonical id downstream (I-8)."""
    step = _step("myocardial infarction", verbatim="MI")
    assert step["output_value"] == "myocardial infarction"
