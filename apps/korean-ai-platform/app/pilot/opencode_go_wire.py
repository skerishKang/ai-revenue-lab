"""OpenCode Go fixed-model protocol boundary (coding-agent traffic only).

The six exact owner-approved model IDs are routed by their *documented*
protocol; no attempt is made to send Responses or Anthropic Messages models
through a generic chat-completions endpoint. Activation is independently gated
by the canonical model/provider enabled flags. Never log secret values.
"""
from __future__ import annotations

import json
import math
import re
import time
import uuid
from typing import Any, AsyncIterator

import httpx

from .b14_timeout_policy import build_provider_http_timeout
from .errors import InvalidRequest, MalformedUpstreamResponse, PilotNotConfigured, UpstreamResponseTooLarge, UpstreamServerError, UpstreamTimeout
from .stream_types import StreamEvent, StreamUsage
from .upstream_answer_contract import UpstreamEmptyAnswer

# Owner-approved Go models; additions must keep their official wire protocol.
_WIRE = {
    "longcat-2.5-preview-free": "chat/completions",
    "step-5-preview-free": "chat/completions",
    "muse-spark-1.3-contributor": "responses",
    "muse-spark-1.2-contributor": "responses",
    "gpt-6-luna": "responses",
    "claude-haiku-5-5": "messages",
}
_UA = "padiem-claw-coding-agent/1.0"
# B54 conversation history mints chat_ + uuid4().hex after owner-scoped D1
# readback. This grammar excludes request IDs (b14req_), P01 Claw run IDs,
# and arbitrary user-provided session tokens. Grammar is NOT ownership proof:
# the caller must still authenticate and revalidate the conversation in B54.
_SESSION = re.compile(r"^chat_[0-9a-f]{32}$")


def prepare_go_request(
    *, model_id: str, upstream_model: str, messages: list[dict[str, str]],
    session_id: str | None, max_tokens: int | None = None,
    temperature: float | None = None, streaming: bool = False,
) -> tuple[str, dict[str, Any], dict[str, str]]:
    """Non-secret request shape. session_id must be an owner-revalidated B54 chat_ conversation ID.

    A B14 request ID is *not* a valid replacement for a stable conversation ID.
    Refuse the request rather than make an apparently working but noncompliant
    per-request session header or fake conversation.
    """
    if _WIRE.get(upstream_model) is None or model_id != "opencode-go/" + upstream_model:
        raise InvalidRequest("OpenCode Go model is not in the owner allowlist.")
    if not isinstance(session_id, str) or not _SESSION.fullmatch(session_id):
        raise InvalidRequest("OpenCode Go requires a trusted stable conversation session ID.")
    if not isinstance(messages, list) or not messages:
        raise InvalidRequest("OpenCode Go requires at least one chat message.")
    for m in messages:
        if not isinstance(m, dict) or m.get("role") not in ("system", "user", "assistant"):
            raise InvalidRequest("Invalid OpenCode Go message role.")
        if not isinstance(m.get("content"), str) or not m["content"].strip():
            raise InvalidRequest("Invalid OpenCode Go message content.")
    if max_tokens is not None and (type(max_tokens) is not int or max_tokens < 1):
        raise InvalidRequest("Invalid OpenCode Go max_tokens.")
    if temperature is not None and (type(temperature) not in (float, int) or not math.isfinite(float(temperature))):
        raise InvalidRequest("Invalid OpenCode Go temperature.")

    wire = _WIRE[upstream_model]
    body: dict[str, Any] = {"model": upstream_model}
    if wire == "messages":
        # Anthropic Messages requires a positive output budget, no fabricated
        # default. Preserve all system content without routing it as a user.
        if max_tokens is None:
            raise InvalidRequest("Claude Messages needs an explicit max_tokens budget.")
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        turns = [{"role": m["role"], "content": m["content"]}
                 for m in messages if m["role"] != "system"]
        if not turns:
            raise InvalidRequest("Anthropic Messages requires user/assistant turns.")
        body.update({"messages": turns, "max_tokens": max_tokens})
        if system:
            body["system"] = system
    elif wire == "responses":
        body["input"] = [{"role": m["role"], "content": m["content"]} for m in messages]
        if max_tokens is not None:
            body["max_output_tokens"] = max_tokens
    else:
        body["messages"] = messages
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
    if temperature is not None:
        # Provider validates the model-native temperature range. Never infer it.
        body["temperature"] = float(temperature)
    if streaming:
        body["stream"] = True
    headers = {"User-Agent": _UA, "x-opencode-session": session_id}
    if wire == "messages":
        headers["anthropic-version"] = "2023-06-01"
    return wire, body, headers


