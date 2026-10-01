"""Intent routing + query planning.

With an LLM configured, one small structured call does three jobs:
classify intent (scope / safety), rewrite follow-ups into a standalone
question, and write search queries in the documents' own terminology in both
English and Traditional Chinese (closing the cross-lingual gap for BM25).

Without an LLM (offline mode) — or if that call fails — a keyword heuristic
takes over: greetings and advice requests by pattern, scope by insurance
vocabulary (plus the retrieval relevance gate downstream).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field

from app.lang import to_simplified
from app.llm.base import LLMError, LLMProvider, Usage
from app.prompts import ROUTER_SCHEMA, ROUTER_SYSTEM, router_user_message
from app.rag.glossary import Glossary

log = logging.getLogger(__name__)

INTENTS = tuple(ROUTER_SCHEMA["properties"]["intent"]["enum"])
ANSWERABLE = {"plan_question", "insurance_concept", "advice_request"}

_GREETING_RE = re.compile(
    r"^\s*(hi|hello|hey|thanks|thank you|thx|good (morning|afternoon|evening)|你好|您好|嗨|哈啰|早晨|早安|谢谢|多谢|"
    r"what can you do|who are you|你是谁|你能做什么|你可以做什么|你会什么)[\s!！。.?？,，~]*$",
    re.I,
)
# Without an LLM, a question is in scope only if it uses insurance vocabulary
# (or a glossary lay term). Matched on the NFKC-folded, Simplified probe.
_DOMAIN_RE = re.compile(
    r"\b(insur\w*|polic(?:y|ies)|plans?|premiums?|benefits?|cover(?:age|ed)?|sum (?:insured|assured)|claims?|"
    r"surrender\w*|withdraw\w*|cash value|account value|interest|bonus\w*|rates?|returns?|fees?|charges?|costs?|"
    r"guarantee\w*|ages?|death|die|dies|illness|disab\w*|unemploy\w*|jobs?|cooling|cancel\w*|refunds?|exclu\w*|"
    r"riders?|supplementary|currenc\w*|pay\w*|lapse\w*|grace|maturity|matures?|beneficiar\w*|underwrit\w*|"
    r"disclos\w*|medical|smok\w*|universal life|flexi\w*|prime saver|yf life|savings?|invest\w*|retire\w*|"
    r"education|protection|insured|owner|appl(?:y|ying|ied|ication|icants?)|conditions?|pre-existing|"
    r"diabet\w*|hypertension|cancer|heart)\b|"
    r"保险|保单|保费|保障|保额|计划|寿险|理赔|赔偿|赔|退保|提取|提款|现金价值|账户价值|利息|派息|回报|收益|利率|费用|"
    r"收费|保证|年龄|身故|死|疾病|病|失业|冷静期|取消|不保|附加|货币|缴费|缴付|期满|宽限|投保|受保|披露|吸烟|万用|"
    r"万通|储蓄|供款|退休|教育",
    re.I,
)
_REFERENTIAL_RE = re.compile(
    r"\b(it|its|that|this|these|those|they|them|one|ones|and|also|what about|how about|same)\b|"
    r"它|这个|那个|这些|那些|呢|还有|另外|同样",
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


def heuristic_route(message: str, history: list[dict], glossary: Glossary | None = None) -> Route:
    probe = to_simplified(unicodedata.normalize("NFKC", message).lower())
    if _GREETING_RE.match(probe):
        return Route("greeting", message, reason="greeting pattern")
    # A short follow-up ("and the Incremental one?", "值不值得買？") inherits the conversation's scope.
    is_follow_up = (
        bool(history) and len(message) < 40 and bool(_REFERENTIAL_RE.search(probe) or _ADVICE_RE.search(probe))
    )
    if not (_DOMAIN_RE.search(probe) or (glossary and glossary.expand(message)) or is_follow_up):
        return Route("out_of_scope", message, reason="no insurance vocabulary")
    intent = "advice_request" if _ADVICE_RE.search(probe) else "plan_question"
    queries = [message]
    # Short follow-ups ("and the Incremental one?") borrow the previous question for retrieval.
    last_user = next((m["content"] for m in reversed(history) if m["role"] == "user"), None)
    if last_user and len(message) < 40:
        queries.append(f"{last_user} {message}")
    return Route(intent, message, queries, reason="keyword heuristic")


class Router:
    def __init__(self, llm: LLMProvider | None, documents: str, glossary: Glossary | None = None) -> None:
        self.llm = llm
        self.system = ROUTER_SYSTEM.format(documents=documents)
        self.glossary = glossary

    async def route(self, message: str, history: list[dict]) -> Route:
        if self.llm is None:
            return heuristic_route(message, history, self.glossary)
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
            route = heuristic_route(message, history, self.glossary)
            route.reason = f"heuristic fallback: {type(exc).__name__}"
            return route
