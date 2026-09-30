from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Literal

import pymupdf
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.chat import ChatService, TurnRequest
from app.store import Store

log = logging.getLogger(__name__)
router = APIRouter()

# Starter questions for the welcome screen: (topic key for the UI icon, question).
SUGGESTIONS = {
    "en": [
        ("death", "What are the death benefit options?"),
        ("gio", "How does the Guaranteed Insurability Option work, and what are its limits?"),
        ("fees", "What fees and charges does this plan have?"),
        ("job", "What happens if I lose my job?"),
        ("rates", "Is the 4% crediting interest rate guaranteed?"),
        ("cooling", "How does the cooling-off period work?"),
    ],
    "zh-Hans": [
        ("death", "身故保障有哪几种选择？"),
        ("gio", "保证可保权益怎么运作？有什么上限？"),
        ("fees", "这个计划有哪些费用？"),
        ("job", "如果我失业了会怎样？"),
        ("rates", "4%的派息率是保证的吗？"),
        ("cooling", "冷静期是怎样的？"),
    ],
    "zh-Hant": [
        ("death", "身故保障有哪幾種選擇？"),
        ("gio", "保證可保權益怎樣運作？有甚麼上限？"),
        ("fees", "這個計劃有哪些費用？"),
        ("job", "如果我失業了會怎樣？"),
        ("rates", "4%的派息率是保證的嗎？"),
        ("cooling", "冷靜期是怎樣的？"),
    ],
}

PAGE_DPI = {"full": 110, "thumb": 40}

_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


# -- dependencies -------------------------------------------------------------------
def get_chat(request: Request) -> ChatService:
    return request.app.state.chat


def get_store(request: Request) -> Store:
    return request.app.state.store


def client_id(x_client_id: str | None = Header(default=None)) -> str:
    if x_client_id is None:
        return "anonymous"
    if not _CLIENT_ID_RE.match(x_client_id):
        raise HTTPException(400, "invalid X-Client-Id")
    return x_client_id


