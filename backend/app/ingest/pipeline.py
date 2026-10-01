"""Catalog -> PDF extraction -> verified overrides -> chunks.

Run ``python -m app.ingest.pipeline`` to print the chunks (useful when adding
a document or reviewing extraction quality).
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.ingest.chunker import chunk_pages
from app.ingest.models import Chunk, DocumentInfo
from app.ingest.overrides import load_overrides
from app.ingest.pdf import extract_document

# Bump when extraction/chunking logic changes, to invalidate cached indexes.
INGEST_VERSION = "4"


@dataclass
class Corpus:
    documents: list[DocumentInfo]
    chunks: list[Chunk]
    override_pages: dict[str, list[int]]

    def document(self, doc_id: str) -> DocumentInfo | None:
        return next((d for d in self.documents if d.id == doc_id), None)

    def chunk(self, chunk_id: str) -> Chunk | None:
        return next((c for c in self.chunks if c.id == chunk_id), None)


def load_catalog(docs_dir: Path) -> list[DocumentInfo]:
    data = yaml.safe_load((docs_dir / "catalog.yaml").read_text(encoding="utf-8")) or {}
    docs = [DocumentInfo(**d) for d in data.get("documents", [])]
    for d in docs:
        if not (docs_dir / d.file).is_file():
            raise FileNotFoundError(f"catalog entry {d.id!r}: {docs_dir / d.file} not found")
    return docs


def corpus_fingerprint(docs_dir: Path, overrides_dir: Path) -> str:
    """Hash of everything that determines the chunks (catalog, PDFs, overrides, code version)."""
    h = hashlib.sha256(INGEST_VERSION.encode())
    h.update((docs_dir / "catalog.yaml").read_bytes())
    for doc in load_catalog(docs_dir):
        h.update((docs_dir / doc.file).read_bytes())
        folder = overrides_dir / doc.id
        if folder.is_dir():
            for f in sorted(folder.glob("*.md")):
                h.update(f.name.encode())
                h.update(f.read_bytes())
    return h.hexdigest()[:16]


def build_corpus(docs_dir: Path, overrides_dir: Path) -> Corpus:
    documents = load_catalog(docs_dir)
    chunks: list[Chunk] = []
    override_pages: dict[str, list[int]] = {}
    for doc in documents:
        pages = extract_document(docs_dir / doc.file, doc)
        overrides = load_overrides(overrides_dir, doc.id)
        unknown = set(overrides) - {p.number for p in pages}
        if unknown:
            raise ValueError(f"{doc.id}: overrides for non-existent pages {sorted(unknown)}")
        pages = [overrides.get(p.number, p) for p in pages]
        override_pages[doc.id] = sorted(overrides)
        chunks.extend(chunk_pages(pages, doc.display_title("en")))
    return Corpus(documents=documents, chunks=chunks, override_pages=override_pages)


if __name__ == "__main__":
    from app.config import get_settings

    s = get_settings()
    corpus = build_corpus(s.docs_dir, s.overrides_dir)
    if "--json" in sys.argv:
        for c in corpus.chunks:
            print(json.dumps(c.to_dict(), ensure_ascii=False))
    else:
        for c in corpus.chunks:
            print(f"\n=== {c.id}  [{c.lang}, {c.source}]  {c.display_section}")
            print(c.text)
        print(f"\n{len(corpus.chunks)} chunks from {len(corpus.documents)} document(s)")
