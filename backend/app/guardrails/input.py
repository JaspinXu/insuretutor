"""Deterministic input guardrails — run before any model sees the message.

1. Sanitise: strip control and zero-width characters (used to hide injected
   text). Detection runs on an NFKC-folded, lower-cased, Simplified-Chinese
   "probe" copy, so full-width or Traditional spellings can't dodge the
   patterns, while the user's own text (e.g. full-width Chinese punctuation)
   is kept as typed.
2. Redact PII: e-mail, phone numbers, HKID, Singapore NRIC/FIN, mainland ID,
   payment card numbers (Luhn-checked). Redacted text is what gets stored,
   logged and sent to the LLM.
3. Detect high-confidence abuse with bilingual patterns: prompt injection /
   jailbreaks, insurance fraud, and self-harm intent. These short-circuit the
   pipeline (no retrieval, no LLM call). Subtler cases are left to the LLM
   router, so the patterns can stay precise rather than broad.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from app.lang import to_simplified

_INVISIBLE_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f­​-‏‪-‮⁠-⁤﻿]")


def sanitize(text: str) -> str:
    text = _INVISIBLE_RE.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# --- PII ----------------------------------------------------------------------
def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


_PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("HKID", re.compile(r"(?<![A-Za-z0-9])[A-Z]{1,2}\d{6}\s?\(?[0-9A]\)?(?![A-Za-z0-9])")),
    ("NRIC", re.compile(r"(?<![A-Za-z0-9])[STFGM]\d{7}[A-Z](?![A-Za-z0-9])")),
    ("ID_NUMBER", re.compile(r"(?<!\d)\d{6}(?:19|20)\d{2}(?:0[1-9]|1[0-2])\d{5}[\dXx](?![\dA-Za-z])")),
    ("PHONE", re.compile(r"(?<![\d$])(?:\+?86[ -]?)?1[3-9]\d{9}(?!\d)")),
    ("PHONE", re.compile(r"(?<![\d$.,])(?:\+?(?:852|853|65)[ -]?)?[2-9]\d{3}[ -]?\d{4}(?![\d,])")),
]
_CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")


def redact_pii(text: str) -> tuple[str, list[str]]:
    kinds: list[str] = []

    def card(m: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            kinds.append("CARD_NUMBER")
            return "[CARD_NUMBER]"
        return m.group()

    text = _CARD_RE.sub(card, text)
    for kind, pattern in _PII_PATTERNS:
        text, n = pattern.subn(f"[{kind}]", text)
        if n:
            kinds.append(kind)
    return text, sorted(set(kinds))


# --- Abuse patterns (matched on lower-cased, Simplified-normalised text) --------
def _rx(*patterns: str) -> re.Pattern[str]:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.I | re.S)


INJECTION = _rx(
    r"\b(ignore|disregard|forget|override|bypass)\b.{0,30}\b(previous|prior|above|earlier|preceding|all|your|system)\b.{0,20}\b(instructions?|prompts?|rules|directions|guidelines|guardrails|constraints)",
    r"\b(reveal\w*|show\w*|print\w*|repeat\w*|display\w*|output\w*|leak\w*|dump\w*|translat\w*|tell me|what(?:'s| is| are))\b.{0,25}\b(system prompt|initial prompt|hidden prompt|(?:hidden )?developer (?:message|prompt)|your (?:instructions|rules|prompt|guidelines)|the instructions above)",
    r"^\s*(?:system|developer|assistant)\s*:|\bnew (?:system )?instructions\s*[:：-]",
    r"\bsystem prompt\b",
    r"\b(you are now|you're now|from now on,? you (?:are|will)|pretend (?:to be|you are)|roleplay as|role-play as|act as (?:an? )?(?:ai|assistant|chatbot|dan|unfiltered|unrestricted|different|another))\b",
    r"\b(developer mode|jailbreak|jailbroken|do anything now|dan mode)\b",
    r"<\|?(?:im_start|system|endoftext)\|?>|\[/?(?:system|inst)\]|###\s*(?:system|instruction)",
    r"(忽略|无视|忘记|忘掉|绕过|跳过).{0,10}(之前|以上|上面|前面|先前|所有|全部|你的|系统).{0,6}(指令|指示|提示|规则|设定|要求|限制)",
    r"(显示|输出|告诉我|打印|泄露|重复|给我看).{0,10}(系统提示|提示词|系统指令|初始指令|你的指令|你的规则|你的设定)",
    r"系统提示词|系统提示",
    r"(你现在是|从现在开始你是|从现在起你是|假装你是|越狱|开发者模式)",
)

FRAUD = _rx(
    r"\b(hide|conceal|not (?:tell|disclose|mention|declare)|without (?:telling|disclosing|declaring)|lie (?:about|on)|fake|forge|falsify|fabricate|cover up|misrepresent)\b.{0,40}\b(condition|illness|disease|diagnos\w*|smok\w*|medical|health|history|application|claim|death|document|records?|age|income|cancer)",
    r"\b(fake|stage|faking|staging)\b.{0,10}\b(my |a |the )?(death|illness|disability|unemployment|redundancy|accident)",
    r"\binsurance fraud\b|\bcheat (?:the|an) insurer\b|\bscam (?:the |an )?insur",
    r"(隐瞒|瞒报|谎报|伪造|编造|篡改|虚报|假报|假装|装作|不告诉|不申报|不如实).{0,12}(病|病史|吸烟|抽烟|健康|体检|诊断|年龄|收入|死亡|失业|理赔|申请|资料|癌)",
    r"骗保|假死|保险诈骗|诈骗保险|骗取保险",
)

SELF_HARM = _rx(
    r"\b(kill myself|killing myself|end my (?:own )?life|take my (?:own )?life|want to die|wanna die|suicidal|end it all|hurt myself|harm myself|better off dead|no reason to live|(?:don'?t|do not) want to (?:live|be alive))\b",
    r"\bif i (?:commit|committed|comitted) suicide\b",
    r"(我|我想|我要|想要|打算|准备).{0,6}(自杀|自尽|轻生|寻死|去死|结束(?:我的|自己的)?生命)",
    r"不想活|活不下去|想死了",
)


@dataclass
class InputCheck:
    text: str  # sanitised + PII-redacted
    redactions: list[str] = field(default_factory=list)
    verdict: str | None = None  # None = continue; else a guardrail outcome key
    matched: str | None = None

    @property
    def blocked(self) -> bool:
        return self.verdict is not None


def inspect(raw: str, max_chars: int) -> InputCheck:
    text = sanitize(raw)
    if not text:
        return InputCheck(text="", verdict="empty")
    if len(text) > max_chars:
        return InputCheck(text=text[:max_chars], verdict="too_long")
    text, redactions = redact_pii(text)
    probe = to_simplified(unicodedata.normalize("NFKC", text).lower())
    for verdict, pattern in (("self_harm", SELF_HARM), ("prompt_attack", INJECTION), ("fraud", FRAUD)):
        m = pattern.search(probe)
        if m:
            return InputCheck(text=text, redactions=redactions, verdict=verdict, matched=m.group(0)[:80])
    return InputCheck(text=text, redactions=redactions)
