"""Hybrid retrieval: BM25 + dense embeddings, fused with Reciprocal Rank Fusion.

Why hybrid: BM25 is exact on product vocabulary ("Guaranteed Insurability
Option", "保證可保權益", "US$50,000"), dense vectors catch paraphrases ("lose my
job" -> "made redundant"). RRF fuses *ranks*, so the two score scales never
need calibrating against each other.

Several queries can be searched at once (the user's question plus the
router's rewrites in English and Traditional Chinese); every ranked list
votes in the same RRF pool.

Dense scoring is multi-vector: each chunk is embedded as a few short windows
and scored by its best window, because small multilingual encoders truncate
long inputs (a 400-token bilingual chunk would otherwise be judged by its
first paragraph only).

The corpus is small (tens of chunks per brochure), so exact search over an
in-memory matrix is faster and simpler than a vector database; the index is
cached on disk keyed by a fingerprint of the documents, overrides and model.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.config import Settings
from app.ingest.models import Chunk
from app.ingest.pipeline import Corpus, build_corpus, corpus_fingerprint, load_catalog
from app.rag.bm25 import BM25
from app.rag.embeddings import Embedder, create_embedder
from app.rag.glossary import Glossary
from app.rag.text import tokenize

log = logging.getLogger(__name__)

RRF_K = 60
WINDOW_CHARS = 220
EXPANSION_WEIGHT = 0.5  # glossary terms nudge the ranking; the user's own words dominate
LOW_PRIORITY_FACTOR = 0.8  # fused-score multiplier for cover / marketing-summary pages

_NOTE_RE = re.compile(r"\[Note \d+\]")
_MD_RE = re.compile(r"^#+\s*|\|", re.M)


@dataclass
class Hit:
    chunk: Chunk
    score: float  # fused RRF score
    bm25: float  # best BM25 score over all queries
    dense: float | None  # best cosine similarity over all queries (None if no embedder)


def search_text(chunk: Chunk, doc_title: str) -> str:
    """Text used for indexing: document + section context, without markup."""
    body = _MD_RE.sub(" ", _NOTE_RE.sub("", chunk.text))
    return f"{doc_title} | {chunk.section}\n{body}"


def windows(chunk: Chunk) -> list[str]:
    """Split a chunk into short, section-prefixed windows for dense scoring."""
    out: list[str] = []
    buf = ""
    for line in _MD_RE.sub(" ", _NOTE_RE.sub("", chunk.text)).splitlines():
        line = line.strip()
        if not line:
            continue
        if buf and len(buf) + len(line) > WINDOW_CHARS:
            out.append(buf)
            buf = ""
        buf = f"{buf} {line}".strip()
    if buf:
        out.append(buf)
    return [f"{chunk.section}: {w}" for w in out] or [chunk.section]


class Retriever:
    def __init__(
        self,
        corpus: Corpus,
        embedder: Embedder | None = None,
        window_vectors: np.ndarray | None = None,
        window_owner: np.ndarray | None = None,
        glossary: Glossary | None = None,
        dense_weight: float = 0.5,
    ) -> None:
        self.corpus = corpus
        self.glossary = glossary or Glossary([])
        # Vote weight of each dense ranked list in RRF (BM25 lists weigh 1.0). Below 1 means
        # exact product vocabulary leads and embeddings break ties / rescue paraphrases.
        self.dense_weight = dense_weight
        self.chunks = corpus.chunks
        titles = {d.id: d.display_title("en") for d in corpus.documents}
        self.bm25 = BM25([tokenize(search_text(c, titles.get(c.doc_id, ""))) for c in self.chunks])
        low = {(d.id, p) for d in corpus.documents for p in d.low_priority_pages}
        self.prior = np.array(
            [LOW_PRIORITY_FACTOR if (c.doc_id, c.page) in low else 1.0 for c in self.chunks], dtype=np.float64
        )
        self.embedder = embedder if window_vectors is not None else None
        self.window_vectors = window_vectors
        self.window_owner = window_owner

    @property
    def dense_enabled(self) -> bool:
        return self.embedder is not None

    # -- construction ------------------------------------------------------
    @classmethod
    def from_settings(cls, settings: Settings) -> Retriever:
        t0 = time.perf_counter()
        corpus = load_or_build_corpus(settings)
        embedder = create_embedder(settings)
        vectors = owner = None
        if embedder is not None:
            try:
                vectors, owner = load_or_build_vectors(settings, corpus, embedder)
            except Exception as exc:  # noqa: BLE001
                log.warning("Could not embed corpus with %s (%s); using BM25 only", embedder.name, exc)
                embedder = None
        r = cls(
            corpus,
            embedder,
            vectors,
            owner,
            Glossary.load(settings.data_dir / "glossary.yaml"),
            dense_weight=settings.dense_rrf_weight,
        )
        log.info(
            "Retriever ready: %d chunks, dense=%s (%.1fs)",
            len(corpus.chunks),
            embedder.name if embedder else "off",
            time.perf_counter() - t0,
        )
        return r

    # -- search ---------------------------------------------------------------
    def expansions(self, query: str) -> list[str]:
        return self.glossary.expand(query)

    def _weighted_query(self, query: str, expand: bool) -> dict[str, float]:
        weights = dict.fromkeys(tokenize(query), 1.0)
        if expand:
            for term in tokenize(" ".join(self.expansions(query))):
                weights.setdefault(term, EXPANSION_WEIGHT)
        return weights

    def search(self, queries: list[str], k: int = 6, expand: bool = True) -> list[Hit]:
        """Search several phrasings of one question; every ranked list votes in RRF.

        Glossary terms are added to the keyword query they were triggered by, at
        reduced weight (classic weighted query expansion) rather than searched
        as separate lists, so an expansion boosts the right passages without
        outvoting the question itself."""
        queries = [q for q in dict.fromkeys(q.strip() for q in queries) if q]
        lexical = [self._weighted_query(q, expand) for q in queries]
        n = len(self.chunks)
        if not queries or n == 0:
            return []
        fused = np.zeros(n, dtype=np.float64)
        best_bm25 = np.zeros(n, dtype=np.float32)
        best_dense = np.full(n, -1.0, dtype=np.float32) if self.dense_enabled else None

        for q in lexical:
            s = self.bm25.scores(q)
            best_bm25 = np.maximum(best_bm25, s)
            ranked = [i for i in np.argsort(-s) if s[i] > 0]
            for rank, i in enumerate(ranked):
                fused[i] += 1.0 / (RRF_K + rank + 1)

        if self.dense_enabled and best_dense is not None:
            qv = self.embedder.embed_queries(queries)  # type: ignore[union-attr]
            sims = qv @ self.window_vectors.T  # (queries, windows)
            for row in sims:
                per_chunk = np.full(n, -1.0, dtype=np.float32)
                np.maximum.at(per_chunk, self.window_owner, row)
                best_dense = np.maximum(best_dense, per_chunk)
                for rank, i in enumerate(np.argsort(-per_chunk)):
                    fused[i] += self.dense_weight / (RRF_K + rank + 1)

        fused *= self.prior
        order = np.argsort(-fused)[:k]
        return [
            Hit(
                chunk=self.chunks[i],
                score=float(fused[i]),
                bm25=float(best_bm25[i]),
                dense=float(best_dense[i]) if best_dense is not None else None,
            )
            for i in order
            if fused[i] > 0
        ]


# -- on-disk cache -------------------------------------------------------------
def _cache_dir(settings: Settings) -> Path:
    fp = corpus_fingerprint(settings.docs_dir, settings.overrides_dir)
    path = settings.index_dir / fp
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_or_build_corpus(settings: Settings) -> Corpus:
    path = _cache_dir(settings) / "chunks.json"
    documents = load_catalog(settings.docs_dir)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        for d in documents:
            d.page_count = data["page_counts"].get(d.id, 0)
        return Corpus(
            documents=documents,
            chunks=[Chunk.from_dict(c) for c in data["chunks"]],
            override_pages={k: v for k, v in data["override_pages"].items()},
        )
    corpus = build_corpus(settings.docs_dir, settings.overrides_dir)
    path.write_text(
        json.dumps(
            {
                "page_counts": {d.id: d.page_count for d in corpus.documents},
                "override_pages": corpus.override_pages,
                "chunks": [c.to_dict() for c in corpus.chunks],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return corpus


def load_or_build_vectors(settings: Settings, corpus: Corpus, embedder: Embedder) -> tuple[np.ndarray, np.ndarray]:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", embedder.name)
    path = _cache_dir(settings) / f"dense-w{WINDOW_CHARS}-{slug}.npz"
    if path.exists():
        data = np.load(path)
        return data["vectors"], data["owner"]
    texts, owner = [], []
    for i, c in enumerate(corpus.chunks):
        for w in windows(c):
            texts.append(w)
            owner.append(i)
    vectors = embedder.embed_documents(texts)
    owner_arr = np.array(owner, dtype=np.int64)
    np.savez(path, vectors=vectors, owner=owner_arr)
    return vectors, owner_arr
