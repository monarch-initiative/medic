"""LLM condition resolver for the disease-grounding residue.

Bridges the *unresolved* disease-string residue to MONDO/HP without asking a model for an
identifier: for a clinical phrase the deterministic lexical grounder cannot ground, ask the
LLM what condition the phrase names, then feed that name back through MeDIC's own lexical
cascade to reach a real term.

Why it is needed
----------------
52.8% of every disease string the pipeline has ever extracted — 9,696 of 18,375 rows in
``mappings/disease_grounding.sssom.tsv`` — resolved to ``sssom:NoTermFound``, and 9,594 of
those are real clinical phrases rather than junk:

    "a history of bronchial asthma"
    "A high risk of arterial or venous thrombotic diseases"
    "inherited or acquired hypercoagulopathies"
    "A history of severe hypersensitivity reactions to protein bound paclitaxel"

No string transform reaches these. ``qualifier_variants`` strips a *leading* run of
qualifiers from a fixed vocabulary, so it handles 'moderate to severe X' and cannot touch
'a history of X' or a synonym the ontology does not list. Scored against the combination
gold standard, grounding refusal is the largest single cause of a missed curated claim:
123 of 234 (52.6%).

The extraction that produced these strings has already been paid for, so this is recovery of
sunk cost rather than new acquisition.

Hallucination guard
-------------------
**The model never returns an identifier.** It returns a condition *name*; the id is whatever
MeDIC's lexical cascade then grounds that name to. The only ids that can enter the store are
ones the pinned release already contains, so a confidently-wrong CURIE has no path in. This
is the single most important property of the design and the reason it is safe to run at
scale.

False-positive guard
--------------------
An LLM asked "what condition is this?" will always answer, including for
'(no condition named)' and '1000 cells/mm 3'. Three defences:

* the residue is pre-filtered for commentary and bare measurements (``looks_like_condition``);
* the prompt requires the literal ``NONE`` when the phrase names no condition, and that is
  honoured rather than second-guessed;
* the proposal is written at certainty 0.55 as ``skos:broadMatch``, which caps anything built
  on it at MEDIUM — a phrase is routinely narrower than the condition it names (a history of
  it, a risk of it), so the mapping is a generalisation and must never ship as an identity.

Determinism guard
-----------------
An LLM call must not live inside the offline matcher. This module runs as a separate, cached
enrichment (``cache/enrichment/disease_paraphrase.json``) and writes *proposed* rows into the
grounding store carrying ``subject_preprocessing: [llm_condition_paraphrase]``, so a curator
can review them and offline grounding runs read them deterministically. Same standing as
``rxnorm_resolve``, which does this for drugs.

Conjunctions
------------
A phrase may name two conditions ('Thrombophlebitis or thromboembolic disorders'), and the
store already supports one subject mapping to several ids — that is how a combination drug
literal works. Up to :data:`MAX_CONDITIONS` rows are proposed per string, and the report
counts the multi-condition cases separately, because splitting a conjunction turns one claim
into two edges and that is a change worth seeing rather than discovering.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from medic.enrichment.cache import EnrichmentCache
from medic.grounding.store import (
    NO_TERM,
    PARAPHRASE_RULE,
    UNSPECIFIED,
    GroundingDecision,
    LiteralMappingStore,
    is_locked,
)
from medic.ingest.common import should_skip_expensive_calls

logger = logging.getLogger(__name__)

CACHE_PATH = Path("cache/enrichment/disease_paraphrase.json")
GROUNDING_STORE = "mappings/disease_grounding.sssom.tsv"

#: Most conditions to accept from one phrase. A label sentence enumerating more than three
#: distinct conditions is a list the extractor should have split, not a paraphrase.
MAX_CONDITIONS = 3

#: The certainty recorded for these proposals; mirrors PreprocessingRuleEnum's annotation.
PARAPHRASE_CERTAINTY = 0.55

#: broadMatch, not closeMatch: see the module docstring's false-positive guard.
PARAPHRASE_PREDICATE = "skos:broadMatch"

#: What the model is told to return when a phrase names no condition at all.
NONE_TOKEN = "NONE"

#: Commentary the extractor emitted about its own answer, not a condition.
_COMMENTARY = re.compile(
    r"^\s*\(|^\s*(none|no condition|not indicated|unspecified|n/?a)\b|"
    r"\b(no therapeutic claim|limitation|not established|describes a)\b", re.I)

#: A bare threshold or measurement lifted out of eligibility criteria.
#:
#: Keyed on *units*, never on a leading digit. '17p deletion', '3rd degree AV block' and
#: '13th rib variant' are all in the real residue and all name conditions; a
#: ``^[^a-zA-Z]*\d`` clause rejected every one of them.
_MEASUREMENT = re.compile(
    r"cells\s*/\s*mm|mg\s*/\s*d[lL]|\d\s*%|%\s*(total|of)|\bmL\b|\bmmHg\b|"
    r"\bmmol\b|\bg/dL\b", re.I)


def looks_like_condition(text: str) -> bool:
    """Is this phrase worth asking about at all?

    Cheap pre-filter, not a judgement about groundability: it drops the extractor's own
    commentary and bare measurements so they neither cost a call nor invite an invented
    answer. Measured on the real residue this rejects 102 of 9,696.
    """
    s = (text or "").strip()
    if len(s) < 3:
        return False
    if _COMMENTARY.search(s):
        return False
    return not _MEASUREMENT.search(s)


_PROMPT = """What clinical condition does this phrase from a drug label name?

