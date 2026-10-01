import json
import secrets
import time
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, StrictBool, ValidationError

from studio.settings import Settings


class Options(BaseModel):
    model: str = Field(min_length=1)
    stream: StrictBool = False
    max_tokens: int | None = Field(default=None, ge=1, le=8192, strict=True)
    max_completion_tokens: int | None = Field(default=None, ge=1, le=8192, strict=True)
    max_output_tokens: int | None = Field(default=None, ge=1, le=8192, strict=True)
    temperature: float = Field(default=0, ge=0, le=2, allow_inf_nan=False)
    top_p: float = Field(default=1, gt=0, le=1, allow_inf_nan=False)


def text_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        result = []
        for part in value:
            if not isinstance(part, dict) or part.get("type") not in {"text", "input_text", "output_text"}:
                raise ValueError("仅支持文本内容，不支持图片、音频或工具调用")
            if not isinstance(part.get("text"), str):
                raise ValueError("文本内容必须是字符串")
            result.append(part["text"])
        return "\n".join(result)
    raise ValueError("content 必须是字符串或文本块数组")


def messages_for(body: dict, kind: str) -> list[dict] | str:
    if kind == "completions":
        if not isinstance(body.get("prompt"), str) or not body["prompt"].strip():
            raise ValueError("prompt 必须是非空字符串；不支持批量或 token ID 输入")
        return body["prompt"]
    raw = body.get("input") if kind == "responses" else body.get("messages")
    if kind == "responses" and isinstance(raw, str):
        raw = [{"role": "user", "content": raw}]
    if not isinstance(raw, list) or not raw:
        raise ValueError("请提供非空的 messages / input")
    messages, system = [], []
    instruction = body.get("instructions") if kind == "responses" else body.get("system")
    if instruction:
        system.append(text_content(instruction))
    for message in raw:
        if not isinstance(message, dict) or message.get("type", "message") != "message":
            raise ValueError("仅支持文本消息，不支持已存储消息引用或工具结果")
        if message.get("tool_calls") or message.get("function_call"):
            raise ValueError("此翻译服务不支持工具调用")
        role = message.get("role")
        if role not in {"system", "developer", "user", "assistant"}:
            raise ValueError("不支持的消息角色")
        content = text_content(message.get("content"))
        if role in {"system", "developer"}:
            system.append(content)
        else:
            messages.append({"role": role, "content": content})
    if not any(m["role"] == "user" and m["content"].strip() for m in messages):
        raise ValueError("需要至少一条非空用户消息")
    return ([{"role": "system", "content": "\n\n".join(system)}] if system else []) + messages


def validate_features(body: dict) -> list[str]:
    for field in (
        "tools",
        "functions",
        "function_call",
        "previous_response_id",
        "store",
        "background",
        "logprobs",
        "top_logprobs",
        "echo",
        "suffix",
        "logit_bias",
    ):
        if body.get(field):
            raise ValueError(f"本地文本翻译服务不支持 {field}")
    if body.get("tool_choice") not in (None, "auto", "none"):
        raise ValueError("本地文本翻译服务不支持工具调用")
    if body.get("thinking") not in (None, {"type": "disabled"}):
        raise ValueError("本地文本翻译服务不支持 thinking")
    for field in ("text", "stream_options"):
        if field in body and not isinstance(body[field], dict):
            raise ValueError(f"{field} 必须是 JSON 对象")
    if body.get("n", 1) != 1 or body.get("best_of", 1) != 1:
        raise ValueError("每次请求仅支持一个结果")
    if body.get("response_format", {"type": "text"}) != {"type": "text"}:
        raise ValueError("仅支持 text 响应格式")
    if body.get("text", {}).get("format", {"type": "text"}) != {"type": "text"}:
        raise ValueError("仅支持 text 响应格式")
    stops = body.get("stop_sequences", body.get("stop", [])) or []
    if isinstance(stops, str):
        stops = [stops]
    if (
        not isinstance(stops, list)
        or len(stops) > 4
        or not all(isinstance(s, str) and 0 < len(s) <= 200 for s in stops)
    ):
        raise ValueError("停止字符串必须是最多 4 个非空字符串，每个不超过 200 字符")
    return stops


def usage_of(done: dict, kind: str) -> dict:
    if kind in {"messages", "responses"}:
        result = {"input_tokens": done["input_tokens"], "output_tokens": done["output_tokens"]}
    else:
        result = {"prompt_tokens": done["input_tokens"], "completion_tokens": done["output_tokens"]}
    if kind != "messages":
        result["total_tokens"] = done["input_tokens"] + done["output_tokens"]
    if kind == "responses":
        result.update(
            input_tokens_details={"cached_tokens": 0}, output_tokens_details={"reasoning_tokens": 0}
        )
    return result


def anthropic_stop(done: dict) -> str:
    return (
        "stop_sequence"
        if done.get("stop_sequence")
        else "max_tokens"
        if done["finish_reason"] == "length"
        else "end_turn"
    )


