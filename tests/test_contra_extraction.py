"""Tests for the contra-tuned disease extractor.

Verifies that `extract_contraindicated_diseases_from_text` exists, has its
own cache, and is correctly imported by the EMA and PMDA contra paths.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path


def _calls(path: str, func: str, arg: str) -> bool:
    """Does ``path`` call ``func`` on ``arg``? Whitespace-insensitive, so wrapping a
    long call across lines does not read as a missing call site."""
    src = Path(path).read_text()
    return re.search(rf"{re.escape(func)}\(\s*{re.escape(arg)}\b", src) is not None


def test_contra_extractor_function_exists():
    """The contra-tuned sister function must exist with the expected signature."""
    from medic.ingest.dailymed.__main__ import extract_contraindicated_diseases_from_text
    sig = inspect.signature(extract_contraindicated_diseases_from_text)
    params = list(sig.parameters.values())
    assert params[0].name == "contraindication_text"
    assert params[0].annotation in (str, "str")
    # Everything after the text is keyword-only. `source` tells the negation screen how
    # to split the text into spans (issue #59); it must never be positional, or a caller
    # could silently pass a section body where a source name belongs.
    assert all(q.kind is inspect.Parameter.KEYWORD_ONLY for q in params[1:])
    assert set(sig.parameters) == {"contraindication_text", "source"}


def test_contra_cache_is_separate_from_indication_cache():
    """The contra extractor must use a different cache file than the indication
    extractor — otherwise contra and indication results collide on identical
    source text."""
    from medic.ingest.dailymed.__main__ import (
        DISEASE_CACHE_PATH,
        CONTRA_DISEASE_CACHE_PATH,
    )
    assert DISEASE_CACHE_PATH != CONTRA_DISEASE_CACHE_PATH, (
        "Contraindication disease cache must not share a file with the "
        "indication disease cache."
    )
    assert "contra" in str(CONTRA_DISEASE_CACHE_PATH).lower(), (
        f"Cache path should be self-documenting; got {CONTRA_DISEASE_CACHE_PATH!r}"
    )


def test_contra_extractor_returns_empty_on_empty_input():
    """Defensive: empty input must short-circuit before any LLM call."""
    from medic.ingest.dailymed.__main__ import extract_contraindicated_diseases_from_text
    assert extract_contraindicated_diseases_from_text("") == []
    assert extract_contraindicated_diseases_from_text(None) == []  # type: ignore[arg-type]


def test_dailymed_contra_path_uses_contra_extractor():
    """The DailyMed contraindication path must call the contra-tuned function,
    not the indication-tuned one."""
    path = "src/medic/ingest/dailymed/__main__.py"
    # The contra path must call the contra-tuned extractor on the contra text...
    assert _calls(path, "extract_contraindicated_diseases_from_text", "contras_text"), (
        "DailyMed contra extraction call site not found"
    )
    # ...and must NOT feed contra text to the indication-tuned extractor.
    assert not _calls(path, " extract_diseases_from_text", "contras_text"), (
        "DailyMed contra path uses the indication-tuned extractor on contra text"
    )


def test_pmda_contra_path_uses_contra_extractor():
    """The PMDA contraindication path must call the contra-tuned function."""
    path = "src/medic/ingest/pmda/__main__.py"
    assert _calls(path, "extract_contraindicated_diseases_from_text", "section_text"), (
        "PMDA contra extraction call site not found"
    )
    assert not _calls(path, " extract_diseases_from_text", "section_text"), (
        "PMDA contra path uses the indication-tuned extractor on contra text"
    )


def test_ema_contra_path_uses_contra_extractor():
    """The EMA contraindication path must call the contra-tuned function."""
    path = "src/medic/ingest/ema/__main__.py"
    assert _calls(path, "extract_contraindicated_diseases_from_text", "contras_text"), (
        "EMA contra extraction call site not found"
    )
    assert not _calls(path, " extract_diseases_from_text", "contras_text"), (
        "EMA contra path uses the indication-tuned extractor on contra text"
    )