Phrase: {phrase}

Rules:
- Answer with the condition's common clinical name, nothing else.
- Strip framing that is not part of the condition: "a history of", "a risk of",
  "known", "active", "patients with", severity and timing qualifiers.
- If the phrase names more than one distinct condition, give one per line, at most {max_n}.
- If the phrase names no condition at all - it is a dose, a lab value, a drug name, a
  co-administration clause, or the extractor's own commentary - answer exactly {none}.
- Never answer with an ontology identifier. Names only.

Examples:
  "a history of bronchial asthma" -> asthma
  "inherited or acquired hypercoagulopathies" -> thrombophilia
  "Thrombophlebitis or thromboembolic disorders" -> thrombophlebitis
                                                    thromboembolism
  "1000 cells/mm 3" -> {none}
"""


def _parse(answer: str) -> list[str]:
    """Condition names out of the model's answer, or ``[]`` for NONE/unusable."""
    names: list[str] = []
    for line in (answer or "").splitlines():
        cleaned = line.strip().strip("-*• ").strip()
        if not cleaned:
            continue
        if cleaned.upper().startswith(NONE_TOKEN):
            return []
        # a model that explains itself anyway: keep the name, drop the commentary
        if cleaned.lower().startswith(("the phrase", "this phrase", "answer:")):
            cleaned = cleaned.split(":", 1)[-1].strip()
        if ":" in cleaned and len(cleaned.split(":", 1)[0]) < 12:
            cleaned = cleaned.split(":", 1)[-1].strip()
        if cleaned and cleaned.upper() != NONE_TOKEN:
            names.append(cleaned)
        if len(names) >= MAX_CONDITIONS:
            break
    return names


def name_conditions(phrase: str, cache: EnrichmentCache) -> list[str]:
    """Condition names the model says this phrase refers to. Cached; never returns ids."""
    cached = cache.get(phrase)
    if cached is not None:
        return list(cached.get("conditions") or [])
    if should_skip_expensive_calls():
        return []

    from medic.llm import llm_call
    answer = llm_call(
        _PROMPT.format(phrase=phrase, max_n=MAX_CONDITIONS, none=NONE_TOKEN),
        task="disease_paraphrase",
        max_tokens=120,
    )
    names = _parse(answer)
    cache.put(phrase, {"conditions": names, "raw": answer})
    return names


def _proposal_rows(source_label: str,
                   grounds: list[tuple[str, str, str | None]]) -> list[GroundingDecision]:
    """Proposed SSSOM rows for one recovered phrase.

    ``match_string`` carries the model's condition name — the in->out pair I-8 asks for, so
    the chain from the label's literal to the final id is replayable from the row alone.
    """
    return [
        GroundingDecision(
            subject_label=source_label,
            entity_type="diseases",
            predicate_id=PARAPHRASE_PREDICATE,
            object_id=object_id,
            object_label=object_label,
            object_match_field=None,
            mapping_justification=UNSPECIFIED,
            subject_preprocessing=[PARAPHRASE_RULE],
            match_string=condition,
            confidence=PARAPHRASE_CERTAINTY,
        )
        for condition, object_id, object_label in grounds
    ]


