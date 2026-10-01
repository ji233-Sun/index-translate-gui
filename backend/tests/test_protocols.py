import asyncio
import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from studio.engine import Generation, StopFilter
from studio.protocols import create_gateway
from studio.settings import Settings

MODEL = "IndexTeam/Index-Translate-2B"
KEY = "test-key-1234567890"
AUTH = {"Authorization": f"Bearer {KEY}"}


class FakeEngine:
    """只替换模型计算；请求解析、鉴权、协议转换和 SSE 均使用真实实现。"""

    model_id = MODEL
    error = None
    finish_reason = "stop"
    stop_sequence = None

    async def begin(self, messages, limit, temperature, top_p, stops):
        if self.error:
            raise self.error
        self.received = (messages, limit, temperature, top_p, stops)
        session = Generation()
        session.input_tokens = 7
        for text in ["Hello", ", world!"]:
            session.queue.put_nowait({"type": "delta", "text": text})
        session.queue.put_nowait(
            {
                "type": "done",
                "input_tokens": 7,
                "output_tokens": 3,
                "finish_reason": self.finish_reason,
                "stop_sequence": self.stop_sequence,
            }
        )
        self.session = session
        return session


@pytest.fixture
def service(tmp_path):
    engine = FakeEngine()
    settings = Settings(model_dir=str(tmp_path), api_key=KEY)
    with TestClient(create_gateway(engine, settings)) as client:
        yield client, engine


def body_for(kind, **extras):
    body = {"model": MODEL, "max_tokens": 32}
    if kind == "responses":
        body.update(input="你好", max_output_tokens=32, store=False)
    elif kind == "completions":
        body["prompt"] = "Translate 你好 into English"
    else:
        body["messages"] = [{"role": "user", "content": "你好"}]
    return {**body, **extras}


def path_for(kind):
    return "/v1/chat/completions" if kind == "chat" else f"/v1/{kind}"


def parse_sse(text):
    return [
        json.loads(line[6:])
        for line in text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]


@pytest.mark.parametrize("kind", ["chat", "completions", "responses", "messages"])
def test_authentication_and_nonstream_contracts(service, kind):
    client, engine = service
    denied = client.post(path_for(kind), json=body_for(kind))
    assert denied.status_code == 401
    assert denied.json()["error"]["type"] == "authentication_error"
    headers = {"x-api-key": KEY, "anthropic-version": "2023-06-01"} if kind == "messages" else AUTH
    response = client.post(path_for(kind), headers=headers, json=body_for(kind))
    assert response.status_code == 200
    payload = response.json()
    assert payload["model"] == MODEL
    if kind == "responses":
        assert payload["output"][0]["content"][0]["text"] == "Hello, world!"
        assert payload["status"] == "completed" and payload["store"] is False
        assert payload["usage"]["total_tokens"] == 10
    elif kind == "messages":
        assert payload["content"] == [{"type": "text", "text": "Hello, world!"}]
        assert payload["stop_reason"] == "end_turn"
        assert payload["usage"] == {"input_tokens": 7, "output_tokens": 3}
    else:
        choice = payload["choices"][0]
        assert (choice["text"] if kind == "completions" else choice["message"]["content"]) == "Hello, world!"
        assert payload["usage"]["prompt_tokens"] == 7
    assert engine.received[1] == 32
    assert engine.session.cancel.is_set()


