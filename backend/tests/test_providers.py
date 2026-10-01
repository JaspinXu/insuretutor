"""Provider adapters against a local fake server speaking the OpenAI / Anthropic
wire formats — validates request shapes, streaming parsing and degradation
paths without network access or API keys."""

import asyncio
import json
import socket
import threading
import time

import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from app.config import Settings
from app.llm.anthropic_provider import FALLBACK_BETA, AnthropicProvider
from app.llm.base import LLMRefusal
from app.llm.openai_provider import OpenAIProvider

ROUTE_JSON = {"intent": "plan_question", "standalone_question": "q", "search_queries": ["a", "b"], "reason": "r"}


class FakeServer:
    def __init__(self):
        self.requests: list[dict] = []
        self.reject: set[str] = set()  # body keys that trigger an error response
        self.reject_status = 400
        self.stop_reason = "end_turn"
        app = Starlette(
            routes=[
                Route("/v1/chat/completions", self.openai, methods=["POST"]),
                Route("/v1/messages", self.anthropic, methods=["POST"]),
            ]
        )
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(app, port=self.port, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        while not self.server.started:
            time.sleep(0.02)
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(5)

    async def _record(self, request: Request) -> dict:
        body = await request.json()
        self.requests.append(
            {"path": request.url.path, "query": str(request.url.query), "headers": dict(request.headers), "body": body}
        )
        return body

    def _bad(self, body):
        hit = self.reject & set(body)
        if hit:
            return JSONResponse(
                {"error": {"type": "invalid_request_error", "message": f"unsupported: {hit}"}},
                status_code=self.reject_status,
            )
        return None

    async def openai(self, request: Request):
        body = await self._record(request)
        if bad := self._bad(body):
            return bad
        if not body.get("stream"):
            return JSONResponse(
                {
                    "id": "c1",
                    "object": "chat.completion",
                    "created": 1,
                    "model": body["model"],
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": json.dumps(ROUTE_JSON)},
                        }
                    ],
                    "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
                }
            )

        def gen():
            base = {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": body["model"]}
            for piece in ["Up to ", "365 days", " [1]."]:
                yield f"data: {json.dumps({**base, 'choices': [{'index': 0, 'delta': {'content': piece}, 'finish_reason': None}]})}\n\n"
            yield f"data: {json.dumps({**base, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
            if "stream_options" in body:
                yield f"data: {json.dumps({**base, 'choices': [], 'usage': {'prompt_tokens': 50, 'completion_tokens': 9, 'total_tokens': 59}})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    async def anthropic(self, request: Request):
        body = await self._record(request)
        if bad := self._bad(body):
            return bad
        msg = {"id": "msg_1", "type": "message", "role": "assistant", "model": body["model"], "stop_sequence": None}
        if not body.get("stream"):
            return JSONResponse(
                {
                    **msg,
                    "content": [{"type": "text", "text": json.dumps(ROUTE_JSON)}],
                    "stop_reason": self.stop_reason,
                    "usage": {"input_tokens": 21, "output_tokens": 8},
                }
            )

        def ev(name, data):
            return f"event: {name}\ndata: {json.dumps({'type': name, **data})}\n\n"

        def gen():
            yield ev(
                "message_start",
                {
                    "message": {
                        **msg,
                        "content": [],
                        "stop_reason": None,
                        "usage": {"input_tokens": 60, "output_tokens": 1},
                    }
                },
            )
            yield ev("content_block_start", {"index": 0, "content_block": {"type": "text", "text": ""}})
            for piece in ["Up to ", "365 days", " [1]."]:
                yield ev("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": piece}})
            yield ev("content_block_stop", {"index": 0})
            yield ev(
                "message_delta",
                {"delta": {"stop_reason": self.stop_reason, "stop_sequence": None}, "usage": {"output_tokens": 12}},
            )
            yield ev("message_stop", {})

        return StreamingResponse(gen(), media_type="text/event-stream")


@pytest.fixture
def server():
    with FakeServer() as s:
        yield s


async def collect(provider):
    text, done = "", None
    async for ev in provider.stream("system", [{"role": "user", "content": "hi"}]):
        if ev.done:
            done = ev
        else:
            text += ev.text
    return text, done


def openai_provider(server):
    return OpenAIProvider(
        Settings(openai_api_key="test", openai_base_url=f"http://127.0.0.1:{server.port}/v1", llm_model="m")
    )


def anthropic_provider(server, monkeypatch, **kw):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", f"http://127.0.0.1:{server.port}")
    return AnthropicProvider(Settings(anthropic_api_key="test", llm_provider="anthropic", **kw))


async def json_then_stream(provider, schema=None):
    """Both calls on one event loop, as in the app (clients hold pooled connections)."""
    data, usage = await provider.complete_json("sys", [{"role": "user", "content": "x"}], schema or {})
    text, done = await collect(provider)
    return data, usage, text, done


def test_openai_json_and_stream(server):
    data, usage, text, done = asyncio.run(json_then_stream(openai_provider(server)))
    assert data == ROUTE_JSON and usage.input_tokens == 11
    sent = server.requests[0]["body"]
    assert sent["response_format"] == {"type": "json_object"} and sent["messages"][0]["role"] == "system"
    assert text == "Up to 365 days [1]." and done.usage.output_tokens == 9 and done.stop_reason == "stop"


