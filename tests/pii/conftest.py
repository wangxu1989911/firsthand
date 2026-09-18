"""Tests here exercise the real Presidio/spaCy NER pass (design doc §1, §8.1).

The `pii` extra and its spaCy model are not `dev` dependencies (`redaction.py`
degrades to its pattern-only pass without them — see its module docstring), so
these tests skip cleanly wherever that's not installed. CI's dedicated job sets
`FIRSTHAND_REQUIRE_PII_NER` so a broken install there fails loudly instead of
the job going green having exercised nothing (same discipline as
`tests/integration/conftest.py`'s `_unreachable`).
"""

from __future__ import annotations

import os
import pathlib

import pytest

PII_DIR = pathlib.Path(__file__).parent


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark everything under this directory `presidio` (see the integration
    conftest for why this can't just be a module-level `pytestmark`)."""
    for item in items:
        if PII_DIR in pathlib.Path(str(item.path)).parents:
            item.add_marker(pytest.mark.presidio)


@pytest.fixture
def real_analyzer() -> object:
    """The real Presidio analyzer, or a skip/fail if it isn't available."""
    import firsthand.redaction as redaction

    redaction._analyzer.cache_clear()
    analyzer = redaction._analyzer()
    if analyzer is None:
        message = (
            "presidio-analyzer/spacy model not available — "
            "pip install -e '.[dev,pii]' && python -m spacy download en_core_web_sm"
        )
        if os.environ.get("FIRSTHAND_REQUIRE_PII_NER"):
            pytest.fail(message)
        pytest.skip(message)
    return analyzer
