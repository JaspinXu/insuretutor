"""Bilingual tokenizer for lexical (BM25) retrieval.

* Chinese is normalised to Simplified before tokenising, so a Simplified query
  matches the Traditional brochure (t2s is many-to-one, hence more robust than
  s2t), and split into overlapping character bigrams — the standard approach
  for Chinese BM25 without a word segmenter.
* English is lower-cased, stop-word filtered and lightly stemmed.
* Numbers keep their value ("50,000" -> "50000", "2.5" stays "2.5").
"""

from __future__ import annotations

import re
import unicodedata

from app.lang import to_simplified

_TOKEN_RE = re.compile(r"[㐀-鿿]+|[a-z]+|\d+(?:\.\d+)?")
_THOUSANDS_RE = re.compile(r"(?<=\d),(?=\d{3}\b)")

STOPWORDS = frozenset(
    """a an and are as at be been but by can could did do does for from had has have how i if in
    into is it its me my of on or our should so than that the their them then there these they this
    to was we were what when where which who why will with would you your about any all also am
    i'm i've please tell know want need much many get give let us after before over under up out""".split()  # noqa: SIM905
)


def stem(word: str) -> str:
    """Tiny suffix stripper; consistency between query and corpus matters more than linguistics."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 5 and word.endswith("ing"):
        return word[:-3]
    if len(word) > 4 and word.endswith("ed") and not word.endswith("eed"):
        return word[:-2]
    if len(word) > 3 and word.endswith("es") and word[-3] in "sxz":
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = _THOUSANDS_RE.sub("", text)
    return to_simplified(text)


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for run in _TOKEN_RE.findall(normalize(text)):
        first = run[0]
        if "㐀" <= first <= "鿿":
            if len(run) == 1:
                tokens.append(run)
            else:
                tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
        elif first.isdigit():
            tokens.append(run)
        elif run not in STOPWORDS and len(run) > 1:
            tokens.append(stem(run))
    return tokens