def test_openai_compatible_server_without_optional_params(server):
    server.reject = {"response_format", "stream_options"}
    data, _, text, done = asyncio.run(json_then_stream(openai_provider(server)))
    assert data == ROUTE_JSON
    assert text == "Up to 365 days [1]." and done.usage.output_tokens == 0  # no usage without stream_options


def test_anthropic_structured_router_call_uses_fallback_beta(server, monkeypatch):
    p = anthropic_provider(server, monkeypatch)
    data, usage = asyncio.run(p.complete_json("sys", [{"role": "user", "content": "x"}], {"type": "object"}))
    assert data == ROUTE_JSON and usage.output_tokens == 8
    req = server.requests[-1]
    assert req["query"] == "beta=true" and FALLBACK_BETA in req["headers"]["anthropic-beta"]
    body = req["body"]
    assert body["model"] == "claude-opus-5-5" and body["fallbacks"] == "default"
    assert body["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": {"type": "object"}}}
    assert "temperature" not in body


def test_anthropic_stream(server, monkeypatch):
    p = anthropic_provider(server, monkeypatch, anthropic_effort="high")
    text, done = asyncio.run(collect(p))
    assert text == "Up to 365 days [1]." and done.usage.output_tokens == 12 and done.stop_reason == "end_turn"
    assert server.requests[-1]["body"]["output_config"] == {"effort": "high"}


def test_anthropic_fallback_beta_rejected_is_disabled(server, monkeypatch):
    server.reject = {"fallbacks"}
    p = anthropic_provider(server, monkeypatch)
    text, _ = asyncio.run(collect(p))
    assert text == "Up to 365 days [1]." and p.fallback_enabled is False
    assert server.requests[-1]["query"] == "" and "fallbacks" not in server.requests[-1]["body"]


@pytest.mark.parametrize("status", [403, 404])
def test_anthropic_fallback_beta_unavailable_is_disabled(server, monkeypatch, status):
    """An account not enrolled in the beta (403) or a proxy that doesn't know it (404) must not
    turn every turn into an LLM failure: the beta is dropped and both calls still succeed."""
    server.reject, server.reject_status = {"fallbacks"}, status
    p = anthropic_provider(server, monkeypatch)
    data, _, text, _ = asyncio.run(json_then_stream(p))
    assert data == ROUTE_JSON and text == "Up to 365 days [1]." and p.fallback_enabled is False
    beta_calls = [r for r in server.requests if r["query"] == "beta=true"]
    assert len(beta_calls) == 1  # tried once, then never again


def test_anthropic_auth_error_is_not_mistaken_for_missing_beta(server, monkeypatch):
    from app.llm.base import LLMError

    server.reject, server.reject_status = {"fallbacks"}, 401
    p = anthropic_provider(server, monkeypatch)
    with pytest.raises(LLMError):
        asyncio.run(collect(p))
    assert p.fallback_enabled is True


def test_anthropic_refusal_raises(server, monkeypatch):
    server.stop_reason = "refusal"
    p = anthropic_provider(server, monkeypatch)
    with pytest.raises(LLMRefusal):
        asyncio.run(collect(p))


def test_anthropic_models_without_effort(server, monkeypatch):
    p = anthropic_provider(server, monkeypatch, llm_model="claude-haiku-4-5")
    asyncio.run(collect(p))
    body = server.requests[-1]["body"]
    assert "output_config" not in body and "fallbacks" not in body


def _soclaas_settings(**kw):
    # _env_file=None and explicit Nones: a developer's own .env or CI env vars must not leak in.
    base = {"llm_provider": "auto", "anthropic_api_key": None, "openai_api_key": None, "soclaas_api_key": "k"}
    return Settings(_env_file=None, **{**base, **kw})


def test_soclaas_key_alone_selects_the_gateway_and_its_default_model():
    s = _soclaas_settings()
    assert s.provider == "soclaas" and s.answer_model == "qwen3.6:35b"
    assert s.compat_api_key == "k" and s.compat_base_url == "https://soclaas-api.comp.nus.edu.sg/v1"
    assert _soclaas_settings(soclaas_url="https://example.org/v1/").compat_base_url == "https://example.org/v1"
    # An explicit OpenAI key still wins in auto mode, and keeps its own base URL.
    s = _soclaas_settings(openai_api_key="o", openai_base_url="https://api.example/v1")
    assert s.provider == "openai" and (s.compat_api_key, s.compat_base_url) == ("o", "https://api.example/v1")


def test_soclaas_chat_goes_through_the_openai_compatible_client(server):
    p = OpenAIProvider(_soclaas_settings(soclaas_url=f"http://127.0.0.1:{server.port}", llm_model="m"))
    data, _, text, _ = asyncio.run(json_then_stream(p))
    assert p.provider == "soclaas" and data == ROUTE_JSON and text == "Up to 365 days [1]."
    assert server.requests[0]["path"] == "/v1/chat/completions"
    assert server.requests[0]["headers"]["authorization"] == "Bearer k"


def test_soclaas_embeddings_default_to_bge_m3():
    from app.rag.embeddings import OpenAIEmbedder, create_embedder

    e = create_embedder(_soclaas_settings(embedding_backend="openai"))
    assert isinstance(e, OpenAIEmbedder) and e.name == "openai:bge-m3"
    assert str(e.client.base_url).startswith("https://soclaas-api.comp.nus.edu.sg/v1")
