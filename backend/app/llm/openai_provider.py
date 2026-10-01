"""OpenAI and OpenAI-compatible chat APIs (OpenAI, NUS SoCLaaS, DeepSeek, Qwen/DashScope, Ollama...).

Compatible servers differ in which optional parameters they accept, so each
call degrades step by step on a 400: drop JSON mode / usage streaming, then
switch to the reasoning-model parameter style (max_completion_tokens, no
temperature).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import openai
from openai import AsyncOpenAI

from app.config import Settings
from app.llm.base import LLMError, LLMProvider, StreamEvent, Usage, parse_json_lenient

log = logging.getLogger(__name__)


def _variants(kwargs: dict, optional: tuple[str, ...]) -> list[dict]:
    base = dict(kwargs)
    plain = {k: v for k, v in base.items() if k not in optional}
    reasoning = {k: v for k, v in plain.items() if k != "temperature"}
    if "max_tokens" in reasoning:
        reasoning["max_completion_tokens"] = reasoning.pop("max_tokens")
    out = [base]
    for v in (plain, reasoning):
        if v not in out:
            out.append(v)
    return out


class OpenAIProvider(LLMProvider):
    provider = "openai"

    def __init__(self, settings: Settings) -> None:
        self.provider = "soclaas" if settings.provider == "soclaas" else "openai"
        self.client = AsyncOpenAI(
            api_key=settings.compat_api_key,
            base_url=settings.compat_base_url or None,
            timeout=settings.llm_timeout_s,
            max_retries=2,
        )
        self.model = settings.answer_model
        self.router_model = settings.routing_model
        self.temperature = settings.openai_temperature
        self.max_tokens = settings.openai_max_tokens

    async def _create(self, kwargs: dict, optional: tuple[str, ...]):
        last: Exception | None = None
        for variant in _variants(kwargs, optional):
            try:
                return await self.client.chat.completions.create(**variant)
            except openai.BadRequestError as exc:
                last = exc
                log.info("OpenAI-compatible API rejected parameters (%s); retrying with fewer", exc.message)
            except openai.APIError as exc:
                raise LLMError(f"{type(exc).__name__}: {getattr(exc, 'message', exc)}") from exc
        raise LLMError(f"BadRequestError: {getattr(last, 'message', last)}")

    async def complete_json(
        self, system: str, messages: list[dict], schema: dict, *, max_tokens: int = 1024
    ) -> tuple[dict, Usage]:
        resp = await self._create(
            {
                "model": self.router_model,
                "messages": [{"role": "system", "content": system}, *messages],
                "temperature": 0,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
            },
            optional=("response_format",),
        )
        text = resp.choices[0].message.content or ""
        usage = Usage(resp.usage.prompt_tokens, resp.usage.completion_tokens) if resp.usage else Usage()
        try:
            return parse_json_lenient(text), usage
        except ValueError as exc:
            raise LLMError(f"router returned invalid JSON: {exc}") from exc

    async def stream(self, system: str, messages: list[dict]) -> AsyncIterator[StreamEvent]:
        stream = await self._create(
            {
                "model": self.model,
                "messages": [{"role": "system", "content": system}, *messages],
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "stream": True,
                "stream_options": {"include_usage": True},
            },
            optional=("stream_options",),
        )
        usage, stop = Usage(), None
        try:
            async for chunk in stream:
                if chunk.usage:
                    usage = Usage(chunk.usage.prompt_tokens, chunk.usage.completion_tokens)
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                if choice.finish_reason:
                    stop = choice.finish_reason
                if choice.delta and choice.delta.content:
                    yield StreamEvent(text=choice.delta.content)
        except openai.APIError as exc:
            raise LLMError(f"{type(exc).__name__}: {getattr(exc, 'message', exc)}") from exc
        yield StreamEvent(done=True, usage=usage, stop_reason=stop)