def resolve_residue(
    unresolved: list[str],
    ground_disease,
    store: LiteralMappingStore | None = None,
    cache: EnrichmentCache | None = None,
    write_store: bool = True,
) -> dict:
    """Name and re-ground the disease residue; propose MONDO/HP mappings.

    Args:
        unresolved: verbatim strings the deterministic grounder could not ground.
        ground_disease: callable ``str -> [GroundingResult]``, i.e. MeDIC's own cascade.
            Every id in the result comes from here, never from the model.
        store: grounding store to write proposals into (loaded lazily when None).
        cache: LLM answer cache.
        write_store: when False, measure without writing — a costed dry run.

    Returns:
        a report dict with counts, the proposals, and the target concentration.
    """
    # Flushed explicitly in the `finally` below, never left to `atexit`. The cache registry
    # is a `weakref.WeakSet`, so a cache held only in a local like this one is collected the
    # moment this function returns and is gone from the registry before the exit handler
    # runs. Measured the hard way: a 287-call pass reported its results and wrote none of
    # them, while an earlier run that *crashed* inside this function did save, because the
    # local was still on the stack. This is the trap #57 was about, one scope further in.
    cache = cache or EnrichmentCache(CACHE_PATH)
    if store is None and write_store:
        store = LiteralMappingStore(GROUNDING_STORE, "diseases")
        store.load()

    skipped = asked = said_none = unground = 0
    recovered: list[dict] = []
    multi = 0
    # Checkpoint the answer cache. `cache.flush_all` runs at exit, but the full residue is
    # ~9,600 calls over about three hours, and an exit that never reaches the atexit
    # handler (SIGKILL, a laptop sleeping out) would throw away every answer paid for since
    # the last write. The ingester checkpoints every 100 for exactly this reason.
    checkpoint_every = 100
    try:
        for phrase in unresolved:
            if not looks_like_condition(phrase):
                skipped += 1
                continue
            asked += 1
            if asked % checkpoint_every == 0:
                cache.flush()
                logger.info("  … %d asked, %d recovered", asked, len(recovered))
            names = name_conditions(phrase, cache)
            if not names:
                said_none += 1
                continue
            grounds: list[tuple[str, str, str | None]] = []
            for condition in names[:MAX_CONDITIONS]:
                results = ground_disease(condition)
                if results and results[0].id:
                    grounds.append((condition, results[0].id, results[0].label))
            if not grounds:
                unground += 1
                continue
            if len(grounds) > 1:
                multi += 1
            recovered.append({"phrase": phrase, "grounds": grounds})
            if write_store and store is not None and not store.manual_rows(phrase):
                # `record_subject` keeps the mention id already on file, which matters
                # here: the residue rows were stamped with the original literal's MEDICNE
                # id at ingest, and that id makes the chain replayable (I-9).
                store.record_subject(phrase, _proposal_rows(phrase, grounds))
    finally:
        # Answers are paid for whether or not proposals are written, so a dry run keeps
        # them too: `--dry-run` means "do not touch the store", not "throw away the batch".
        cache.flush()

    if write_store and store is not None:
        store.save()

    targets: dict[str, int] = {}
    for item in recovered:
        for _, object_id, _ in item["grounds"]:
            targets[object_id] = targets.get(object_id, 0) + 1
    return {
        "residue": len(unresolved),
        "skipped_not_a_condition": skipped,
        "asked": asked,
        "model_said_none": said_none,
        "named_but_ungroundable": unground,
        "recovered": len(recovered),
        "multi_condition": multi,
        "proposals": sum(len(i["grounds"]) for i in recovered),
        "targets": targets,
        "details": recovered,
    }


def collect_residue(store: LiteralMappingStore) -> list[str]:
    """Verbatim subjects the grounder left unresolved (``sssom:NoTermFound``).

    Reads the authoritative residue straight from the store, skipping subjects a curator or
    a prior proposal already owns. Mirrors ``rxnorm_resolve.collect_residue``.
    """
    residue: list[str] = []
    seen: set[str] = set()
    for rows in store._rows.values():  # noqa: SLF001 (module-owned store)
        if any(is_locked(d) for d in rows):
            continue
        if all(d.predicate_id == NO_TERM or d.object_id == NO_TERM for d in rows):
            subject = rows[0].subject_label
            if subject and subject not in seen:
                seen.add(subject)
                residue.append(subject)
    return residue


def main(argv: list[str] | None = None) -> None:
    """Batch pass: name the disease residue and write proposals into the store."""
    import argparse

    parser = argparse.ArgumentParser(description="LLM condition resolver for the residue")
    parser.add_argument("--limit", type=int, default=None,
                        help="cap the residue processed (for a costed sample)")
    parser.add_argument("--dry-run", action="store_true",
                        help="measure recovery without writing proposals")
    parser.add_argument("--show", type=int, default=15,
                        help="how many recovered phrases to print")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    store = LiteralMappingStore(GROUNDING_STORE, "diseases")
    store.load()
    residue = collect_residue(store)
    logger.info("Collected %d unresolved disease strings from %s",
                len(residue), GROUNDING_STORE)
    if args.limit:
        residue = residue[: args.limit]

    from medic.grounding.factory import get_grounding_service
    svc = get_grounding_service("lexical")
    report = resolve_residue(residue, svc.ground_disease, store=store,
                             write_store=not args.dry_run)

    for key in ("residue", "skipped_not_a_condition", "asked", "model_said_none",
                "named_but_ungroundable", "recovered", "multi_condition", "proposals"):
        logger.info("  %-26s %d", key, report[key])
    if report["asked"]:
        logger.info("  recovery rate of those asked: %.1f%%",
                    100 * report["recovered"] / report["asked"])

    top = sorted(report["targets"].items(), key=lambda kv: -kv[1])[:10]
    if top:
        logger.info("  most-proposed targets (a term absorbing many distinct phrases is "
                    "the thing to distrust):")
        for object_id, count in top:
            logger.info("     %-18s %d", object_id, count)

    for item in report["details"][: args.show]:
        logger.info("  %s", item["phrase"][:80])
        for condition, object_id, object_label in item["grounds"]:
            logger.info("      -> %-26s %s (%s)", condition[:26], object_id, object_label)


if __name__ == "__main__":
    main()