def _normalize_go_answer(wire: str, upstream_model: str, payload: Any, *, latency_ms: int, response_bytes: int) -> dict[str, Any]:
    """Normalize three incompatible envelopes to B14 chat completion shape."""
    if not isinstance(payload, dict):
        raise MalformedUpstreamResponse()
    actual = payload.get("model")
    if actual is not None and actual != upstream_model:
        raise MalformedUpstreamResponse()
    usage = payload.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    if wire == "chat/completions":
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise MalformedUpstreamResponse()
        item = choices[0]
        if not isinstance(item, dict) or not isinstance(item.get("message"), dict):
            raise MalformedUpstreamResponse()
        text = item["message"].get("content")
        finish = item.get("finish_reason")
        in_tokens = usage.get("prompt_tokens")
        out_tokens = usage.get("completion_tokens")
    elif wire == "responses":
        status = payload.get("status")
        if status != "completed":
            raise MalformedUpstreamResponse()
        chunks = []
        if not isinstance(payload.get("output"), list):
            raise MalformedUpstreamResponse()
        for item in payload["output"]:
            if isinstance(item, dict) and item.get("type") == "message":
                for part in item.get("content", []):
                    if isinstance(part, dict) and part.get("type") == "output_text" and isinstance(part.get("text"), str):
                        chunks.append(part["text"])
        text = "".join(chunks)
        finish = "stop"
        in_tokens = usage.get("input_tokens")
        out_tokens = usage.get("output_tokens")
    elif wire == "messages":
        if payload.get("type") != "message" or payload.get("role") != "assistant":
            raise MalformedUpstreamResponse()
        if not isinstance(payload.get("content"), list):
            raise MalformedUpstreamResponse()
        chunks = [p["text"] for p in payload["content"]
                  if isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("text"), str)]
        text = "".join(chunks)
        finish = payload.get("stop_reason") or "stop"
        in_tokens = usage.get("input_tokens")
        out_tokens = usage.get("output_tokens")
    else:
        raise MalformedUpstreamResponse()
    if not isinstance(text, str) or not text.strip():
        raise UpstreamEmptyAnswer(finish)
    if any(v is not None and (type(v) is not int or v < 0) for v in (in_tokens, out_tokens)):
        raise MalformedUpstreamResponse()
    return {
        "id": payload.get("id") if isinstance(payload.get("id"), str) else f"b14go_{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "model": upstream_model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": finish}],
        "usage": {"prompt_tokens": in_tokens, "completion_tokens": out_tokens,
                  "total_tokens": in_tokens + out_tokens if in_tokens is not None and out_tokens is not None else None},
        "_live": True,
        "_requested_upstream_model": upstream_model,
        "_actual_response_model": actual,
        "_upstream_latency_ms": latency_ms,
        "_response_bytes": response_bytes,
    }


def _authorization_gate(model_id: str, upstream_model: str) -> None:
    from .catalog import get_catalog_by_id
    from .platform_secrets import get_platform_provider
    from .platform import _require_owner_allowed_live_model
    model = get_catalog_by_id(model_id)
    spec = get_platform_provider("opencode-go")
    if (model is None or not model.enabled or model.upstream_model != upstream_model
            or model.platform_provider_id != "opencode-go" or spec is None or not spec.enabled):
        raise PilotNotConfigured("OpenCode Go model is not enabled by the owner.")
    _require_owner_allowed_live_model(model_id, upstream_model, "opencode-go")


async def _authenticated_headers(session_headers: dict[str, str], wire: str) -> dict[str, str]:
    from .platform import _request_headers, _require_spec
    from .worker_env import load_request_secret
    spec = _require_spec("opencode-go")
    await load_request_secret(spec.credential_binding_name)
    headers = _request_headers(spec)
    if wire == "messages":
        bearer = headers.pop("Authorization", "")
        if not bearer.startswith("Bearer "):
            raise PilotNotConfigured("OpenCode Go Anthropic authorization is unavailable.")
        headers["x-api-key"] = bearer[7:]
    return {**headers, **session_headers}


