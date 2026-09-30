"""Provider-neutral LLM interface used by the router and the answer generator."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class StreamEvent:
    """Either a text delta, or (last) the end-of-stream summary."""

    text: str = ""
    done: bool = False
    usage: Usage = field(default_factory=Usage)
    stop_reason: str | None = None


class LLMError(Exception):
    """Provider failure (auth, rate limit, network, bad request). Message is safe to log."""


class LLMRefusal(LLMError):
    """The provider's own safety system declined the request."""


class LLMProvider(ABC):
    provider: str
    model: str
    router_model: str

    @abstractmethod
    async def complete_json(
        self, system: str, messages: list[dict], schema: dict, *, max_tokens: int = 1024
    ) -> tuple[dict, Usage]:
        """Single structured call (used for routing). Returns parsed JSON + usage."""

    @abstractmethod
    def stream(self, system: str, messages: list[dict]) -> AsyncIterator[StreamEvent]:
        """Stream the answer. Yields text deltas, then one event with done=True."""


def parse_json_lenient(text: str) -> dict:
    """Parse a JSON object, tolerating code fences or prose around it."""
    text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise
        data = json.loads(m.group())
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return data
