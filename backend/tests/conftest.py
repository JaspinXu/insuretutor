import pytest

from app.config import get_settings
from app.ingest.pipeline import build_corpus


@pytest.fixture(scope="session")
def corpus():
    s = get_settings()
    return build_corpus(s.docs_dir, s.overrides_dir)
