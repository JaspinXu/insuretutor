"""Glossary-based query expansion (lay terms -> brochure terminology)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.rag.text import normalize


@dataclass(frozen=True)
class GlossaryEntry:
    terms: str
    aliases: tuple[str, ...]


class Glossary:
    def __init__(self, entries: list[GlossaryEntry]) -> None:
        self.entries = entries
        self._patterns = [
            (e, [self._pattern(a) for a in e.aliases]) for e in entries
        ]

    @staticmethod
    def _pattern(alias: str) -> re.Pattern[str]:
        a = normalize(alias)
        # Word boundaries for Latin aliases ("fee" must not match "feel").
        if re.search(r"[a-z]", a):
            return re.compile(rf"(?<![a-z]){re.escape(a)}(?![a-z])")
        return re.compile(re.escape(a))

    @classmethod
    def load(cls, path: Path) -> Glossary:
        if not path.is_file():
            return cls([])
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(
            [GlossaryEntry(e["terms"], tuple(e.get("aliases", []))) for e in data.get("entries", [])]
        )

    def expand(self, query: str) -> list[str]:
        """Canonical term strings for every entry whose alias occurs in the query."""
        q = normalize(query)
        return [e.terms for e, pats in self._patterns if any(p.search(q) for p in pats)]
