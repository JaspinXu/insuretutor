from __future__ import annotations

from app.config import Settings
from app.llm.base import LLMProvider


def create_llm(settings: Settings) -> LLMProvider | None:
    """The configured provider, or None for offline (extractive) mode."""
    if settings.provider == "anthropic":
        from app.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(settings)
    if settings.provider in ("openai", "soclaas"):
        from app.llm.openai_provider import OpenAIProvider

        return OpenAIProvider(settings)
    return None
