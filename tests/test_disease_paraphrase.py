"""The LLM condition resolver for the disease-grounding residue.

52.8% of every disease string the pipeline has extracted resolved to `sssom:NoTermFound`,
and 9,594 of those 9,696 are real clinical phrases — 'a history of bronchial asthma',
'inherited or acquired hypercoagulopathies' — that no string transform reaches. Against the
combination gold standard, grounding refusal is the largest single cause of a missed curated
claim: 123 of 234.

The tests that matter here are the guards, not the happy path. The model is asked for a
condition *name* and never an identifier, so the only ids that can enter the store are ones
MeDIC's own cascade produced from the pinned release; and an LLM asked "what condition is
this?" will answer even when the right answer is "that is a lab value".
"""

from __future__ import annotations

import pytest

from medic.enrichment.disease_paraphrase import (
    MAX_CONDITIONS,
    PARAPHRASE_CERTAINTY,
    PARAPHRASE_PREDICATE,
    _parse,
    _proposal_rows,
    looks_like_condition,
    resolve_residue,
)
from medic.grounding.store import PARAPHRASE_RULE, GroundingDecision, is_locked


class _Result:
    def __init__(self, id_, label):
        self.id = id_
        self.label = label


class _Cache:
    """Stands in for EnrichmentCache; also proves the resolver never calls out when hot."""

    def __init__(self, answers):
        self.answers = answers
        self.gets = 0

    def get(self, key):
        self.gets += 1
        return self.answers.get(key)

    def put(self, key, value):
        self.answers[key] = value

    def flush(self):
        pass


# ---------------------------------------------------------------------------
# The pre-filter: what is not worth a call
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("phrase", [
    "a history of bronchial asthma",
    "inherited or acquired hypercoagulopathies",
    "3rd degree AV block",
    "17p deletion",
])
def test_a_clinical_phrase_is_worth_asking_about(phrase):
    assert looks_like_condition(phrase)


@pytest.mark.parametrize("phrase", [
    "(no condition named)",
    "(none)",
    "(not indicated - this is a limitation stating it is NOT indicated for prevention)",
    "1000 cells/mm 3",
    "20% total body surface area)",
    "none specified",
    "",
    "x",
])
def test_commentary_and_measurements_are_not_worth_a_call(phrase):
    """These are in the real residue. Asking about them costs money and invites an invented
    answer, which is the failure mode the RxNorm resolver had to guard against too."""
    assert not looks_like_condition(phrase)


# ---------------------------------------------------------------------------
# Reading the answer
# ---------------------------------------------------------------------------
def test_none_means_none():
    assert _parse("NONE") == []
    assert _parse("none") == []


def test_a_single_name_is_taken_verbatim():
    assert _parse("asthma") == ["asthma"]


def test_several_conditions_come_back_in_order():
    assert _parse("thrombophlebitis\nthromboembolism") == [
        "thrombophlebitis", "thromboembolism"]


def test_bullets_and_dashes_are_stripped():
    assert _parse("- asthma\n* eczema") == ["asthma", "eczema"]


def test_more_than_the_cap_is_truncated():
    """A phrase naming more than three conditions is a list the extractor should have
    split, not a paraphrase."""
    answer = "\n".join(f"condition {i}" for i in range(10))
    assert len(_parse(answer)) == MAX_CONDITIONS


def test_a_none_anywhere_wins_over_names_already_read():
    """A model that hedges — 'asthma' then 'NONE' — must not have the hedge ignored."""
    assert _parse("asthma\nNONE") == []


# ---------------------------------------------------------------------------
# The proposal rows
# ---------------------------------------------------------------------------
def test_a_proposal_records_the_in_and_the_out():
    """I-8: the chain from the label's literal to the final id has to be replayable from
    the row alone, so `match_string` carries the name the model gave."""
    rows = _proposal_rows("a history of bronchial asthma",
                          [("asthma", "HP:0002099", "Asthma")])
    assert len(rows) == 1
    row = rows[0]
    assert row.subject_label == "a history of bronchial asthma"
    assert row.match_string == "asthma"
    assert row.object_id == "HP:0002099"
    assert row.subject_preprocessing == [PARAPHRASE_RULE]


def test_a_proposal_is_a_broad_match_at_low_certainty():
    """A phrase is routinely narrower than the condition it names — a history of it, a risk
    of it — so the mapping is a generalisation. closeMatch here would let it reach HIGH."""
    row = _proposal_rows("a risk of stroke", [("stroke", "MONDO:1", "stroke")])[0]
    assert row.predicate_id == PARAPHRASE_PREDICATE == "skos:broadMatch"
    assert row.confidence == PARAPHRASE_CERTAINTY < 0.9


def test_a_proposal_is_locked_so_a_regrounding_run_reads_it():
    row = _proposal_rows("x", [("asthma", "HP:0002099", "Asthma")])[0]
    assert is_locked(row)


def test_an_ordinary_lexical_row_is_not_locked():
    assert not is_locked(GroundingDecision(
        subject_label="asthma", entity_type="diseases", predicate_id="skos:exactMatch",
        object_id="HP:0002099", object_label="Asthma", object_match_field="label",
        mapping_justification="semapv:LexicalMatching"))


