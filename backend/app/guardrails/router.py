"""Intent routing + query planning.

With an LLM configured, one small structured call does three jobs:
classify intent (scope / safety), rewrite follow-ups into a standalone
question, and write search queries in the documents' own terminology in both
English and Traditional Chinese (closing the cross-lingual gap for BM25).

Without an LLM (offline mode) — or if that call fails — a keyword heuristic
takes over; scope is then decided by the retrieval relevance gate.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from app.lang import to_simplified
from app.llm.base import LLMError, LLMProvider, Usage
from app.prompts import ROUTER_SCHEMA, ROUTER_SYSTEM, router_user_message

log = logging.getLogger(__name__)

INTENTS = tuple(ROUTER_SCHEMA["properties"]["intent"]["enum"])
ANSWERABLE = {"plan_question", "insurance_concept", "advice_request"}

_GREETING_RE = re.compile(
    r"^\s*(hi|hello|hey|thanks|thank you|thx|good (morning|afternoon|evening)|你好|您好|嗨|哈啰|早晨|早安|谢谢|多谢|"
    r"what can you do|who are you|你是谁|你能做什么|你可以做什么|你会什么)[\s!！。.?？,，~]*$",
    re.I,
)
_ADVICE_RE = re.compile(
    r"\b(should i|shall i|is it worth|worth it|recommend|better than|good investment|suitable for me|"
    r"right for me|best (option|choice) for me|which (option|one) should)\b|"
    r"(应该买|应不应该|值不值|值得买|推荐|适合我|划算|好不好|买不买|该不该)",
    re.I,
)


@dataclass
class Route:
    intent: str
    standalone_question: str
    search_queries: list[str] = field(default_factory=list)
    reason: str = ""
    source: str = "heuristic"
    usage: Usage = field(default_factory=Usage)


def heuristic_route(message: str, history: list[dict]) -> Route:
    probe = to_simplified(message.lower())
    if _GREETING_RE.match(probe):
        return Route("greeting", message, reason="greeting pattern")
    intent = "advice_request" if _ADVICE_RE.search(probe) else "plan_question"
    queries = [message]
    # Short follow-ups ("and the Incremental one?") borrow the previous question for retrieval.
    last_user = next((m["content"] for m in reversed(history) if m["role"] == "user"), None)
    if last_user and len(message) < 40:
        queries.append(f"{last_user} {message}")
    return Route(intent, message, queries, reason="keyword heuristic")


class Router:
    def __init__(self, llm: LLMProvider | None, documents: str) -> None:
        self.llm = llm
        self.system = ROUTER_SYSTEM.format(documents=documents)

    async def route(self, message: str, history: list[dict]) -> Route:
        if self.llm is None:
            return heuristic_route(message, history)
        try:
            data, usage = await self.llm.complete_json(
                self.system,
                [{"role": "user", "content": router_user_message(message, history)}],
                ROUTER_SCHEMA,
                max_tokens=600,
            )
            intent = data.get("intent")
            if intent not in INTENTS:
                raise ValueError(f"unknown intent {intent!r}")
            queries = [str(q)[:200] for q in data.get("search_queries") or [] if str(q).strip()][:4]
            standalone = str(data.get("standalone_question") or message)[:600]
            return Route(
                intent=intent,
                standalone_question=standalone,
                search_queries=queries,
                reason=str(data.get("reason", ""))[:200],
                source="llm",
                usage=usage,
            )
        except (LLMError, ValueError, TypeError, KeyError) as exc:
            log.warning("LLM router failed (%s); using heuristic routing", exc)
            route = heuristic_route(message, history)
            route.reason = f"heuristic fallback: {type(exc).__name__}"
            return route