def response_item(item_id: str, text: str, status: str = "completed") -> dict:
    return {
        "id": item_id,
        "type": "message",
        "status": status,
        "role": "assistant",
        "content": [{"type": "output_text", "text": text, "annotations": [], "logprobs": []}],
    }


def response_object(response_id, item_id, model, created, text, done=None, options=None):
    status = (
        "incomplete" if done and done["finish_reason"] == "length" else "completed" if done else "in_progress"
    )
    return {
        "id": response_id,
        "object": "response",
        "created_at": created,
        "completed_at": int(time.time()) if done else None,
        "status": status,
        "model": model,
        "output": [response_item(item_id, text, status)] if done else [],
        "usage": usage_of(done, "responses") if done else None,
        "error": None,
        "incomplete_details": {"reason": "max_output_tokens"} if status == "incomplete" else None,
        "store": False,
        "tools": [],
        "tool_choice": "none",
        "parallel_tool_calls": False,
        "previous_response_id": None,
        "instructions": None,
        "metadata": {},
        "text": {"format": {"type": "text"}},
        "truncation": "disabled",
        "temperature": options.temperature if options else 0,
        "top_p": options.top_p if options else 1,
    }


def sse(data: dict | str, event: str | None = None) -> str:
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return (f"event: {event}\n" if event else "") + f"data: {payload}\n\n"


def error_payload(message: str, status: int, anthropic: bool) -> dict:
    kind = {
        400: "invalid_request_error",
        401: "authentication_error",
        404: "not_found_error",
        429: "rate_limit_error",
        503: "overloaded_error",
    }.get(status, "api_error")
    error = {"type": kind, "message": message}
    return (
        {"type": "error", "error": error}
        if anthropic
        else {"error": {**error, "param": None, "code": str(status)}}
    )


