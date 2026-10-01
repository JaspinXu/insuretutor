from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Literal

BBox = tuple[float, float, float, float]

_CJK_RE = re.compile(r"[㐀-鿿]")


def _has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text))


@dataclass
class Block:
    """A paragraph-level unit of a page, in reading order."""

    text: str
    kind: Literal["title", "heading", "text"] = "text"
    size: float = 0.0
    bbox: BBox | None = None


@dataclass
class Page:
    doc_id: str
    number: int  # 1-based PDF page number (what the viewer shows)
    blocks: list[Block]
    source: Literal["extracted", "override"] = "extracted"

    @property
    def title(self) -> str:
        """Page title: the first title block (or, failing that, a large heading),
        plus its translation if the next one is in the other language — brochure
        titles come in Chinese/English pairs."""
        titles = [b.text for b in self.blocks if b.kind == "title"]
        if not titles:
            titles = [b.text for b in self.blocks if b.kind == "heading" and b.size >= 11]
        if not titles:
            return ""
        if len(titles) > 1 and _has_cjk(titles[0]) != _has_cjk(titles[1]):
            return f"{titles[0]} {titles[1]}"
        return titles[0]


@dataclass
class DocumentInfo:
    id: str
    file: str
    title: dict[str, str]
    insurer: str = ""
    product_type: str = ""
    doc_type: dict[str, str] = field(default_factory=dict)
    version: str = ""
    languages: list[str] = field(default_factory=list)
    text_fixes: dict[str, str] = field(default_factory=dict)
    # Cover / marketing-summary / company pages: still searchable, ranked lower.
    low_priority_pages: list[int] = field(default_factory=list)
    page_count: int = 0

    def __post_init__(self) -> None:
        # Catalog fields that may be given as one string or per language.
        if isinstance(self.title, str):
            self.title = {"en": self.title}
        if isinstance(self.doc_type, str):
            self.doc_type = {"en": self.doc_type} if self.doc_type else {}

    def display_title(self, lang: str = "en") -> str:
        return self.title.get(lang) or self.title.get("en") or self.id

    def display_doc_type(self, lang: str = "en") -> str:
        return self.doc_type.get(lang) or self.doc_type.get("en") or ""


@dataclass
class Chunk:
    """A retrievable passage. `text` is exactly what the LLM and user see."""

    id: str
    doc_id: str
    page: int
    section: str
    text: str
    lang: Literal["en", "zh-Hant", "mixed"]
    source: Literal["extracted", "override"]
    bboxes: list[BBox] = field(default_factory=list)
    # Display label naming every sub-section the chunk covers ("Inflation Risk · Credit Risk · Key
    # Exclusions"); `section` names only the first and is what retrieval indexes.
    label: str = ""

    @property
    def display_section(self) -> str:
        return self.label or self.section

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Chunk:
        d = dict(d)
        d["bboxes"] = [tuple(b) for b in d.get("bboxes", [])]
        return cls(**d)