def _go_url(wire: str) -> str:
    from .platform import _require_spec
    spec = _require_spec("opencode-go")
    if spec.base_origin != "https://opencode.ai/zen/go/v1":
        raise PilotNotConfigured("OpenCode Go origin does not match the owner approved endpoint.")
    return spec.base_origin + "/" + wire


async def call_go_model(*, model_id: str, upstream_model: str,
                        messages: list[dict[str, str]], session_id: str | None,
                        max_tokens: int | None = None, temperature: float | None = None,
                        transport: httpx.AsyncBaseTransport | None = None) -> dict[str, Any]:
    wire, body, h = prepare_go_request(model_id=model_id, upstream_model=upstream_model,
                                       messages=messages, session_id=session_id,
                                       max_tokens=max_tokens, temperature=temperature)
    _authorization_gate(model_id, upstream_model)
    headers = await _authenticated_headers(h, wire)
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=build_provider_http_timeout(), transport=transport) as client:
            async with client.stream("POST", _go_url(wire), headers=headers, json=body, follow_redirects=False) as resp:
                if not 200 <= resp.status_code < 300:
                    from .platform import _raise_upstream_error
                    _raise_upstream_error(resp.status_code, "opencode-go")  # never forward vendor body
                # Pre-decode byte cap (#4379): the post-buffer len() check could
                # only fire after the whole body was already in RAM.
                from .platform import _read_bounded_body
                raw = await _read_bounded_body(resp)
    except httpx.TimeoutException as e:
        raise UpstreamTimeout() from e
    except httpx.RequestError as e:
        raise UpstreamServerError() from e
    try:
        parsed = json.loads(raw)
    except (ValueError, UnicodeError) as e:
        raise MalformedUpstreamResponse() from e
    return _normalize_go_answer(wire, upstream_model, parsed,
                                latency_ms=int((time.monotonic() - start) * 1000),
                                response_bytes=len(raw))


def _decode_stream_event(wire: str, event: str, payload: Any, upstream_model: str) -> tuple[str | None, str | None, StreamUsage | None, bool]:
    if not isinstance(payload, dict):
        raise MalformedUpstreamResponse()
    actual = payload.get("model")
    if actual is not None and actual != upstream_model:
        raise MalformedUpstreamResponse()
    if wire == "responses":
        kind = payload.get("type") or event
        if kind == "response.output_text.delta":
            v = payload.get("delta")
            if not isinstance(v, str):
                raise MalformedUpstreamResponse()
            return v, None, None, False
        if kind == "response.completed":
            response = payload.get("response")
            if not isinstance(response, dict) or response.get("status") != "completed":
                raise MalformedUpstreamResponse()
            if response.get("model") not in (None, upstream_model):
                raise MalformedUpstreamResponse()
            usage = response.get("usage", {})
            return None, "stop", _go_usage(usage, "input_tokens", "output_tokens"), True
        if kind in ("response.failed", "error", "response.incomplete"):
            raise MalformedUpstreamResponse()
    elif wire == "messages":
        kind = payload.get("type") or event
        if kind == "content_block_delta":
            delta = payload.get("delta")
            if not isinstance(delta, dict):
                raise MalformedUpstreamResponse()
            if delta.get("type") == "text_delta":
                text = delta.get("text")
                if not isinstance(text, str):
                    raise MalformedUpstreamResponse()
                return text, None, None, False
        if kind == "message_start":
            msg = payload.get("message")
            if isinstance(msg, dict) and msg.get("model") not in (None, upstream_model):
                raise MalformedUpstreamResponse()
            return None, None, _go_usage(msg.get("usage", {}) if isinstance(msg, dict) else {}, "input_tokens", "output_tokens"), False
        if kind == "message_delta":
            d = payload.get("delta", {})
            if not isinstance(d, dict):
                raise MalformedUpstreamResponse()
            return None, d.get("stop_reason"), _go_usage(payload.get("usage", {}), "input_tokens", "output_tokens"), False
        if kind == "message_stop":
            return None, None, None, True
        if kind == "error":
            raise MalformedUpstreamResponse()
    else:
        choices = payload.get("choices")
        if choices is not None:
            if not isinstance(choices, list):
                raise MalformedUpstreamResponse()
            if choices:
                choice = choices[0]
                if not isinstance(choice, dict):
                    raise MalformedUpstreamResponse()
                delta = choice.get("delta", {})
                if delta is not None and not isinstance(delta, dict):
                    raise MalformedUpstreamResponse()
                t = delta.get("content") if isinstance(delta, dict) else None
                if t is not None and not isinstance(t, str):
                    raise MalformedUpstreamResponse()
                finish = choice.get("finish_reason")
                return t, finish, None, False
        if payload.get("usage") is not None:
            return None, None, _go_usage(payload["usage"], "prompt_tokens", "completion_tokens"), False
    return None, None, None, False


