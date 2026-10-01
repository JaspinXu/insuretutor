"""Dense embedding backends.

* ``local``  – fastembed (ONNX Runtime, no PyTorch) with a multilingual model
  that is downloaded into the Docker image at build time, so the running
  container needs no network access for retrieval.
* ``openai`` – any OpenAI-compatible ``/embeddings`` endpoint.
* ``none``   – lexical retrieval only.

If a backend cannot be initialised (no model files, no key), the app logs a
warning and degrades to BM25-only instead of failing to start.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod

import numpy as np

from app.config import Settings

log = logging.getLogger(__name__)


def _normalize(m: np.ndarray) -> np.ndarray:
    m = np.asarray(m, dtype=np.float32)
    norms = np.linalg.norm(m, axis=-1, keepdims=True)
    return m / np.clip(norms, 1e-12, None)


class Embedder(ABC):
    name: str

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> np.ndarray: ...

    @abstractmethod
    def embed_queries(self, texts: list[str]) -> np.ndarray: ...


class FastEmbedEmbedder(Embedder):
    def __init__(self, model: str, cache_dir: str | None, model_path: str | None = None) -> None:
        from fastembed import TextEmbedding

        kwargs = {"specific_model_path": model_path} if model_path else {}
        self.model = TextEmbedding(model_name=model, cache_dir=cache_dir, **kwargs)
        self.name = f"local:{model}"

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return _normalize(np.stack(list(self.model.passage_embed(texts))))

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        return _normalize(np.stack(list(self.model.query_embed(texts))))


class OpenAIEmbedder(Embedder):
    def __init__(self, model: str, api_key: str, base_url: str | None, timeout: float) -> None:
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, base_url=base_url or None, timeout=timeout, max_retries=2)
        self.model = model
        self.name = f"openai:{model}"

    def _embed(self, texts: list[str]) -> np.ndarray:
        vectors: list[list[float]] = []
        for i in range(0, len(texts), 64):
            resp = self.client.embeddings.create(model=self.model, input=texts[i : i + 64])
            vectors.extend(d.embedding for d in sorted(resp.data, key=lambda d: d.index))
        return _normalize(np.array(vectors))

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self._embed(texts)

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        return self._embed(texts)


def create_embedder(settings: Settings) -> Embedder | None:
    backend = settings.embedding_backend
    try:
        if backend == "local":
            return FastEmbedEmbedder(
                settings.embedding_model,
                cache_dir=os.environ.get("FASTEMBED_CACHE_PATH") or str(settings.var_dir / "models"),
                model_path=os.environ.get("EMBEDDING_MODEL_PATH") or None,
            )
        if backend == "openai":
            key = settings.embedding_api_key or settings.compat_api_key
            if not key:
                log.warning(
                    "EMBEDDING_BACKEND=openai but no EMBEDDING_API_KEY/OPENAI_API_KEY/SOCLAAS_API_KEY; BM25 only"
                )
                return None
            base_url = settings.embedding_base_url or settings.compat_base_url
            model = settings.embedding_model
            if model.startswith("sentence-transformers/"):  # the local default; pick the endpoint's own model
                model = "bge-m3" if base_url and "soclaas" in base_url else "text-embedding-3-small"
            return OpenAIEmbedder(model, key, base_url, settings.llm_timeout_s)
    except Exception as exc:  # noqa: BLE001 - any failure means "run without dense retrieval"
        log.warning("Dense embeddings unavailable (%s: %s); falling back to BM25 only", type(exc).__name__, exc)
    return None