# ---------------------------------------------------------------------------
# The resolver end to end, with the cascade stubbed
# ---------------------------------------------------------------------------
def test_the_id_always_comes_from_the_cascade_never_from_the_model():
    """The hallucination guard. The model says 'asthma'; the id is whatever MeDIC grounds
    that to. A model answering with a CURIE has no path into the store."""
    cache = _Cache({"a history of bronchial asthma": {"conditions": ["MONDO:9999999"]}})
    seen = []

    def ground(name):
        seen.append(name)
        return [_Result("HP:0002099", "Asthma")]

    report = resolve_residue(["a history of bronchial asthma"], ground,
                             cache=cache, write_store=False)
    assert seen == ["MONDO:9999999"]        # passed through as a *string* to be grounded
    assert report["recovered"] == 1
    assert list(report["targets"]) == ["HP:0002099"]


def test_a_phrase_the_model_declines_is_not_recovered():
    cache = _Cache({"co-administration with another agent": {"conditions": []}})
    report = resolve_residue(["co-administration with another agent"], lambda n: [],
                             cache=cache, write_store=False)
    assert report["model_said_none"] == 1
    assert report["recovered"] == 0


def test_a_name_the_cascade_cannot_ground_is_not_a_proposal():
    """The model may name a real condition the pinned release has no term for. That is a
    miss, not a mapping to something approximate."""
    cache = _Cache({"some phrase": {"conditions": ["a condition with no term"]}})
    report = resolve_residue(["some phrase"], lambda n: [], cache=cache, write_store=False)
    assert report["named_but_ungroundable"] == 1
    assert report["recovered"] == 0


def test_the_prefilter_runs_before_any_call_is_made():
    cache = _Cache({})
    report = resolve_residue(["(no condition named)"], lambda n: [],
                             cache=cache, write_store=False)
    assert report["skipped_not_a_condition"] == 1
    assert report["asked"] == 0
    assert cache.gets == 0, "a pre-filtered phrase must not even reach the cache"


def test_a_conjunction_proposes_a_row_per_condition_and_is_counted():
    """The store already maps one subject to several ids — that is how a combination drug
    literal works. But splitting a conjunction turns one claim into two edges, so the
    report counts it separately rather than letting it pass unseen."""
    cache = _Cache({"Thrombophlebitis or thromboembolic disorders":
                    {"conditions": ["thrombophlebitis", "thromboembolism"]}})
    ids = {"thrombophlebitis": _Result("HP:0004418", "Thrombophlebitis"),
           "thromboembolism": _Result("HP:0001907", "Thromboembolism")}
    report = resolve_residue(["Thrombophlebitis or thromboembolic disorders"],
                             lambda n: [ids[n]], cache=cache, write_store=False)
    assert report["multi_condition"] == 1
    assert report["proposals"] == 2


def test_the_report_counts_how_often_each_target_is_proposed():
    """A single term absorbing many distinct phrases is the tell-tale of a model answering
    generically, so the concentration is reported rather than buried."""
    cache = _Cache({f"phrase {i}": {"conditions": ["asthma"]} for i in range(4)})
    report = resolve_residue([f"phrase {i}" for i in range(4)],
                             lambda n: [_Result("HP:0002099", "Asthma")],
                             cache=cache, write_store=False)
    assert report["targets"] == {"HP:0002099": 4}


def test_a_dry_run_writes_nothing():
    """`--dry-run` has to be safe to point at the real store."""
    cache = _Cache({"a history of asthma": {"conditions": ["asthma"]}})

    class _Store:
        def manual_rows(self, _):
            return []

        def record_subject(self, *a, **k):
            raise AssertionError("a dry run must not write")

        def save(self):
            raise AssertionError("a dry run must not save")

    resolve_residue(["a history of asthma"], lambda n: [_Result("HP:0002099", "Asthma")],
                    store=_Store(), cache=cache, write_store=False)


# ---------------------------------------------------------------------------
# Paid answers must reach disk
# ---------------------------------------------------------------------------
class _FlushCache(_Cache):
    def __init__(self, answers):
        super().__init__(answers)
        self.flushes = 0

    def flush(self):  # noqa: D102
        self.flushes += 1


def test_the_answer_cache_is_flushed_before_returning():
    """`cache.flush_all` runs at exit, but the registry is a `weakref.WeakSet` and this
    cache is held in a local, so it is collected the moment `resolve_residue` returns and
    is gone before the exit handler fires. A 287-call pass reported its results and wrote
    none of them. Flushing has to be explicit."""
    cache = _FlushCache({"a history of asthma": {"conditions": ["asthma"]}})
    resolve_residue(["a history of asthma"], lambda n: [_Result("HP:0002099", "Asthma")],
                    cache=cache, write_store=False)
    assert cache.flushes >= 1


def test_the_answer_cache_is_flushed_even_when_the_run_blows_up():
    """The expensive case: three hours in, something raises, and every answer since the
    last checkpoint is only in memory."""
    cache = _FlushCache({"a history of asthma": {"conditions": ["asthma"]}})

    def boom(_name):
        raise RuntimeError("provider fell over")

    with pytest.raises(RuntimeError):
        resolve_residue(["a history of asthma"], boom, cache=cache, write_store=False)
    assert cache.flushes >= 1


def test_a_dry_run_still_keeps_what_it_paid_for():
    """`--dry-run` means "do not touch the store", not "throw away the batch"."""
    cache = _FlushCache({"a history of asthma": {"conditions": ["asthma"]}})
    resolve_residue(["a history of asthma"], lambda n: [_Result("HP:0002099", "Asthma")],
                    cache=cache, write_store=False)
    assert cache.flushes >= 1