@pytest.mark.parametrize("kind", ["chat", "completions", "responses", "messages"])
def test_stream_contracts(service, kind):
    client, _ = service
    response = client.post(
        path_for(kind), headers=AUTH, json=body_for(kind, stream=True, stream_options={"include_usage": True})
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    if kind == "responses":
        names = [event["type"] for event in events]
        assert names == [
            "response.created",
            "response.in_progress",
            "response.output_item.added",
            "response.content_part.added",
            "response.output_text.delta",
            "response.output_text.delta",
            "response.output_text.done",
            "response.content_part.done",
            "response.output_item.done",
            "response.completed",
        ]
        assert [e["sequence_number"] for e in events] == list(range(len(events)))
        assert events[-1]["response"]["output"][0]["content"][0]["text"] == "Hello, world!"
    elif kind == "messages":
        assert [e["type"] for e in events] == [
            "message_start",
            "content_block_start",
            "content_block_delta",
            "content_block_delta",
            "content_block_stop",
            "message_delta",
            "message_stop",
        ]
        assert events[0]["message"]["usage"]["input_tokens"] == 7
        assert events[-2]["usage"]["output_tokens"] == 3
    else:
        assert response.text.endswith("data: [DONE]\n\n")
        assert events[-1]["usage"]["total_tokens"] == 10
        assert events[-2]["choices"][0]["finish_reason"] == "stop"
        content = [e["choices"][0] for e in events[:-1]]
        assert (
            "".join(
                c.get("text", "") if kind == "completions" else c["delta"].get("content", "") for c in content
            )
            == "Hello, world!"
        )


@pytest.mark.parametrize(
    "extra",
    [
        {"tools": [{"type": "function"}]},
        {"max_tokens": -1},
        {"stream": "true"},
        {"n": 2},
        {"stop": [""]},
        {"text": "invalid"},
        {"temperature": 8},
    ],
)
def test_invalid_and_unsupported_inputs_fail_explicitly(service, extra):
    client, _ = service
    result = client.post(path_for("chat"), headers=AUTH, json=body_for("chat", **extra))
    assert result.status_code == 400
    assert result.json()["error"]["type"] == "invalid_request_error"


def test_unknown_model_busy_and_stateless_response(service):
    client, engine = service
    assert (
        client.post(path_for("chat"), headers=AUTH, json=body_for("chat", model="unloaded")).status_code
        == 404
    )
    assert (
        client.post(path_for("responses"), headers=AUTH, json=body_for("responses", store=True)).status_code
        == 400
    )
    engine.error = HTTPException(429, "busy")
    assert client.post(path_for("chat"), headers=AUTH, json=body_for("chat")).status_code == 429
    assert client.get("/v1/models", headers=AUTH).json()["data"][0]["id"] == MODEL


def test_messages_system_blocks_and_stop_reason(service):
    client, engine = service
    engine.stop_sequence = "END"
    payload = body_for(
        "messages", system=[{"type": "text", "text": "Translate only"}], stop_sequences=["END"]
    )
    response = client.post(path_for("messages"), headers=AUTH, json=payload)
    assert engine.received[0][0] == {"role": "system", "content": "Translate only"}
    assert response.json()["stop_reason"] == "stop_sequence"
    assert response.json()["stop_sequence"] == "END"


def test_length_limit_is_not_reported_as_complete(service):
    client, engine = service
    engine.finish_reason = "length"
    payload = client.post(path_for("responses"), headers=AUTH, json=body_for("responses")).json()
    assert payload["status"] == "incomplete"
    assert payload["incomplete_details"]["reason"] == "max_output_tokens"
    response = client.post(path_for("responses"), headers=AUTH, json=body_for("responses", stream=True))
    terminal = parse_sse(response.text)[-1]
    assert terminal["type"] == "response.incomplete"
    assert terminal["response"]["incomplete_details"]["reason"] == "max_output_tokens"


def test_streaming_generation_error_is_a_failed_response(service):
    client, engine = service

    async def fail(*_args):
        session = Generation()
        session.queue.put_nowait({"type": "error", "message": "out of memory"})
        return session

    engine.begin = fail
    response = client.post(path_for("responses"), headers=AUTH, json=body_for("responses", stream=True))
    assert parse_sse(response.text)[-1]["type"] == "response.failed"


def test_split_stop_strings_and_cancellation():
    filter_ = StopFilter(["<END>"])
    assert filter_.feed("Hello<E") == "Hello"
    assert filter_.feed("ND>hidden") == ""
    assert filter_.stopped and filter_.stop_sequence == "<END>"
    assert filter_.feed("ignored", final=True) == ""

    async def cancel_on_disconnect():
        session = Generation()
        session.queue.put_nowait({"type": "delta", "text": "hello"})
        iterator = session.events()
        await anext(iterator)
        await iterator.aclose()
        assert session.cancel.is_set()

    asyncio.run(cancel_on_disconnect())
