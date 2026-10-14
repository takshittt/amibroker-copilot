from pathlib import Path

import pytest

from copilot.config import Settings
from copilot.kb import load_catalog

KB_DIR = Path(__file__).resolve().parents[3] / "kb"


@pytest.fixture(scope="session")
def catalog():
    return load_catalog(KB_DIR)


@pytest.fixture
def settings():
    return Settings(strong_model="strong-model", cheap_model="cheap-model")
