"""Heading-aware chunking.

A chunk is one or more "sections" (heading lines + the paragraphs under them),
packed up to a token budget and never crossing a page boundary, so every
citation maps to exactly one page. Because the brochure places each Chinese
paragraph next to its English translation, most chunks are bilingual: a
question in any language matches, and the model can quote the official wording
in the user's language.
"""

from __future__ import annotations

import re

from app.ingest.models import BBox, Block, Chunk, Page
from app.lang import is_cjk_char

MAX_TOKENS = 420
MIN_TOKENS = 60
MAX_LABELS = 3  # sub-section names shown in a chunk's display label
_NOTE_RE = re.compile(r"\s*\[Note \d+\]")
_CJK_RE = re.compile(r"[㐀-鿿]")


def est_tokens(text: str) -> int:
    """Rough token estimate: ~1 token per CJK character, ~4 chars per token otherwise."""
    cjk = sum(1 for ch in text if is_cjk_char(ch))
    return int(cjk + (len(text) - cjk) / 4) + 1


def chunk_language(text: str) -> str:
    cjk = sum(1 for ch in text if is_cjk_char(ch))
    latin = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    if latin < 0.05 * (cjk + latin):
        return "zh-Hant"
    if cjk < 0.05 * (cjk + latin):
        return "en"
    return "mixed"


def clean_label(text: str) -> str:
    return _NOTE_RE.sub("", text).strip()


class _Section:
    def __init__(self) -> None:
        self.headings: list[str] = []
        self.heading_bboxes: list[BBox] = []
        self.blocks: list[Block] = []

    @property
    def label(self) -> str:
        """Most specific heading, paired with its translation when the last two
        headings are a Chinese/English pair (e.g. 保證可保權益 / Guaranteed ...)."""
        if not self.headings:
            return ""
        last = self.headings[-1]
        if len(self.headings) > 1:
            prev = self.headings[-2]
            if bool(_CJK_RE.search(prev)) != bool(_CJK_RE.search(last)):
                return clean_label(f"{prev} {last}")
        return clean_label(last)

    def lines(self) -> list[str]:
        return [f"## {h}" for h in self.headings] + [b.text for b in self.blocks]

    def tokens(self) -> int:
        return est_tokens("\n".join(self.lines()))

    def bboxes(self) -> list[BBox]:
        return self.heading_bboxes + [b.bbox for b in self.blocks if b.bbox]


def _sections(page: Page) -> list[_Section]:
    """Group blocks under their headings. Title blocks are page-level context
    (carried in the chunk's `section` label), not section headings."""
    sections = [_Section()]
    for b in page.blocks:
        if b.kind == "title":
            continue
        current = sections[-1]
        if b.kind == "heading":
            if current.blocks:
                current = _Section()
                sections.append(current)
            current.headings.append(b.text)
            if b.bbox:
                current.heading_bboxes.append(b.bbox)
        else:
            current.blocks.append(b)
    return [s for s in sections if s.blocks or s.headings]


def _split_section(section: _Section) -> list[_Section]:
    """Split an oversized section by paragraphs, repeating its headings."""
    parts: list[_Section] = []
    current = _Section()
    current.headings, current.heading_bboxes = list(section.headings), list(section.heading_bboxes)
    for b in section.blocks:
        if current.blocks and est_tokens("\n".join(current.lines() + [b.text])) > MAX_TOKENS:
            parts.append(current)
            current = _Section()
            current.headings = list(section.headings)
        current.blocks.append(b)
    parts.append(current)
    return parts


def chunk_page(page: Page, doc_title: str) -> list[Chunk]:
    title = clean_label(page.title)
    sections: list[_Section] = []
    for s in _sections(page):
        sections.extend(_split_section(s) if s.tokens() > MAX_TOKENS else [s])

    groups: list[list[_Section]] = []
    for s in sections:
        if groups and sum(x.tokens() for x in groups[-1]) + s.tokens() <= MAX_TOKENS:
            groups[-1].append(s)
        else:
            groups.append([s])
    # Fold a tiny trailing group into its predecessor rather than index a fragment.
    if len(groups) > 1 and sum(x.tokens() for x in groups[-1]) < MIN_TOKENS:
        groups[-2].extend(groups.pop())

    chunks: list[Chunk] = []
    for i, group in enumerate(groups):
        text = "\n".join(line for s in group for line in s.lines()).strip()
        if not text:
            continue
        labels = list(dict.fromkeys(s.label for s in group if s.label and s.label != title))
        label = labels[0] if labels else ""
        section = " › ".join(p for p in (title, label) if p) or doc_title
        # Packed sections are all named in the display label, so a citation of the suicide
        # exclusion doesn't read "Inflation Risk" just because that heading came first.
        shown = " · ".join(labels[:MAX_LABELS]) + (" …" if len(labels) > MAX_LABELS else "")
        display = " › ".join(p for p in (title, shown) if p) or doc_title
        chunks.append(
            Chunk(
                id=f"{page.doc_id}:p{page.number:02d}:{i}",
                doc_id=page.doc_id,
                page=page.number,
                section=section,
                text=text,
                lang=chunk_language(text),  # type: ignore[arg-type]
                source=page.source,
                bboxes=[bb for s in group for bb in s.bboxes()],
                label=display if len(labels) > 1 else "",
            )
        )
    return chunks


def chunk_pages(pages: list[Page], doc_title: str) -> list[Chunk]:
    return [c for p in pages for c in chunk_page(p, doc_title)]
