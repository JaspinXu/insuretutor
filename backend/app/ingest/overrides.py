"""Human-verified page transcriptions.

Some brochure pages are infographics or nested tables whose meaning depends on
2-D layout (e.g. "Cash Value = Account Value - surrender charge" drawn as a
graphic). Automatic extraction returns the right words in the wrong order,
which is worse than useless for an insurance tutor. For those pages a reviewer
writes a Markdown transcription:

    data/overrides/<doc_id>/page-<NN>.md

with YAML front matter stating *why* the page needed it. The transcription
replaces the extracted text for that page only; citations still point to the
original PDF page. Everything else stays fully automatic.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from app.ingest.models import Block, Page

_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def override_path(overrides_dir: Path, doc_id: str, page: int) -> Path:
    return overrides_dir / doc_id / f"page-{page:02d}.md"


def parse_override(text: str, doc_id: str, page: int) -> tuple[Page, dict]:
    meta: dict = {}
    m = _FRONT_MATTER_RE.match(text)
    if m:
        meta = yaml.safe_load(m.group(1)) or {}
        text = text[m.end() :]

    blocks: list[Block] = []
    para: list[str] = []

    def flush() -> None:
        if para:
            blocks.append(Block(text="\n".join(para).strip(), kind="text"))
            para.clear()

    for line in text.splitlines():
        h = _HEADING_RE.match(line)
        if h:
            flush()
            kind = "title" if len(h.group(1)) == 1 else "heading"
            blocks.append(Block(text=h.group(2).strip(), kind=kind))
        elif not line.strip():
            flush()
        else:
            para.append(line.rstrip())
    flush()
    return Page(doc_id=doc_id, number=page, blocks=blocks, source="override"), meta


def load_overrides(overrides_dir: Path, doc_id: str) -> dict[int, Page]:
    folder = overrides_dir / doc_id
    pages: dict[int, Page] = {}
    if not folder.is_dir():
        return pages
    for path in sorted(folder.glob("page-*.md")):
        number = int(path.stem.split("-")[1])
        page, meta = parse_override(path.read_text(encoding="utf-8"), doc_id, number)
        if not meta.get("reason"):
            raise ValueError(f"{path}: override must document a 'reason' in its front matter")
        pages[number] = page
    return pages
