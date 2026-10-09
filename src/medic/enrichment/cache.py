"""Simple JSON-file cache for enrichment results. GitHub-diffable."""

import json
import weakref
from pathlib import Path

#: Every live cache, so a caller can flush them all without naming any of them.
#:
#: `put` only mutates an in-memory dict — persistence happens in `flush` — so a cache
#: nobody flushes is silently re-queried on the next build. The DailyMed teardown flushed
#: two of its three by name, and the third re-ran 2,484 non-deterministic LLM calls on
#: every build for as long as nobody noticed (#57). Flushing one more by name would have
#: left the same trap set for the fourth, so registration is automatic instead.
#:
#: Weak, so a cache that goes out of scope — every cache a test builds — is not
#: resurrected and written by some later flush elsewhere in the process.
_REGISTRY: weakref.WeakSet = weakref.WeakSet()


def live_caches() -> list["EnrichmentCache"]:
    """Every cache still alive, for tests and diagnostics."""
    return list(_REGISTRY)


def flush_all() -> None:
    """Persist every live cache. Untouched caches write nothing, as `flush` no-ops."""
    for cache in list(_REGISTRY):
        cache.flush()


class EnrichmentCache:
    """Sorted, deterministic JSON cache for enrichment results."""

    def __init__(self, cache_path: Path):
        self._path = cache_path
        self._data: dict | None = None
        _REGISTRY.add(self)

    def _load(self) -> dict:
        if self._data is not None:
            return self._data
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text())
            except (json.JSONDecodeError, OSError):
                self._data = {}
        else:
            self._data = {}
        return self._data

    def get(self, key: str) -> dict | None:
        return self._load().get(key)

    def put(self, key: str, value: dict) -> None:
        self._load()[key] = value

    def flush(self) -> None:
        if self._data is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Sorted keys, no timestamps, deterministic output
        self._path.write_text(
            json.dumps(self._data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        )
