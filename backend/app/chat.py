"""Chat orchestration: one user turn -> a stream of events.

Pipeline (each stage can end the turn early with a reviewed template):

  1. input guard   sanitise, redact PII, block injection / fraud / self-harm
  2. router        intent + standalone question + bilingual search queries
  3. retrieval     hybrid search, then a relevance gate ("don't answer from nothing")
  4. generation    grounded answer streamed from the LLM (or extractive, offline)
  5. output guard  citation validation, numeric grounding, leak check, script

Events: status, meta, sources, delta (answer text), final (validated answer +
citations + guardrail flags + metrics). The UI renders deltas live and then
replaces the text with `final.answer`, which is the checked version.
"""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from app.config import Settings
from app.guardrails.input import inspect, sanitize
from app.guardrails.messages import message
from app.guardrails.output import check_output, leaked_prompt
from app.guardrails.router import ANSWERABLE, Route, Router
from app.lang import Lang, convert_script, detect_language, is_cjk_char
from app.llm.base import LLMError, LLMProvider, LLMRefusal
from app.prompts import answer_system, answer_user_message
from app.rag.retriever import Hit, Retriever
from app.rag.text import tokenize
from app.store import Store

log = logging.getLogger(__name__)

# Backstop only: scope is decided by the router (LLM or domain vocabulary). Set well below the
# weakest in-scope eval question (best BM25 ≈ 4) so real questions are never refused here.
RELEVANCE_MIN_BM25 = 2.0
_CITE_RE = re.compile(r"\[\d+\]")
_NOTE_RE = re.compile(r"\s*\[Note \d+\]")

Event = tuple[str, dict]


@dataclass
class TurnRequest:
    client_id: str
    message: str
    ui_lang: Lang = "en"
    conversation_id: str | None = None


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _cjk_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha() or is_cjk_char(c)]
    return sum(1 for c in letters if is_cjk_char(c)) / len(letters) if letters else 0.0


def excerpt(text: str, lang: Lang, query: str = "", max_chars: int = 300, terms: Sequence[str] = ()) -> tuple[str, str]:
    """Best-matching lines of a (bilingual) chunk in the reader's language, and the heading
    the best one sits under — the offline mode's stand-in for a generated answer.

    `terms` are extra query words (glossary expansions, the router's search queries): lay
    questions rarely share words with the brochure ("lose my job" vs "Unemployment Benefit")."""
    raw = re.sub(r"(?<=[。！？」）])\s*(?=[A-Za-z“\"])", "\n", text)  # split "中文。 English" lines
    rows: list[tuple[str, str]] = []  # (heading, line)
    heading = ""
    for ln in raw.splitlines():
        if ln.lstrip().startswith("#"):
            heading = _NOTE_RE.sub("", ln.strip().lstrip("#")).strip()
            continue
        ln = _NOTE_RE.sub("", ln).lstrip("|- ").replace("|", " ").strip()
        if ln and not set(ln) <= set("-: "):
            rows.append((heading, ln))
    want_zh = lang != "en"
    picked = [r for r in rows if (_cjk_ratio(r[1]) > 0.3) == want_zh] or rows
    q = set(tokenize(" ".join([query, *terms])))
    # A line also scores through its heading, so a table row such as "A Special Grace Period
    # of up to 365 days" is found through its row label "Unemployment Benefit".
    overlap = [len(q & set(tokenize(ln))) + len(q & set(tokenize(h))) for h, ln in picked]
    best = max(overlap, default=0)
    if best:
        # Only lines that match the question about as well as the best one.
        order = sorted((i for i in range(len(picked)) if overlap[i] * 2 >= best), key=lambda i: -overlap[i])
    else:
        order = list(range(len(picked)))
    chosen: list[int] = []
    used = 0
    for i in order:
        if chosen and used + len(picked[i][1]) > max_chars:
            break
        chosen.append(i)
        used += len(picked[i][1])
    out = " ".join(picked[i][1] for i in sorted(chosen))
    out = out if len(out) <= max_chars + 40 else out[:max_chars].rstrip() + "…"
    return (picked[order[0]][0] if order else ""), out


