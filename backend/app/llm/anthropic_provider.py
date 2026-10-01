"""Anthropic (Claude) via the official SDK.

* Routing uses structured outputs (``output_config.format`` with a JSON schema),
  so the router's JSON is schema-valid by construction.
* Answers stream with ``messages.stream``; usage comes from the final message.
* ``output_config.effort`` controls depth/cost on models that support it
  (low for routing, configurable for answers). Sampling parameters such as
  temperature are not sent: current Claude models reject them.
* The server-side refusal fallback (beta) is enabled by default on the models
  that support it: if the model declines on safety grounds, the API retries on
  a fallback model inside the same call. If the account, endpoint or SDK
  rejects the beta (400/403/404/422, or an SDK without the parameter), the
  provider turns it off for the rest of the process and retries without it,
  so an account without the beta still gets generated answers.
* ``stop_reason == "refusal"`` is surfaced as ``LLMRefusal``.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import anthropic
from anthropic import AsyncAnthropic

from app.config import Settings
from app.llm.base import LLMError, LLMProvider, LLMRefusal, StreamEvent, Usage, parse_json_lenient

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
_NO_EFFORT = ("haiku", "sonnet-4-5", "claude-3", "opus-4-1", "opus-4-0", "sonnet-4-0")

ANSWER_MAX_TOKENS = 16000  # thinking tokens count towards this; answers are kept short by the prompt
ROUTER_MAX_TOKENS = 4000


def supports_effort(model: str) -> bool:
    return not any(tag in model for tag in _NO_EFFORT)


# Responses to the beta call that mean "the beta is not available here" rather than "the request
# failed": an unknown parameter (400/422), a beta the account is not enrolled in (403), an endpoint
# or proxy that does not know it (404). Auth, rate-limit and server errors are real failures.
_BETA_REJECTED_STATUS = {400, 403, 404, 422}


def beta_rejected(exc: Exception) -> bool:
    if isinstance(exc, TypeError):  # an SDK version without the `fallbacks` parameter
        return True
    return isinstance(exc, anthropic.APIStatusError) and exc.status_code in _BETA_REJECTED_STATUS


class AnthropicProvider(LLMProvider):
    provider = "anthropic"

    def __init__(self, settings: Settings) -> None:
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=settings.llm_timeout_s, max_retries=2)
        self.model = settings.answer_model
        self.router_model = settings.routing_model
        self.effort = settings.anthropic_effort
        self.router_effort = settings.anthropic_router_effort
        self.fallback_enabled = settings.anthropic_refusal_fallback

    def _output_config(self, model: str, effort: str, fmt: dict | None = None) -> dict | None:
        cfg: dict = {}
        if supports_effort(model):
            cfg["effort"] = effort
        if fmt:
            cfg["format"] = fmt
        return cfg or None

    def _use_fallback(self, model: str) -> bool:
        return self.fallback_enabled and model in FALLBACK_MODELS

    def _disable_fallback(self, exc: Exception) -> None:
        log.warning("Refusal-fallback beta rejected (%s); continuing without it", exc)
        self.fallback_enabled = False

    async def complete_json(
        self, system: str, messages: list[dict], schema: dict, *, max_tokens: int = ROUTER_MAX_TOKENS
    ) -> tuple[dict, Usage]:
        model = self.router_model
        params: dict = {
            "model": model,
            "max_tokens": max(max_tokens, ROUTER_MAX_TOKENS),
            "system": system,
            "messages": messages,
        }
        cfg = self._output_config(model, self.router_effort, {"type": "json_schema", "schema": schema})
        if cfg:
            params["output_config"] = cfg
        try:
            if self._use_fallback(model):
                try:
                    resp = await self.client.beta.messages.create(**params, betas=[FALLBACK_BETA], fallbacks="default")
                except (anthropic.APIStatusError, TypeError) as exc:
                    if not beta_rejected(exc):
                        raise
                    self._disable_fallback(exc)
                    resp = await self.client.messages.create(**params)
            else:
                resp = await self.client.messages.create(**params)
        except anthropic.APIError as exc:
            raise LLMError(f"{type(exc).__name__}: {getattr(exc, 'message', exc)}") from exc

        if resp.stop_reason == "refusal":
            raise LLMRefusal("model declined the routing request")
        text = next((b.text for b in resp.content if b.type == "text"), "")
        usage = Usage(resp.usage.input_tokens, resp.usage.output_tokens)
        try:
            return parse_json_lenient(text), usage
        except ValueError as exc:
            raise LLMError(f"router returned invalid JSON: {exc}") from exc

    async def stream(self, system: str, messages: list[dict]) -> AsyncIterator[StreamEvent]:
        model = self.model
        params: dict = {"model": model, "max_tokens": ANSWER_MAX_TOKENS, "system": system, "messages": messages}
        cfg = self._output_config(model, self.effort)
        if cfg:
            params["output_config"] = cfg

        use_fallback = self._use_fallback(model)
        emitted = False
        try:
            while True:
                try:
                    if use_fallback:
                        manager = self.client.beta.messages.stream(**params, betas=[FALLBACK_BETA], fallbacks="default")
                    else:
                        manager = self.client.messages.stream(**params)
                    async with manager as stream:
                        async for text in stream.text_stream:
                            emitted = True
                            yield StreamEvent(text=text)
                        final = await stream.get_final_message()
                    break
                except (anthropic.APIStatusError, TypeError) as exc:
                    if use_fallback and not emitted and beta_rejected(exc):
                        self._disable_fallback(exc)
                        use_fallback = False
                        continue
                    raise
        except anthropic.APIError as exc:
            raise LLMError(f"{type(exc).__name__}: {getattr(exc, 'message', exc)}") from exc

        if final.stop_reason == "refusal":
            raise LLMRefusal("model declined to answer")
        yield StreamEvent(
            done=True,
            usage=Usage(final.usage.input_tokens, final.usage.output_tokens),
            stop_reason=final.stop_reason,
        )
