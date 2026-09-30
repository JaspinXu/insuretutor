"""Pre-build the retrieval index (chunks + embeddings) so the first request is fast.

Run at image build time (`python -m app.warmup`). The index is cached under
VAR_DIR keyed by a fingerprint of the documents, overrides and embedding
model, so the running container reuses it — or rebuilds it transparently if
the documents or model changed.
"""

from __future__ import annotations

import logging

from app.config import get_settings
from app.rag.retriever import Retriever


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    r = Retriever.from_settings(get_settings())
    hits = r.search(["Guaranteed Insurability Option 保證可保權益"], k=1)
    logging.info(
        "Warm-up search OK: top hit page %s (%s)",
        hits[0].chunk.page if hits else "-",
        r.embedder.name if r.embedder else "BM25 only",
    )


if __name__ == "__main__":
    main()
