"""FastAPI application factory.

    uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import RateLimiter
from app.api.routes import router as api_router
from app.chat import ChatService
from app.config import Settings, get_settings
from app.llm import create_llm
from app.llm.base import LLMProvider
from app.rag.retriever import Retriever
from app.store import Store

_UNSET = object()


def create_app(
    settings: Settings | None = None,
    *,
    retriever: Retriever | None = None,
    llm: LLMProvider | None | object = _UNSET,
    store: Store | None = None,
) -> FastAPI:
    """Build the app. Components can be injected (tests); otherwise built from settings."""
    settings = settings or get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("insuretutor")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        r = retriever or await asyncio.to_thread(Retriever.from_settings, settings)
        provider = create_llm(settings) if llm is _UNSET else llm
        db = store or Store(settings.db_path)
        app.state.settings = settings
        app.state.store = db
        app.state.rate_limiter = RateLimiter(settings.rate_limit_per_minute)
        app.state.chat = ChatService(settings, r, provider, db)  # type: ignore[arg-type]
        log.info(
            "InsureTutor ready: provider=%s model=%s dense=%s",
            app.state.chat.mode,
            getattr(provider, "model", None),
            r.embedder.name if r.embedder else "off",
        )
        yield

    app = FastAPI(title="InsureTutor", version="0.1.0", lifespan=lifespan)
    app.include_router(api_router, prefix="/api")

    static = settings.static_dir
    if static and Path(static).is_dir():
        index = Path(static) / "index.html"
        if (Path(static) / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=Path(static) / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path.startswith("api/"):
                raise HTTPException(404)
            candidate = (Path(static) / path).resolve()
            if path and candidate.is_file() and candidate.is_relative_to(Path(static).resolve()):
                return FileResponse(candidate)
            return FileResponse(index)

    return app


app = create_app()