class ChatService:
    def __init__(self, settings: Settings, retriever: Retriever, llm: LLMProvider | None, store: Store) -> None:
        self.settings = settings
        self.retriever = retriever
        self.llm = llm
        self.store = store
        self.canary = f"IT-CANARY-{secrets.token_hex(8)}"
        self.documents = retriever.corpus.documents
        described = "\n".join(
            f"- {d.display_title('en')} / {d.display_title('zh-Hant')} — {d.insurer}; {d.product_type}; {d.display_doc_type('en')}"
            for d in self.documents
        )
        self.router = Router(llm, described, retriever.glossary)

    @property
    def mode(self) -> str:
        return self.llm.provider if self.llm else "offline"

    def doc_names(self, lang: Lang) -> str:
        return (
            "、".join(d.display_title(lang) for d in self.documents)
            if lang != "en"
            else ", ".join(d.display_title(lang) for d in self.documents)
        )

    # -- helpers -------------------------------------------------------------------
    def _source(self, n: int, hit: Hit, lang: Lang) -> dict:
        c = hit.chunk
        doc = self.retriever.corpus.document(c.doc_id)
        return {
            "n": n,
            "chunk_id": c.id,
            "doc_id": c.doc_id,
            "doc_title": doc.display_title(lang) if doc else c.doc_id,
            "page": c.page,
            "section": convert_script(c.display_section, lang),
            "text": c.text,
            "lang": c.lang,
            "source": c.source,
            "score": round(hit.score, 4),
            "bm25": round(hit.bm25, 2),
            "dense": round(hit.dense, 3) if hit.dense is not None else None,
        }

    def _history(self, conversation_id: str) -> list[dict]:
        turns = self.store.recent_turns(conversation_id, self.settings.history_turns * 2)
        # Citation numbers are per-turn; strip them so old [n] can't be confused with new sources.
        turns = [{"role": t["role"], "content": _CITE_RE.sub("", t["content"]).strip()} for t in turns]
        while turns and turns[0]["role"] != "user":
            turns.pop(0)
        return turns

    def _gate(self, hits: list[Hit], route: Route) -> str:
        best = max((h.bm25 for h in hits), default=0.0)
        if best >= RELEVANCE_MIN_BM25:
            return "ok"
        if route.source == "heuristic" and best == 0:
            return "out_of_scope"
        return "not_found"

    def _disclosure_source(self, lang: Lang) -> list[dict]:
        hits = self.retriever.search(["Duty of Disclosure voidable 提供資料責任 作廢"], k=4, expand=False)
        want = "en" if lang == "en" else "zh-Hant"
        hit = next((h for h in hits if h.chunk.lang == want), hits[0] if hits else None)
        return [self._source(1, hit, lang)] if hit else []

    def _conversation(self, req: TurnRequest, title: str, lang: Lang) -> str:
        if req.conversation_id and self.store.get_conversation(req.conversation_id, req.client_id):
            return req.conversation_id
        return self.store.create_conversation(req.client_id, title or "…", lang)

    def _finish(
        self,
        conversation_id: str,
        answer: str,
        *,
        lang: Lang,
        intent: str,
        mode: str,
        sources: list[dict],
        cited: list[int],
        flags: list[str],
        guardrail: dict | None,
        redactions: list[str],
        unverified: list[str] | None = None,
        metrics: dict,
    ) -> Event:
        payload = {
            "conversation_id": conversation_id,
            "lang": lang,
            "intent": intent,
            "mode": mode,
            "sources": [{**s, "cited": s["n"] in cited} for s in sources],
            "cited": cited,
            "flags": flags,
            "unverified_numbers": unverified or [],
            "guardrail": guardrail,
            "redactions": redactions,
            "metrics": metrics,
        }
        payload["message_id"] = self.store.add_message(conversation_id, "assistant", answer, payload)
        log.info(
            "turn intent=%s mode=%s flags=%s cited=%s total_ms=%s",
            intent,
            mode,
            flags,
            cited,
            metrics.get("total_ms"),
        )
        return "final", {**payload, "answer": answer}

    # -- the turn ----------------------------------------------------------------------
    async def run(self, req: TurnRequest) -> AsyncIterator[Event]:
        t_start = time.perf_counter()
        timings: dict[str, int] = {}
        usage: dict[str, dict] = {}

        # 1. Input guard -----------------------------------------------------------
        t0 = time.perf_counter()
        check = inspect(req.message, self.settings.max_input_chars)
        lang = detect_language(check.text or req.message, fallback=req.ui_lang)
        stored_text = check.text or sanitize(req.message)[: self.settings.max_input_chars]
        conv_id = self._conversation(req, stored_text[:60], lang)
        history = self._history(conv_id)
        self.store.add_message(conv_id, "user", stored_text, {"redactions": check.redactions, "lang": lang})
        timings["input_guard_ms"] = _ms(t0)
        yield "meta", {"conversation_id": conv_id, "lang": lang, "redactions": check.redactions}

        def metrics(**extra: object) -> dict:
            return {
                "timings": timings,
                "total_ms": _ms(t_start),
                "usage": usage,
                "model": self.llm.model if self.llm else None,
                "provider": self.mode,
                **extra,
            }

        def canned(
            key: str,
            stage: str,
            intent: str,
            sources: list[dict] | None = None,
            extra_metrics: dict | None = None,
            **fmt: object,
        ) -> Event:
            """Finish the turn with a reviewed template instead of generated text."""
            text = convert_script(message(key, lang, **fmt), lang)
            sources = sources or []
            is_greeting = key == "greeting"
            return self._finish(
                conv_id,
                text,
                lang=lang,
                intent=intent,
                mode="template" if is_greeting else "guardrail",
                sources=sources,
                cited=[1] if sources else [],
                flags=[] if is_greeting else [f"guardrail:{key}"],
                guardrail=None if is_greeting else {"stage": stage, "verdict": key, "matched": check.matched},
                redactions=check.redactions,
                metrics=metrics(**(extra_metrics or {})),
            )

        if check.blocked:
            verdict = check.verdict or "refused"
            extra = {"max": self.settings.max_input_chars} if verdict == "too_long" else {}
            sources = self._disclosure_source(lang) if verdict == "fraud" else None
            yield canned(verdict, "input", verdict, sources, **extra)
            return

        # 2. Route ------------------------------------------------------------------------
        yield "status", {"stage": "routing"}
        t0 = time.perf_counter()
        route = await self.router.route(check.text, history)
        timings["route_ms"] = _ms(t0)
        if route.source == "llm":
            usage["router"] = vars(route.usage)
        route_info = {
            "intent": route.intent,
            "source": route.source,
            "standalone_question": route.standalone_question,
            "search_queries": route.search_queries,
            "reason": route.reason,
        }

        if route.intent not in ANSWERABLE:
            key = route.intent if route.intent != "greeting" else "greeting"
            sources = self._disclosure_source(lang) if key == "fraud" else None
            fmt = {"docs": self.doc_names(lang)} if key in ("greeting", "out_of_scope") else {}
            yield canned(key, "router", route.intent, sources, {"route": route_info}, **fmt)
            return

        # 3. Retrieve ---------------------------------------------------------------------
        yield "status", {"stage": "retrieving"}
        t0 = time.perf_counter()
        queries = [check.text, route.standalone_question]
        hits = await asyncio.to_thread(self.retriever.search, queries, self.settings.top_k, True, route.search_queries)
        timings["retrieve_ms"] = _ms(t0)
        retrieval_info = {
            "queries": list(dict.fromkeys(q for q in [*queries, *route.search_queries] if q)),
            "dense": self.retriever.dense_enabled,
            "best_bm25": round(max((h.bm25 for h in hits), default=0.0), 2),
        }
        gate = self._gate(hits, route)
        if gate != "ok":
            fmt = {"docs": self.doc_names(lang)} if gate == "out_of_scope" else {}
            yield canned(
                gate, "retrieval", route.intent, None, {"route": route_info, "retrieval": retrieval_info}, **fmt
            )
            return
        sources = [self._source(i + 1, h, lang) for i, h in enumerate(hits)]
        yield "sources", {"sources": sources}

        # 4. Generate ---------------------------------------------------------------------
        yield "status", {"stage": "generating"}
        t0 = time.perf_counter()
        system = answer_system(lang, self.canary)
        mode = self.mode
        if self.llm is None:
            answer = self._extractive(hits, lang, "offline_intro", route.standalone_question or check.text, route)
        else:
            messages = [
                *history,
                {
                    "role": "user",
                    "content": answer_user_message(
                        route.standalone_question or check.text, sources, route.intent == "advice_request"
                    ),
                },
            ]
            # The output guard runs on the finished answer, but deltas reach the browser first.
            # So the stream itself is screened: the last len(canary) chars are held back, which
            # means a canary can never be sent, even split across deltas, before it is detected;
            # on a leak the stream stops and the final event carries the refusal.
            answer, sent, hold = "", 0, len(self.canary)
            try:
                async for ev in self.llm.stream(system, messages):
                    if ev.done:
                        usage["answer"] = vars(ev.usage)
                        break
                    answer += ev.text
                    if leaked_prompt(answer, self.canary, system):
                        log.warning("Prompt leak detected mid-stream; stopping generation")
                        break
                    if len(answer) - hold > sent:
                        yield "delta", {"text": convert_script(answer[sent : len(answer) - hold], lang)}
                        sent = len(answer) - hold
            except LLMRefusal:
                log.warning("Provider refused to answer; returning template")
                yield canned("refused", "generation", route.intent, None, {"route": route_info})
                return
            except LLMError as exc:
                log.error("LLM generation failed: %s", exc)
                mode = "fallback"
                answer = self._extractive(hits, lang, "llm_unavailable", route.standalone_question or check.text, route)
        timings["generate_ms"] = _ms(t0)

        # 5. Output guard -----------------------------------------------------------------
        t0 = time.perf_counter()
        out = check_output(
            answer,
            sources=sources,
            allowed_text=f"{check.text}\n{route.standalone_question}",
            lang=lang,
            canary=self.canary,
            system_prompt=system,
        )
        timings["output_guard_ms"] = _ms(t0)
        guardrail = None
        text = out.text
        if out.leaked:
            text = convert_script(message("prompt_attack", lang), lang)
            guardrail = {"stage": "output", "verdict": "prompt_leak"}
        elif not text:
            text = convert_script(message("not_found", lang), lang)
        yield self._finish(
            conv_id,
            text,
            lang=lang,
            intent=route.intent,
            mode=mode,
            sources=[] if out.leaked else sources,
            cited=out.cited,
            flags=out.flags,
            guardrail=guardrail,
            redactions=check.redactions,
            unverified=out.unverified_numbers,
            metrics=metrics(route=route_info, retrieval=retrieval_info),
        )

    def _extractive(self, hits: list[Hit], lang: Lang, intro: str, query: str, route: Route) -> str:
        # Quote passages the reader can read: skip chunks written only in the other language
        # (citation numbers keep pointing at the original source positions).
        readable = {"en": ("en", "mixed")}.get(lang, ("zh-Hant", "mixed"))
        numbered = [(n, h) for n, h in enumerate(hits, 1) if h.chunk.lang in readable] or list(enumerate(hits, 1))
        terms = [*self.retriever.expansions(query), *route.search_queries]
        lines = [message(intro, lang), ""]
        for n, h in numbered[:3]:
            heading, text = excerpt(h.chunk.text, lang, query, terms=terms)
            # Label the quote with the heading it sits under, not the chunk's first heading.
            title = h.chunk.section.split(" › ")[0]
            label = f"{title} › {heading}" if heading and heading not in title else h.chunk.section
            lines.append(f"- **{label}** — {text} [{n}]")
        return "\n".join(lines)