class RateLimiter:
    """Sliding-window limit per client IP (in-memory; per process)."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        if self.per_minute <= 0:
            return
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            raise HTTPException(429, "Too many requests — please wait a moment.")
        q.append(now)


def rate_limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    request.app.state.rate_limiter.check(ip)


# -- models --------------------------------------------------------------------------
class ChatBody(BaseModel):
    message: str = Field(..., max_length=20000)
    conversation_id: str | None = Field(default=None, max_length=64)
    ui_lang: Literal["en", "zh-Hans", "zh-Hant"] = "en"


class FeedbackBody(BaseModel):
    rating: Literal[1, -1]
    comment: str = Field(default="", max_length=1000)


# -- endpoints ------------------------------------------------------------------------
@router.get("/health")
def health(chat: ChatService = Depends(get_chat)) -> dict:
    r = chat.retriever
    return {
        "status": "ok",
        "provider": chat.mode,
        "model": chat.llm.model if chat.llm else None,
        "dense_retrieval": r.embedder.name if r.embedder else None,
        "documents": len(r.corpus.documents),
        "chunks": len(r.corpus.chunks),
    }


@router.get("/config")
def config(request: Request, chat: ChatService = Depends(get_chat)) -> dict:
    corpus = chat.retriever.corpus
    return {
        "provider": chat.mode,
        "model": chat.llm.model if chat.llm else None,
        "dense_retrieval": chat.retriever.dense_enabled,
        "max_input_chars": request.app.state.settings.max_input_chars,
        "suggestions": {
            lang: [{"topic": topic, "question": q} for topic, q in items] for lang, items in SUGGESTIONS.items()
        },
        "documents": [
            {
                "id": d.id,
                "title": d.title,
                "insurer": d.insurer,
                "product_type": d.product_type,
                "doc_type": d.doc_type,
                "version": d.version,
                "pages": d.page_count,
                "override_pages": corpus.override_pages.get(d.id, []),
            }
            for d in corpus.documents
        ],
    }


@router.post("/chat", dependencies=[Depends(rate_limit)])
async def chat_endpoint(
    body: ChatBody, cid: str = Depends(client_id), chat: ChatService = Depends(get_chat)
) -> StreamingResponse:
    req = TurnRequest(client_id=cid, message=body.message, ui_lang=body.ui_lang, conversation_id=body.conversation_id)

    async def events():
        try:
            async for event, data in chat.run(req):
                yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        except Exception:  # noqa: BLE001 - never leak internals to the client
            log.exception("chat turn failed")
            payload = json.dumps({"message": "Internal error — please try again."})
            yield f"event: error\ndata: {payload}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/conversations")
def list_conversations(cid: str = Depends(client_id), store: Store = Depends(get_store)) -> list[dict]:
    return store.list_conversations(cid)


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, cid: str = Depends(client_id), store: Store = Depends(get_store)) -> dict:
    conv = store.get_conversation(conversation_id, cid)
    if not conv:
        raise HTTPException(404, "conversation not found")
    return {"conversation": conv, "messages": store.messages(conversation_id)}


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str, cid: str = Depends(client_id), store: Store = Depends(get_store)):
    if not store.delete_conversation(conversation_id, cid):
        raise HTTPException(404, "conversation not found")
    return Response(status_code=204)


@router.post("/messages/{message_id}/feedback", status_code=204)
def feedback(message_id: str, body: FeedbackBody, cid: str = Depends(client_id), store: Store = Depends(get_store)):
    if not store.set_feedback(message_id, cid, body.rating, body.comment):
        raise HTTPException(404, "message not found")
    return Response(status_code=204)


@router.get("/documents/{doc_id}/file")
def document_file(doc_id: str, request: Request, chat: ChatService = Depends(get_chat)) -> FileResponse:
    doc = chat.retriever.corpus.document(doc_id)
    if not doc:
        raise HTTPException(404, "document not found")
    path = request.app.state.settings.docs_dir / doc.file
    return FileResponse(path, media_type="application/pdf", filename=doc.file)


def _render_page(pdf_path: Path, page_no: int, rects: list[tuple], dpi: int, out: Path) -> None:
    with pymupdf.open(pdf_path) as pdf:
        if pdf.needs_pass:
            pdf.authenticate("")
        page = pdf[page_no - 1]
        for r in rects:
            page.draw_rect(
                pymupdf.Rect(*r), color=(0.95, 0.6, 0.0), fill=(1.0, 0.85, 0.2), fill_opacity=0.28, width=0.8
            )
        pix = page.get_pixmap(dpi=dpi)
        out.parent.mkdir(parents=True, exist_ok=True)
        pix.save(out)


@router.get("/documents/{doc_id}/pages/{page_no}.png")
async def page_image(
    doc_id: str,
    page_no: int,
    request: Request,
    chunk: str | None = None,
    size: Literal["full", "thumb"] = "full",
    chat: ChatService = Depends(get_chat),
) -> FileResponse:
    corpus = chat.retriever.corpus
    doc = corpus.document(doc_id)
    if not doc or not 1 <= page_no <= doc.page_count:
        raise HTTPException(404, "page not found")
    rects: list[tuple] = []
    if chunk:
        c = corpus.chunk(chunk)
        if c and c.doc_id == doc_id and c.page == page_no:
            rects = list(c.bboxes)
    settings = request.app.state.settings
    key = hashlib.sha1(json.dumps([doc_id, page_no, rects, size]).encode()).hexdigest()[:16]
    out = settings.var_dir / "pages" / f"{doc_id}-{page_no:02d}-{size}-{key}.png"
    if not out.exists():
        await run_in_threadpool(_render_page, settings.docs_dir / doc.file, page_no, rects, PAGE_DPI[size], out)
    return FileResponse(out, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
