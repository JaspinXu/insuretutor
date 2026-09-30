"""Deterministic output guardrails — run on every generated answer.

* Citations: normalise "[1, 3]" -> "[1][3]", drop citations to sources that
  were not provided, and flag answers that cite nothing.
* Numeric grounding: every figure in the answer (percentages, amounts, ages,
  periods) must appear in the cited sources — or in the user's own question.
  Figures that don't are flagged to the user as "could not be verified"
  (they may be calculations, or hallucinations). In insurance, a wrong number
  is the most harmful kind of wrong answer, and this check is cheap and exact.
* Prompt leakage: the system prompt carries a random canary; if it (or a
  verbatim slice of the rules) shows up in the output, the answer is replaced.
* Script: Chinese answers are converted to the user's script (Simplified or
  Traditional) with OpenCC, since models drift towards the sources' script.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.lang import Lang, convert_script

_CITE_RE = re.compile(r"\[(\d{1,2}(?:\s*[,，、]\s*\d{1,2})*)\]")
_NUMBER_RE = re.compile(r"(?<![\w.])\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.,])\d+(?:\.\d+)?")
_ORDINAL_LINE_RE = re.compile(r"^\s*\d+[.)、]\s", re.M)

_EN_NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
}  # fmt: skip
_ZH_DIGITS = {"零": 0, "一": 1, "二": 2, "兩": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_ZH_NUMBER_RE = re.compile(r"[零一二兩两三四五六七八九十]+")

MIN_CHECKED_INTEGER = 10  # small counts ("2 times", "3 years") are too ambiguous to check


def _canon(num: str) -> str:
    num = num.replace(",", "")
    if "." in num:
        num = num.rstrip("0").rstrip(".")
    return num


def _zh_to_int(s: str) -> int | None:
    if s == "十":
        return 10
    if "十" in s:
        tens, _, ones = s.partition("十")
        t = _ZH_DIGITS.get(tens, 1) if tens else 1
        o = _ZH_DIGITS.get(ones, 0) if ones else 0
        return t * 10 + o if (not tens or tens in _ZH_DIGITS) and (not ones or ones in _ZH_DIGITS) else None
    if len(s) == 1:
        return _ZH_DIGITS.get(s)
    return None


def numbers_in(text: str, *, spelled: bool = False) -> set[str]:
    found = {_canon(m) for m in _NUMBER_RE.findall(text)}
    if spelled:
        for word in re.findall(r"[a-z]+", text.lower()):
            if word in _EN_NUMBER_WORDS:
                found.add(str(_EN_NUMBER_WORDS[word]))
        for zh in _ZH_NUMBER_RE.findall(text):
            v = _zh_to_int(zh)
            if v is not None:
                found.add(str(v))
    return found


def _checkable(num: str) -> bool:
    return "." in num or int(num) >= MIN_CHECKED_INTEGER


@dataclass
class OutputCheck:
    text: str
    cited: list[int] = field(default_factory=list)
    invalid_citations: list[int] = field(default_factory=list)
    unverified_numbers: list[str] = field(default_factory=list)
    leaked: bool = False

    @property
    def flags(self) -> list[str]:
        flags = []
        if self.leaked:
            flags.append("blocked_prompt_leak")
        if self.invalid_citations:
            flags.append("invalid_citations_removed")
        if not self.cited and not self.leaked:
            flags.append("no_citations")
        if self.unverified_numbers:
            flags.append("unverified_numbers")
        return flags


def normalize_citations(text: str, n_sources: int) -> tuple[str, list[int], list[int]]:
    cited: list[int] = []
    invalid: list[int] = []

    def repl(m: re.Match[str]) -> str:
        out = []
        for part in re.split(r"\s*[,，、]\s*", m.group(1)):
            n = int(part)
            if 1 <= n <= n_sources:
                out.append(f"[{n}]")
                if n not in cited:
                    cited.append(n)
            else:
                invalid.append(n)
        return "".join(out)

    return _CITE_RE.sub(repl, text), cited, invalid


def leaked_prompt(text: str, canary: str, system_prompt: str) -> bool:
    if canary and canary in text:
        return True
    # Any long verbatim line of the system prompt appearing in the answer.
    for line in system_prompt.splitlines():
        line = line.strip()
        if len(line) > 60 and line[:60] in text:
            return True
    return False


def check_output(
    text: str,
    *,
    sources: list[dict],
    allowed_text: str,
    lang: Lang,
    canary: str,
    system_prompt: str,
) -> OutputCheck:
    """`allowed_text`: user-supplied text whose numbers are legitimately reusable."""
    if leaked_prompt(text, canary, system_prompt):
        return OutputCheck(text="", leaked=True)

    text, cited, invalid = normalize_citations(text, len(sources))
    text = convert_script(text, lang).strip()

    evidence = [s for s in sources if s["n"] in cited] or sources
    supported = set().union(*(numbers_in(s["text"], spelled=True) for s in evidence)) if evidence else set()
    supported |= numbers_in(allowed_text, spelled=True)
    body = _CITE_RE.sub(" ", _ORDINAL_LINE_RE.sub(" ", text))
    unverified = sorted(
        (n for n in numbers_in(body) if _checkable(n) and n not in supported),
        key=lambda n: float(n),
    )
    return OutputCheck(text=text, cited=cited, invalid_citations=invalid, unverified_numbers=unverified)
