"""Okapi BM25 over pre-tokenised documents (small corpus, exact scoring)."""

from __future__ import annotations

import math
from collections import Counter

import numpy as np


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.2, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.tfs = [Counter(d) for d in docs]
        self.lengths = np.array([len(d) for d in docs], dtype=np.float32)
        self.avg_len = float(self.lengths.mean()) if len(docs) else 0.0
        df: Counter[str] = Counter()
        for tf in self.tfs:
            df.update(tf.keys())
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: list[str]) -> np.ndarray:
        out = np.zeros(len(self.tfs), dtype=np.float32)
        if not self.tfs:
            return out
        norm = self.k1 * (1 - self.b + self.b * self.lengths / (self.avg_len or 1.0))
        for term in set(query):
            idf = self.idf.get(term)
            if idf is None:
                continue
            tf = np.array([d.get(term, 0) for d in self.tfs], dtype=np.float32)
            out += idf * tf * (self.k1 + 1) / (tf + norm)
        return out
