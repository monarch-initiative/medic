"""Claims that are the prompt's worked example rather than the label's content.

Found by reading the rows behind the gold standard's "model omitted it" bucket. 17 of the
8,610 cached contraindication answers reproduce the prompt's example output verbatim —
`angioedema` and `NSAID-induced asthma` — and on the intermediate that is 102 rows, 60 of
which have the verbatim nowhere in their own section text. Fabricated contraindications on
aliskiren, irbesartan, losartan, valsartan, sildenafil and five more drugs.

Nothing downstream caught it. `locatable_anchor` knows about "the hallucinated-quote case"
and deliberately falls back from an unfindable verbatim to the name, because its job is
deciding whether polarity can be evaluated, not whether the claim is supported at all.

The guard is narrow on purpose, and the tests below are mostly about what it must *not*
drop: 42 of those 102 rows are real, because plenty of ACE-inhibitor labels do contraindicate
a history of angioedema.
"""

from __future__ import annotations

from medic.ingest.dailymed.__main__ import Claim
from medic.validation.extraction_fidelity import (
    PROMPT_EXAMPLE_RECORDS,
    drop_copied_prompt_examples,
)

IRBESARTAN = ("4 CONTRAINDICATIONS Irbesartan tablets are contraindicated in patients "
              "who are hypersensitive to any component of this product. Do not "
              "coadminister aliskiren with irbesartan in patients with diabetes.")

REAL_ANGIOEDEMA = ("4 CONTRAINDICATIONS Contraindicated in patients with a history of "
                   "angioedema related to previous ACE inhibitor treatment.")


def _claim(target, verbatim):
    return Claim(target=target, target_verbatim=verbatim)


def test_the_example_pair_is_dropped_when_the_label_does_not_say_it():
    kept, dropped = drop_copied_prompt_examples(
        [_claim("angioedema", "a history of angioedema")], IRBESARTAN)
    assert kept == []
    assert [c.target for c in dropped] == ["angioedema"]


def test_the_second_example_record_is_dropped_too():
    kept, dropped = drop_copied_prompt_examples(
        [_claim("NSAID-induced asthma", "Asthma after taking aspirin or other NSAIDs")],
        IRBESARTAN)
    assert [c.target for c in dropped] == ["NSAID-induced asthma"]


def test_the_same_pair_is_kept_when_the_label_really_says_it():
    """The load-bearing case. 42 of the 102 matching rows are genuine; a guard keyed on
    the pair alone would throw away real contraindications from every ACE-inhibitor
    label."""
    kept, dropped = drop_copied_prompt_examples(
        [_claim("angioedema", "a history of angioedema")], REAL_ANGIOEDEMA)
    assert [c.target for c in kept] == ["angioedema"]
    assert dropped == []


def test_an_ordinary_claim_is_untouched_even_if_unfindable():
    """Only the example records are candidates. A legitimate canonicalisation —
    'neutrophil counts of <1,000 cells/mm3' -> severe neutropenia — is 231 further rows
    whose verbatim is also unfindable, and dropping those would cost real claims."""
    claim = _claim("severe neutropenia", "baseline neutrophil counts of <1,000 cells/mm3")
    kept, dropped = drop_copied_prompt_examples([claim], IRBESARTAN)
    assert [c.target for c in kept] == ["severe neutropenia"]
    assert dropped == []


def test_the_match_ignores_case_whitespace_and_typographic_punctuation():
    """The verbatim arrives as the model spelled it; a curly apostrophe or a doubled space
    must not let a copied example through."""
    kept, dropped = drop_copied_prompt_examples(
        [_claim("Angioedema", "A  history   of angioedema")], IRBESARTAN)
    assert dropped and kept == []


def test_a_claim_with_no_verbatim_is_never_dropped():
    """A cached answer predating #64 has no verbatim, so there is nothing to check it
    against and silence is not evidence."""
    kept, dropped = drop_copied_prompt_examples([_claim("angioedema", "")], IRBESARTAN)
    assert [c.target for c in kept] == ["angioedema"]
    assert dropped == []


def test_the_indication_side_has_its_own_example():
    """The indication prompt's example is `osteoarthritis :: osteoarthritis`, which is a
    common enough claim that only the text check distinguishes a copy from a real one."""
    kept, dropped = drop_copied_prompt_examples(
        [_claim("osteoarthritis", "osteoarthritis")],
        "1 INDICATIONS AND USAGE Indicated for the treatment of plaque psoriasis.",
        kind="indication")
    assert [c.target for c in dropped] == ["osteoarthritis"]
    kept2, dropped2 = drop_copied_prompt_examples(
        [_claim("osteoarthritis", "osteoarthritis")],
        "1 INDICATIONS AND USAGE For the relief of signs and symptoms of osteoarthritis.",
        kind="indication")
    assert [c.target for c in kept2] == ["osteoarthritis"] and dropped2 == []


def test_an_unknown_kind_drops_nothing():
    claims = [_claim("angioedema", "a history of angioedema")]
    kept, dropped = drop_copied_prompt_examples(claims, IRBESARTAN, kind="research")
    assert kept == claims and dropped == []


def test_both_prompts_are_covered():
    """If a prompt's example changes, this is the reminder that the set has to change with
    it — the guard is only as good as the records it knows about."""
    assert set(PROMPT_EXAMPLE_RECORDS) == {"contraindication", "indication"}
    for records in PROMPT_EXAMPLE_RECORDS.values():
        assert records, "an empty example set silently disables the guard"