def create_gateway(engine, settings: Settings) -> FastAPI:
    app = FastAPI(title="Index Translate API", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        if request.url.path != "/health":
            authorization = request.headers.get("authorization", "")
            bearer = authorization[7:] if authorization.lower().startswith("bearer ") else ""
            supplied = request.headers.get("x-api-key", "") if request.url.path == "/v1/messages" else ""
            if not secrets.compare_digest((supplied or bearer).encode(), settings.api_key.encode()):
                return JSONResponse(
                    error_payload("访问密钥无效", 401, request.url.path == "/v1/messages"), 401
                )
        length = request.headers.get("content-length", "0")
        if not length.isdecimal() or int(length) > 1024 * 1024:
            return JSONResponse(
                error_payload("请求体超过 1 MiB", 400, request.url.path == "/v1/messages"), 400
            )
        return await call_next(request)

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        return JSONResponse(
            error_payload(str(error.detail), error.status_code, request.url.path == "/v1/messages"),
            error.status_code,
        )

    @app.exception_handler(ValueError)
    async def invalid_request(request, error):
        message = "请求参数不符合接口要求" if isinstance(error, ValidationError) else str(error)
        return JSONResponse(error_payload(message, 400, request.url.path == "/v1/messages"), 400)

    @app.get("/health")
    async def health():
        return {"status": "ready" if engine.model_id else "stopped"}

    @app.get("/v1/models")
    async def models():
        return {
            "object": "list",
            "data": [{"id": engine.model_id, "object": "model", "created": 0, "owned_by": "IndexTeam"}],
        }

    async def generate(request: Request, kind: str):
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("请求体必须是 JSON 对象")
        options = Options.model_validate(body)
        if options.model not in {engine.model_id, engine.model_id.split("/")[-1], "index-translate"}:
            raise HTTPException(404, "请求模型未加载，请通过 /v1/models 获取当前模型")
        stops = validate_features(body)
        messages = messages_for(body, kind)
        if kind == "messages" and options.max_tokens is None:
            raise ValueError("Anthropic Messages 要求提供 max_tokens")
        limit = (
            options.max_output_tokens
            or options.max_completion_tokens
            or options.max_tokens
            or settings.max_tokens
        )
        session = await engine.begin(messages, limit, options.temperature, options.top_p, stops)
        response_id = (
            "resp_"
            if kind == "responses"
            else "msg_"
            if kind == "messages"
            else "cmpl-"
            if kind == "completions"
            else "chatcmpl-"
        ) + uuid4().hex
        item_id, created = "msg_" + uuid4().hex, int(time.time())

        def chat_chunk(delta=None, finish=None, usage=None):
            choice = {"index": 0, "finish_reason": finish}
            choice["text" if kind == "completions" else "delta"] = (
                delta if delta is not None else ("" if kind == "completions" else {})
            )
            result = {
                "id": response_id,
                "object": "text_completion" if kind == "completions" else "chat.completion.chunk",
                "created": created,
                "model": engine.model_id,
                "choices": [] if usage else [choice],
            }
            if usage:
                result["usage"] = usage
            return result

        async def stream():
            text, done, sequence = "", None, 0

            def event(name, **values):
                nonlocal sequence
                payload = {"type": name, **values}
                if kind == "responses":
                    payload["sequence_number"] = sequence
                    sequence += 1
                return sse(payload, name)

            position = {"item_id": item_id, "output_index": 0, "content_index": 0}
            try:
                if kind == "responses":
                    initial = response_object(
                        response_id, item_id, engine.model_id, created, "", options=options
                    )
                    yield event("response.created", response=initial)
                    yield event("response.in_progress", response=initial)
                    yield event(
                        "response.output_item.added",
                        output_index=0,
                        item={
                            "id": item_id,
                            "type": "message",
                            "role": "assistant",
                            "status": "in_progress",
                            "content": [],
                        },
                    )
                    yield event(
                        "response.content_part.added",
                        **position,
                        part={"type": "output_text", "text": "", "annotations": []},
                    )
                elif kind == "messages":
                    yield event(
                        "message_start",
                        message={
                            "id": response_id,
                            "type": "message",
                            "role": "assistant",
                            "model": engine.model_id,
                            "content": [],
                            "stop_reason": None,
                            "stop_sequence": None,
                            "usage": {"input_tokens": session.input_tokens, "output_tokens": 0},
                        },
                    )
                    yield event("content_block_start", index=0, content_block={"type": "text", "text": ""})
                else:
                    yield sse(
                        chat_chunk("" if kind == "completions" else {"role": "assistant", "content": ""})
                    )
                async for part in session.events():
                    if part["type"] == "done":
                        done = part
                        break
                    text += part["text"]
                    if kind == "responses":
                        yield event("response.output_text.delta", **position, delta=part["text"], logprobs=[])
                    elif kind == "messages":
                        yield event(
                            "content_block_delta", index=0, delta={"type": "text_delta", "text": part["text"]}
                        )
                    else:
                        yield sse(
                            chat_chunk(part["text"] if kind == "completions" else {"content": part["text"]})
                        )
                if kind == "responses":
                    response = response_object(
                        response_id, item_id, engine.model_id, created, text, done, options
                    )
                    yield event("response.output_text.done", **position, text=text, logprobs=[])
                    yield event(
                        "response.content_part.done", **position, part=response["output"][0]["content"][0]
                    )
                    yield event("response.output_item.done", output_index=0, item=response["output"][0])
                    yield event("response." + response["status"], response=response)
                elif kind == "messages":
                    yield event("content_block_stop", index=0)
                    yield event(
                        "message_delta",
                        delta={
                            "stop_reason": anthropic_stop(done),
                            "stop_sequence": done.get("stop_sequence"),
                        },
                        usage={"output_tokens": done["output_tokens"]},
                    )
                    yield event("message_stop")
                else:
                    yield sse(chat_chunk(finish=done["finish_reason"]))
                    if body.get("stream_options", {}).get("include_usage"):
                        yield sse(chat_chunk(usage=usage_of(done, kind)))
                    yield sse("[DONE]")
            except Exception as error:
                if kind == "responses":
                    failed = response_object(
                        response_id, item_id, engine.model_id, created, text, options=options
                    )
                    failed.update(status="failed", error={"code": "server_error", "message": str(error)})
                    yield event("response.failed", response=failed)
                else:
                    yield sse(
                        error_payload(str(error), 500, kind == "messages"),
                        "error" if kind == "messages" else None,
                    )
                if kind in {"chat", "completions"}:
                    yield sse("[DONE]")
            finally:
                session.cancel.set()

        if options.stream:
            return StreamingResponse(
                stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        text, done = "", None
        try:
            async for part in session.events():
                if await request.is_disconnected():
                    raise HTTPException(499, "客户端已断开")
                if part["type"] == "delta":
                    text += part["text"]
                else:
                    done = part
        except RuntimeError as error:
            raise HTTPException(500, str(error)) from error
        finally:
            session.cancel.set()
        if kind == "responses":
            return response_object(response_id, item_id, engine.model_id, created, text, done, options)
        if kind == "messages":
            return {
                "id": response_id,
                "type": "message",
                "role": "assistant",
                "model": engine.model_id,
                "content": [{"type": "text", "text": text}],
                "usage": usage_of(done, kind),
                "stop_sequence": done.get("stop_sequence"),
                "stop_reason": anthropic_stop(done),
            }
        return {
            "id": response_id,
            "object": "text_completion" if kind == "completions" else "chat.completion",
            "created": created,
            "model": engine.model_id,
            "usage": usage_of(done, kind),
            "choices": [
                {
                    "index": 0,
                    "finish_reason": done["finish_reason"],
                    "logprobs": None,
                    **(
                        {"text": text}
                        if kind == "completions"
                        else {"message": {"role": "assistant", "content": text}}
                    ),
                }
            ],
        }

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        return await generate(request, "chat")

    @app.post("/v1/completions")
    async def completions(request: Request):
        return await generate(request, "completions")

    @app.post("/v1/responses")
    async def responses(request: Request):
        return await generate(request, "responses")

    @app.post("/v1/messages")
    async def messages(request: Request):
        return await generate(request, "messages")

    return app
