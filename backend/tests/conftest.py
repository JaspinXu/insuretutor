import pytest

from app.config import get_settings
from app.ingest.pipeline import build_corpus


@pytest.fixture(scope="session")
def corpus():
    s = get_settings()
    return build_corpus(s.docs_dir, s.overrides_dir)


@pytest.fixture(scope="session")
def retriever(corpus):
    from app.rag.glossary import Glossary
    from app.rag.retriever import Retriever

    return Retriever(corpus, glossary=Glossary.load(get_settings().data_dir / "glossary.yaml"))
