"""Every enrichment cache is flushed without anyone remembering it (#57).

`_contra_disease_cache` was populated during a run and discarded at the end, because
`EnrichmentCache.put` only mutates an in-memory dict and the teardown flushed two of the
three caches by name. The result was 2,484 LLM calls re-run on every build, returning a
slightly different answer each time (2,442 / 2,445 / 2,448 contraindications).

The one-line fix — flush the third one too — leaves the same trap set for the fourth
cache. These tests pin the structural version: a cache registers itself, and the teardown
flushes whatever exists rather than whatever someone listed.
"""

from __future__ import annotations

import gc
import json

from medic.enrichment.cache import EnrichmentCache, flush_all, live_caches


def test_a_new_cache_is_flushed_without_being_named(tmp_path):
    """The property the hand-maintained list could not give: nobody has to know about it."""
    path = tmp_path / "brand_new.json"
    cache = EnrichmentCache(path)
    cache.put("k", {"v": 1})
    assert not path.exists()

    flush_all()

    assert path.exists()
    assert json.loads(path.read_text()) == {"k": {"v": 1}}
    assert cache is not None  # keep it alive for the registry


def test_several_caches_all_flush(tmp_path):
    caches = [EnrichmentCache(tmp_path / f"c{i}.json") for i in range(3)]
    for i, c in enumerate(caches):
        c.put(f"k{i}", {"i": i})

    flush_all()

    for i in range(3):
        assert (tmp_path / f"c{i}.json").exists()
    assert len(caches) == 3


def test_an_untouched_cache_writes_nothing(tmp_path):
    """flush() already no-ops when the cache was never loaded; registering must not
    change that, or a build would litter empty files for caches it did not use."""
    path = tmp_path / "never_used.json"
    cache = EnrichmentCache(path)

    flush_all()

    assert not path.exists()
    assert cache is not None


def test_a_collected_cache_does_not_break_the_flush(tmp_path):
    """The registry holds weak references, so a cache that went out of scope — every
    cache built by a test, for instance — is not resurrected and written by a later
    flush somewhere else in the process."""
    before = len(live_caches())
    cache = EnrichmentCache(tmp_path / "transient.json")
    cache.put("k", {"v": 1})
    assert len(live_caches()) == before + 1
    del cache
    gc.collect()
    assert len(live_caches()) == before

    flush_all()  # must not raise
    assert not (tmp_path / "transient.json").exists()


def test_no_cache_is_flushed_by_name_in_the_ingester():
    """The bug was a hand-written list of caches that one cache was missing from. Pin the
    property rather than the fix, so the list cannot come back."""
    from pathlib import Path

    src = Path("src/medic/ingest/dailymed/__main__.py").read_text()
    offenders = [
        line.strip() for line in src.splitlines()
        if "_cache.flush()" in line and "flush_all" not in line
    ]
    assert not offenders, (
        "caches flushed by name instead of via flush_all(); the next cache added will be "
        f"forgotten exactly as _contra_disease_cache was: {offenders}"
    )


def test_flush_all_is_idempotent(tmp_path):
    path = tmp_path / "twice.json"
    cache = EnrichmentCache(path)
    cache.put("k", {"v": 1})
    flush_all()
    first = path.read_text()
    flush_all()
    assert path.read_text() == first
    assert cache is not None
