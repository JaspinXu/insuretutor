import numpy as np
import pytest

from app.rag.bm25 import BM25
from app.rag.embeddings import Embedder, _normalize
from app.rag.glossary import Glossary, GlossaryEntry
from app.rag.retriever import Retriever, windows
from app.rag.text import tokenize


def test_tokenizer_is_script_insensitive():
    assert tokenize("保證可保權益") == tokenize("保证可保权益")


def test_tokenizer_normalises_numbers_and_drops_stopwords():
    toks = tokenize("What is the US$50,000 limit for 2.5% interest?")
    assert "50000" in toks and "2.5" in toks and "interest" in toks
    assert "the" not in toks and "what" not in toks


def test_bm25_prefers_matching_document():
    bm = BM25([tokenize("cooling-off period 21 days"), tokenize("surrender charge 14 years")])
    s = bm.scores(tokenize("how long is the cooling-off period"))
    assert s[0] > s[1] == 0


def test_glossary_matches_whole_words_only():
    g = Glossary([GlossaryEntry("Premium Expense Charge", ("fee", "fees"))])
    assert g.expand("What fees apply?") == ["Premium Expense Charge"]
    assert g.expand("I feel unsure") == []


@pytest.mark.parametrize(
    "query, page",
    [
        ("How many times can I exercise the Guaranteed Insurability Option?", {12, 16}),
        ("保证可保权益最多可以行使几次？", {12, 16}),
        ("保證可保權益最多可以行使幾次？", {12, 16}),
        ("What happens if I lose my job?", {11, 16}),
        ("冷静期有多少天？", {15}),
        ("What is the minimum sum insured?", {17}),
        ("How is the cash value calculated?", {10}),
        ("What are the death benefit options?", {7, 16}),
        ("What is the guaranteed interest rate?", {8, 16}),
        ("自殺的不保事項是什麼", {14}),
    ],
)
def test_bm25_retrieval_finds_expected_page(retriever, query, page):
    top_pages = {h.chunk.page for h in retriever.search([query], k=3)}
    assert top_pages & page, f"{query!r}: expected one of {page}, got {top_pages}"


def test_router_keyword_queries_cannot_outvote_the_question(retriever):
    """Live router rewrites for "lose my job" used generic terms the brochure doesn't feature
    (automatic premium loan, policy lapse). Pooled at half weight they must not push the
    Unemployment Protection pages out of the top results."""
    rewrites = [
        "premium payment default 繳費逾期",
        "policy lapse 保單失效",
        "cash value 現金價值",
        "automatic premium loan",
    ]
    question = "What happens if I lose my job?"
    pooled = {h.chunk.page for h in retriever.search([question], k=3, rewrites=rewrites)}
    assert {11, 16} <= pooled
    # Searched as separate full-weight lists (the old fusion), they pushed both pages out of the top 6.
    assert not {11, 16} & {h.chunk.page for h in retriever.search([question, *rewrites], k=6)}


def test_out_of_scope_query_has_no_lexical_match(retriever):
    assert all(h.bm25 == 0 for h in retriever.search(["weather in Singapore today"], k=3))


class BagOfWordsEmbedder(Embedder):
    """Deterministic stand-in for a neural model: hashed bag of tokens."""

    name = "test:bow"

    def _vec(self, text):
        v = np.zeros(256, dtype=np.float32)
        for t in tokenize(text):
            v[hash(t) % 256] += 1
        return v

    def embed_documents(self, texts):
        return _normalize(np.stack([self._vec(t) for t in texts]))

    def embed_queries(self, texts):
        return self.embed_documents(texts)


def test_hybrid_search_uses_multi_vector_dense_scores(corpus):
    emb = BagOfWordsEmbedder()
    texts, owner = [], []
    for i, c in enumerate(corpus.chunks):
        for w in windows(c):
            texts.append(w)
            owner.append(i)
    r = Retriever(corpus, emb, emb.embed_documents(texts), np.array(owner))
    assert r.dense_enabled
    hits = r.search(["cooling-off period right of cancellation"], k=3)
    assert hits[0].chunk.page == 15
    assert hits[0].dense is not None and hits[0].dense > 0