def _go_usage(usage: Any, input_key: str, output_key: str) -> StreamUsage | None:
    if not isinstance(usage, dict) or not usage:
        return None
    ins = usage.get(input_key)
    outs = usage.get(output_key)
    if any(v is not None and (type(v) is not int or v < 0) for v in (ins, outs)):
        raise MalformedUpstreamResponse()
    return StreamUsage(ins, outs, ins + outs if ins is not None and outs is not None else None)


async def stream_go_model(*, model_id: str, upstream_model: str,
                          messages: list[dict[str, str]], session_id: str | None,
                          max_tokens: int | None = None, temperature: float | None = None,
                          transport: httpx.AsyncBaseTransport | None = None) -> AsyncIterator[StreamEvent]:
    wire, body, h = prepare_go_request(model_id=model_id, upstream_model=upstream_model,
                                       messages=messages, session_id=session_id, max_tokens=max_tokens,
                                       temperature=temperature, streaming=True)
    _authorization_gate(model_id, upstream_model)
    headers = await _authenticated_headers(h, wire)
    from .platform import MAX_RESPONSE_BYTES, _pop_sse_frames, _raise_upstream_error
    buffer = b""
    saw_text = False
    saw_end = False
    last_reason = None
    try:
        async with httpx.AsyncClient(timeout=build_provider_http_timeout(), transport=transport) as client:
            async with client.stream("POST", _go_url(wire), headers=headers, json=body, follow_redirects=False) as resp:
                if not 200 <= resp.status_code < 300:
                    _raise_upstream_error(resp.status_code, "opencode-go")
                async for block in resp.aiter_bytes():
                    buffer += block
                    if len(buffer) > MAX_RESPONSE_BYTES:
                        raise UpstreamResponseTooLarge(MAX_RESPONSE_BYTES)
                    frames, buffer = _pop_sse_frames(buffer)
                    for frame in frames:
                        event_type = ""
                        lines: list[str] = []
                        for line in frame.decode("utf-8").splitlines():
                            if line.startswith("event:"):
                                event_type = line[6:].strip()
                            elif line.startswith("data:"):
                                lines.append(line[5:].lstrip())
                        if not lines:
                            continue
                        data = "\n".join(lines)
                        if data == "[DONE]":
                            if wire == "chat/completions":
                                if not saw_text:
                                    raise UpstreamEmptyAnswer(last_reason, streamed=True)
                                saw_end = True
                                yield StreamEvent(done=True)
                                return
                            raise MalformedUpstreamResponse()
                        try:
                            payload = json.loads(data)
                        except ValueError as e:
                            raise MalformedUpstreamResponse() from e
                        delta, reason, usage, ended = _decode_stream_event(wire, event_type, payload, upstream_model)
                        if delta:
                            saw_text = saw_text or bool(delta.strip())
                            yield StreamEvent(model=upstream_model, delta_content=delta)
                        if reason is not None or usage is not None:
                            last_reason = reason or last_reason
                            yield StreamEvent(model=upstream_model, finish_reason=reason, usage=usage)
                        if ended:
                            if not saw_text:
                                raise UpstreamEmptyAnswer(last_reason, streamed=True)
                            saw_end = True
                            yield StreamEvent(done=True)
                            return
    except httpx.TimeoutException as e:
        raise UpstreamTimeout() from e
    except httpx.RequestError as e:
        raise UpstreamServerError() from e
    if not saw_end:
        raise MalformedUpstreamResponse()
