"""Language detection and Chinese script conversion.

The tutor answers in the language *and script* of the question:

* ``en``       – English
* ``zh-Hans``  – Simplified Chinese
* ``zh-Hant``  – Traditional Chinese

The source brochure is Traditional Chinese + English, so a Simplified-Chinese
user would otherwise get Traditional characters copied from the sources. We
detect the script with OpenCC (a character that changes under t2s conversion is
Traditional-specific, and vice versa) and convert the final answer with OpenCC
so the script is guaranteed, not just requested in the prompt.
"""

from __future__ import annotations

import re
from functools import cache
from typing import Literal

from opencc import OpenCC

Lang = Literal["en", "zh-Hans", "zh-Hant"]
LANGS: tuple[Lang, ...] = ("en", "zh-Hans", "zh-Hant")

_CJK_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_LATIN_WORD_RE = re.compile(r"[A-Za-z]+")

LANG_NAMES = {
    "en": "English",
    "zh-Hans": "Simplified Chinese (简体中文)",
    "zh-Hant": "Traditional Chinese (繁體中文)",
}


@cache
def _converter(config: str) -> OpenCC:
    return OpenCC(config)


def to_simplified(text: str) -> str:
    return _converter("t2s").convert(text)


def to_traditional(text: str) -> str:
    # "s2t" (not "s2hk"/"s2tw") matches the brochure's glyphs, e.g. 賬戶.
    return _converter("s2t").convert(text)


def is_cjk_char(ch: str) -> bool:
    return bool(_CJK_RE.match(ch))


def chinese_variant(text: str) -> Lang | None:
    """Return zh-Hans / zh-Hant if the text is clearly one script, else None."""
    simp, trad = to_simplified(text), to_traditional(text)
    traditional_only = sum(1 for a, b in zip(text, simp, strict=False) if a != b)
    simplified_only = sum(1 for a, b in zip(text, trad, strict=False) if a != b)
    if traditional_only > simplified_only:
        return "zh-Hant"
    if simplified_only > traditional_only:
        return "zh-Hans"
    return None


def detect_language(text: str, fallback: Lang = "en") -> Lang:
    """Detect the language of a user message.

    CJK characters are compared against English *words* (weighted), so a
    Chinese sentence containing "FLEXI-ULife" is still Chinese, and an English
    sentence quoting "保證可保權益" is still English. For script-neutral Chinese
    (characters identical in both scripts) we fall back to the UI language.
    """
    cjk = len(_CJK_RE.findall(text))
    words = len(_LATIN_WORD_RE.findall(text))
    if cjk == 0 and words == 0:
        return fallback
    if cjk > words * 2.5:
        variant = chinese_variant(text)
        if variant:
            return variant
        return fallback if fallback != "en" else "zh-Hans"
    return "en"


# Clause boundaries for convert_script (kept in the output by the capturing group).
_CLAUSE_SPLIT_RE = re.compile(r"([\s，。；：！？、,.;:!?（）()「」『』【】\[\]])")


@cache
def _foreign_char(ch: str, config: str) -> bool:
    """True if `ch` changes under a character-level `config` conversion."""
    return _converter(config).convert(ch) != ch


def convert_script(text: str, lang: Lang) -> str:
    """Force Chinese text into the requested script (no-op for English).

    Only clauses that contain a character of the *other* script are converted.
    OpenCC's phrase rules are not idempotent on text that is already in the
    target script (s2t turns the brochure's "最多只可" into "最多隻可"), and
    answers quote the brochure verbatim, so those quotes must pass through
    untouched while clauses the model drifted into the wrong script are fixed
    with full phrase context.
    """
    if lang == "en":
        return text
    config = "t2s" if lang == "zh-Hans" else "s2t"
    converter = _converter(config)
    return "".join(
        converter.convert(part) if any(is_cjk_char(c) and _foreign_char(c, config) for c in part) else part
        for part in _CLAUSE_SPLIT_RE.split(text)
    )
