from pathlib import Path

import pytest

from copilot.checker import Context, check
from copilot.kb import load_catalog

KB_DIR = Path(__file__).resolve().parents[3] / "kb"


@pytest.fixture(scope="session")
def catalog():
    return load_catalog(KB_DIR)


@pytest.fixture
def run(catalog):
    """Checks a piece of AFL and returns the whole result."""

    def _run(source, timeframe="daily", market_id=None):
        return check(source, catalog, Context(timeframe=timeframe, market_id=market_id))

    return _run


@pytest.fixture
def found(run):
    """Checks a piece of AFL and returns the findings of one rule."""

    def _found(source, rule, timeframe="daily"):
        result = run(source, timeframe=timeframe)
        assert result.status != "checker_error", result.error
        return [finding for finding in result.findings if finding.rule == rule]

    return _found
