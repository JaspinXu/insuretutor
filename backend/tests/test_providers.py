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
        self.reject: set[str] = set()  # body keys that trigger a 400
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
                {"error": {"type": "invalid_request_error", "message": f"unsupported: {hit}"}}, status_code=400
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
