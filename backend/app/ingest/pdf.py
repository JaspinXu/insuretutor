"""PDF -> pages of paragraph blocks, using PyMuPDF.

Brochures are designed documents, not prose, so the extractor:

* keeps PyMuPDF's content-stream block order (the designer's reading order,
  which keeps each Chinese paragraph next to its English translation);
* joins wrapped lines (no space between CJK characters, a space for English);
* turns superscript footnote digits into explicit ``[Note n]`` markers so the
  model can connect e.g. "Guaranteed Insurability Option[Note 3]" to Note 3;
* splits a bold lead-in line ("Termination", "終止") off its paragraph so it
  becomes a heading, and classifies blocks as title / heading / text;
* drops decoration (page numbers, big section-number badges, bullet dots);
* applies per-document text fixes from the catalog (font-mapping errata).

Pages whose visual layout cannot be recovered this way (multi-column tables,
infographics) can be replaced by a human-verified transcription, see
``app.ingest.overrides``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from app.ingest.models import Block, DocumentInfo, Page
from app.lang import is_cjk_char

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f​-‏  ﻿]")
_WORDY_RE = re.compile(r"[A-Za-z㐀-鿿]")
_BULLETS_ONLY_RE = re.compile(r"^[\s•·.■]*$")
_DIGITS_ONLY_RE = re.compile(r"^\s*\d{1,3}\s*$")
_TRAILING_BADGE_RE = re.compile(r"\s+\d$")
_CJK_PUNCT = set("，。、；：？！「」『』（）《》〈〉【】…—")
_BOLD_FONT_RE = re.compile(r"(Bold|Medium|Heavy|Black|Semibold)", re.I)

TITLE_MIN_SIZE = 15.0
HEADING_MIN_SIZE = 11.0
MAX_HEADING_CHARS = 80
BADGE_MIN_SIZE = 20.0  # large lone digits are section-number badges
FOOTER_ZONE = 0.92  # lone digits below this fraction of page height = page numbers


def _is_cjkish(ch: str) -> bool:
    return is_cjk_char(ch) or ch in _CJK_PUNCT


def join_lines(lines: list[str]) -> str:
    """Join wrapped lines of one paragraph, CJK-aware."""
    out = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if not out:
            out = line
        elif out.endswith("-") and len(out) > 1 and out[-2].isalpha():
            out += line  # hyphenated wrap: "last-in-" + "first-out"
        elif _is_cjkish(out[-1]) and _is_cjkish(line[0]):
            out += line
        else:
            out += " " + line
    return re.sub(r"[  ]{2,}", " ", out).strip()


def _clean(text: str) -> str:
    return _CONTROL_RE.sub("", text.replace("\t", " "))


def _is_bold(span: dict) -> bool:
    return bool(span["flags"] & 16) or bool(_BOLD_FONT_RE.search(span["font"]))


@dataclass
class _Line:
    text: str
    bold: bool
    size: float


def _read_line(line: dict) -> _Line | None:
    spans = [s for s in line["spans"] if _clean(s["text"])]
    if not spans:
        return None
    sizes = [s["size"] for s in spans]
    parts = []
    for i, s in enumerate(spans):
        text = _clean(s["text"])
        others = sizes[:i] + sizes[i + 1 :] or [0.0]
        is_super = bool(s["flags"] & 1) or s["size"] < 0.75 * max(others)
        if is_super and text.strip().isdigit():
            parts.append(f"[Note {text.strip()}]")
        else:
            parts.append(text)
    visible = [s for s in spans if s["text"].strip() and not s["text"].strip().isdigit()] or spans
    return _Line(
        text="".join(parts),
        bold=all(_is_bold(s) for s in visible if s["text"].strip()),
        size=max(sizes),
    )


def _classify(text: str, size: float, bold: bool) -> str:
    if not _WORDY_RE.search(text) or len(text) > MAX_HEADING_CHARS:
        return "text"
    if size >= TITLE_MIN_SIZE:
        return "title"
    if size >= HEADING_MIN_SIZE or bold:
        return "heading"
    return "text"


def _apply_fixes(text: str, doc: DocumentInfo) -> str:
    for wrong, right in doc.text_fixes.items():
        text = text.replace(wrong, right)
    return text


def extract_page(page: pymupdf.Page, doc: DocumentInfo) -> Page:
    height = page.rect.height
    blocks: list[Block] = []
    for rb in page.get_text("dict")["blocks"]:
        if rb["type"] != 0:
            continue
        lines = [ln for ln in (_read_line(raw) for raw in rb["lines"]) if ln]
        if not lines:
            continue
        raw_text = join_lines([ln.text for ln in lines])
        max_size = max(ln.size for ln in lines)
        bbox = tuple(rb["bbox"])

        # Decoration: bullets, page numbers, section badges.
        if _BULLETS_ONLY_RE.match(raw_text):
            continue
        if _DIGITS_ONLY_RE.match(raw_text) and (max_size >= BADGE_MIN_SIZE or bbox[1] > height * FOOTER_ZONE):
            continue
        # Superscript-only blocks at the bottom are page numbers, not notes.
        if re.fullmatch(r"\[Note \d+\]", raw_text) and bbox[1] > height * FOOTER_ZONE:
            continue

        # A bold lead-in line followed by regular lines -> heading + paragraph.
        lead = 0
        while lead < len(lines) and lines[lead].bold:
            lead += 1
        if 0 < lead < len(lines):
            head = join_lines([ln.text for ln in lines[:lead]])
            if len(head) <= MAX_HEADING_CHARS and _WORDY_RE.search(head):
                head_size = max(ln.size for ln in lines[:lead])
                head_kind = "title" if head_size >= TITLE_MIN_SIZE else "heading"
                blocks.append(Block(_apply_fixes(head, doc), head_kind, round(head_size, 1), bbox))
                lines = lines[lead:]
                raw_text = join_lines([ln.text for ln in lines])
                max_size = max(ln.size for ln in lines)

        text = _apply_fixes(raw_text, doc)
        kind = _classify(text, max_size, all(ln.bold for ln in lines))
        if kind == "title":
            text = _TRAILING_BADGE_RE.sub("", text)  # "Life Protection Options 2"
        blocks.append(Block(text=text, kind=kind, size=round(max_size, 1), bbox=bbox))
    return Page(doc_id=doc.id, number=page.number + 1, blocks=_merge_wrapped(blocks))


_CJK_SENTENCE_END = set("。！？；：」）")


def _merge_wrapped(blocks: list[Block]) -> list[Block]:
    """Re-join CJK paragraphs that the PDF stores as one block per line
    ("...在保單生效第四至" + "第九年內，為繳付保費的7%...")."""
    merged: list[Block] = []
    for b in blocks:
        prev = merged[-1] if merged else None
        if (
            prev is not None
            and prev.kind == b.kind == "text"
            and prev.size == b.size
            and _is_cjkish(prev.text[-1])
            and prev.text[-1] not in _CJK_SENTENCE_END
            and (is_cjk_char(b.text[0]) or b.text[0].isdigit())
        ):
            prev.text += b.text
            if prev.bbox and b.bbox:
                prev.bbox = (
                    min(prev.bbox[0], b.bbox[0]),
                    min(prev.bbox[1], b.bbox[1]),
                    max(prev.bbox[2], b.bbox[2]),
                    max(prev.bbox[3], b.bbox[3]),
                )
            continue
        merged.append(b)
    return merged


def open_pdf(path: Path) -> pymupdf.Document:
    pdf = pymupdf.open(path)
    if pdf.needs_pass and not pdf.authenticate(""):
        raise ValueError(f"{path.name} is password-protected")
    return pdf


def extract_document(path: Path, doc: DocumentInfo) -> list[Page]:
    with open_pdf(path) as pdf:
        doc.page_count = pdf.page_count
        return [extract_page(p, doc) for p in pdf]
