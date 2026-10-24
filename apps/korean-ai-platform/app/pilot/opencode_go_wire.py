"""OpenCode Go fixed-model protocol boundary (coding-agent traffic only).

The seven exact owner-approved model IDs are routed by their *documented*
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
from .errors import PilotError, InvalidRequest, MalformedUpstreamResponse, PilotNotConfigured, UpstreamResponseTooLarge, UpstreamServerError, UpstreamTimeout
from .stream_types import StreamEvent, StreamToolCall, StreamUsage
from .tool_channel import (
    InvalidToolDeclaration,
    MAX_TOOL_ARGUMENT_CHARS,
    require_tool_capability,
    validate_tool_calls,
    validate_tool_choice,
    validate_tools,
)
from .upstream_answer_contract import UpstreamEmptyAnswer

# Owner-approved Go models; additions must keep their official wire protocol.
_WIRE = {
    "cat-jam-free": "chat/completions",
    "beam-free": "chat/completions",
    "longcat-2.5-preview-free": "chat/completions",
    "step-5-preview-free": "chat/completions",
    "muse-spark-1.3-contributor": "responses",
    "muse-spark-1.2-contributor": "responses",
    "gpt-6-luna": "responses",
    "claude-haiku-5-5": "messages",
}
_UA = "padiem-claw-coding-agent/1.0"
# The Responses lane is the one Go wire that carries a tool declaration. The
# model maker documents function calling for Muse Spark and the Go gateway
# serves that model on the OpenAI Responses transport; the chat/completions and
# Anthropic Messages lanes keep their answer-only request shape until their own
# provider contract is verified.
_TOOL_WIRE = "responses"
# Go documents a stable x-opencode-session per conversation, NOT a chat_ UUID
# format. This is a header-value safety check only, not identity authority.
# The public B14 gateway must never promote user-supplied JSON/headers to trust.
_SESSION_HEADER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _plain_turns(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    """The text-only turn shape every Go wire has always accepted."""
    turns: list[dict[str, str]] = []
    for m in messages:
        if not isinstance(m, dict) or m.get("role") not in ("system", "user", "assistant"):
            raise InvalidRequest("Invalid OpenCode Go message role.")
        if not isinstance(m.get("content"), str) or not m["content"].strip():
            raise InvalidRequest("Invalid OpenCode Go message content.")
        turns.append({"role": m["role"], "content": m["content"]})
    return turns


def _responses_turns(
    messages: list[dict[str, Any]], declared: frozenset[str],
) -> list[dict[str, Any]]:
    """Project a validated B14 conversation onto Responses input items.

    A text turn keeps its ``role``/``content`` shape. The Responses transport
    replays a tool turn as items, not messages: the assistant's request becomes
    one ``function_call`` item per call and the caller's answer becomes one
    ``function_call_output`` item. A call naming an undeclared tool, or a result
    answering no call of this input, is refused here instead of reaching the
    provider.
    """
    items: list[dict[str, Any]] = []
    requested: set[str] = set()
    answered: set[str] = set()
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            raise InvalidRequest("Invalid OpenCode Go message shape.")
        role = message.get("role")
        content = message.get("content")

        if role == "tool":
            call_id = message.get("tool_call_id")
            if not isinstance(content, str) or not content.strip():
                raise InvalidRequest("Invalid OpenCode Go tool result content.")
            if call_id not in requested:
                raise InvalidRequest("OpenCode Go tool result answers an unknown call.")
            if call_id in answered:
                raise InvalidRequest("OpenCode Go tool result duplicates an answered call.")
            answered.add(call_id)
            items.append({"type": "function_call_output", "call_id": call_id, "output": content})
            continue

        if role not in ("system", "user", "assistant"):
            raise InvalidRequest("Invalid OpenCode Go message role.")
        calls = (
            [] if message.get("tool_calls") is None
            else validate_tool_calls(message.get("tool_calls"), index)
        )
        if calls and (role != "assistant" or not declared):
            raise InvalidRequest("Only an assistant turn may carry a declared tool call.")
        if content is None:
            if not calls:
                raise InvalidRequest("Invalid OpenCode Go message content.")
        elif not isinstance(content, str) or not content.strip():
            raise InvalidRequest("Invalid OpenCode Go message content.")
        if isinstance(content, str) and content.strip():
            items.append({"role": role, "content": content})
        for call in calls:
            name, call_id = call["function"]["name"], call["id"]
            if name not in declared:
                raise InvalidRequest("OpenCode Go assistant turn names an undeclared tool.")
            if call_id in requested:
                raise InvalidRequest("OpenCode Go assistant turn duplicates a tool call id.")
            requested.add(call_id)
            items.append({
                "type": "function_call", "call_id": call_id, "name": name,
                "arguments": call["function"]["arguments"],
            })
    return items


def _responses_tool_declarations(
    declared: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """The Responses transport declares a function tool flat, not nested."""
    tools: list[dict[str, Any]] = []
    for item in declared:
        function = item["function"]
        entry: dict[str, Any] = {
            "type": "function", "name": function["name"],
            "parameters": function["parameters"],
        }
        description = function.get("description")
        if description:
            entry["description"] = description
        tools.append(entry)
    return tools


def _responses_tool_choice(choice: Any) -> Any:
    """A named choice is flat on this transport; the keyword forms are not."""
    if isinstance(choice, str):
        return choice
    return {"type": "function", "name": choice["function"]["name"]}


def go_tool_wire(model_id: str) -> str | None:
    """The tool-carrying wire of one registered Go model, or None.

    Three separate facts must hold: the model is the enabled, registered
    opencode-go model, the canonical registry declares its tool capability, and
    its documented wire is the one this adapter carries tools on. A caller uses
    the answer to refuse with its own error, so a tool request is never
    answered by a model that cannot make a call.
    """
    from .catalog import get_catalog_by_id
    from .tool_channel import model_supports_tools

    model = get_catalog_by_id(model_id)
    if model is None or not model.enabled or model.platform_provider_id != "opencode-go":
        return None
    if not model_supports_tools(model.model_id):
        return None
    return model.upstream_model if _WIRE.get(model.upstream_model) == _TOOL_WIRE else None


def prepare_go_request(
    *, model_id: str, upstream_model: str, messages: list[dict[str, Any]],
    session_id: str | None, max_tokens: int | None = None,
    temperature: float | None = None, streaming: bool = False,
    tools: Any = None, tool_choice: Any = None,
) -> tuple[str, dict[str, Any], dict[str, str]]:
    """Provider-specific wire shape, not a B14-wide conversation requirement.

    An authorized caller can supply its existing stable conversation key.
    For an independent one-shot B14 completion (no conversation key), mint one
    request-scoped session key solely for OpenCode routing. It is NOT a login,
    tenancy or ownership grant and cannot be reused as one.
    """
    if _WIRE.get(upstream_model) is None or model_id != "opencode-go/" + upstream_model:
        raise InvalidRequest("OpenCode Go model is not in the owner allowlist.")
    wire = _WIRE[upstream_model]
    # A tool declaration is a claim about the routed model, so the registry
    # decides whether it may be served and the wire decides whether this
    # adapter can carry it. Both are read before any credential is resolved.
    declared = validate_tools(tools)
    choice = validate_tool_choice(tool_choice, declared)
    if choice is not None and not declared:
        raise InvalidRequest("OpenCode Go tool_choice requires a declared tool.")
    if declared:
        require_tool_capability(model_id)
        if wire != _TOOL_WIRE:
            raise InvalidRequest("Unverified tool declaration for the OpenCode Go wire.")
    if session_id is None:
        # One POST without product conversation state is its own one-turn
        # conversation. Keep a real, distinct provider session for this call.
        session_id = "go_" + uuid.uuid4().hex
    elif not isinstance(session_id, str) or not _SESSION_HEADER.fullmatch(session_id):
        raise InvalidRequest("Invalid OpenCode Go session header value.")
    if not isinstance(messages, list) or not messages:
        raise InvalidRequest("OpenCode Go requires at least one chat message.")
    if wire == _TOOL_WIRE:
        turns = _responses_turns(
            messages, frozenset(item["function"]["name"] for item in declared)
        )
    else:
        turns = _plain_turns(messages)
    if max_tokens is not None and (type(max_tokens) is not int or max_tokens < 1):
        raise InvalidRequest("Invalid OpenCode Go max_tokens.")
    if temperature is not None and (type(temperature) not in (float, int) or not math.isfinite(float(temperature))):
        raise InvalidRequest("Invalid OpenCode Go temperature.")

    body: dict[str, Any] = {"model": upstream_model}
    if wire == "messages":
        # Anthropic Messages requires a positive output budget, no fabricated
        # default. Preserve all system content without routing it as a user.
        if max_tokens is None:
            raise InvalidRequest("Claude Messages needs an explicit max_tokens budget.")
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        chat_turns = [{"role": m["role"], "content": m["content"]}
                      for m in messages if m["role"] != "system"]
        if not chat_turns:
            raise InvalidRequest("Anthropic Messages requires user/assistant turns.")
        body.update({"messages": chat_turns, "max_tokens": max_tokens})
        if system:
            body["system"] = system
    elif wire == _TOOL_WIRE:
        body["input"] = turns
        if max_tokens is not None:
            body["max_output_tokens"] = max_tokens
        # The declaration and the choice travel only when the caller declared
        # a tool, so a tool-free request keeps its exact previous body.
        if declared:
            body["tools"] = _responses_tool_declarations(declared)
            if choice is not None:
                body["tool_choice"] = _responses_tool_choice(choice)
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


def _responses_function_calls(
    payload: dict[str, Any], declared_names: frozenset[str] | None,
) -> list[dict[str, Any]]:
    """Read the model's function calls out of a completed Responses envelope.

    The transport answers with one ``function_call`` item per call. B14 relays
    the call to its caller as the OpenAI-compatible ``tool_calls`` array, so the
    provider item shape and the product shape are translated here, once.

    A call is checked against the tools this request actually declared, the
    same way the streaming decoder checks one. A name nobody declared is a
    provider defect, not a request the caller may act on.
    """
    calls: list[dict[str, Any]] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "function_call":
            continue
        arguments = item.get("arguments")
        if isinstance(arguments, dict):
            # A provider that hands back parsed arguments instead of the JSON
            # string still describes one call; encode it for the shared shape.
            arguments = json.dumps(arguments, ensure_ascii=False)
        calls.append({
            "id": item.get("call_id") or item.get("id"),
            "type": "function",
            "function": {"name": item.get("name"), "arguments": arguments},
        })
    if not calls:
        return []
    permitted = declared_names or frozenset()
    try:
        validated = validate_tool_calls(calls, 0)
    except InvalidToolDeclaration as exc:
        raise MalformedUpstreamResponse() from exc
    if any(call["function"]["name"] not in permitted for call in validated):
        # The request is refused rather than relayed: an unvalidated call could
        # reach a tool executor that trusts whatever name the answer carried.
        raise MalformedUpstreamResponse()
    return validated


def _normalize_go_answer(wire: str, upstream_model: str, payload: Any, *, latency_ms: int, response_bytes: int, declared_names: frozenset[str] | None = None) -> dict[str, Any]:
    """Normalize three incompatible envelopes to B14 chat completion shape."""
    if not isinstance(payload, dict):
        raise MalformedUpstreamResponse()
    actual = payload.get("model")
    if actual is not None and actual != upstream_model:
        raise MalformedUpstreamResponse()
    usage = payload.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    tool_calls: list[dict[str, Any]] = []
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
    elif wire == _TOOL_WIRE:
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
        # A call is the model's answer for this turn. It may come with prose or
        # without it, and the caller decides what the tool result means.
        tool_calls = _responses_function_calls(payload, declared_names)
        finish = "tool_calls" if tool_calls else "stop"
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
    if not isinstance(text, str):
        raise MalformedUpstreamResponse()
    if not text.strip() and not tool_calls:
        raise UpstreamEmptyAnswer(finish)
    if any(v is not None and (type(v) is not int or v < 0) for v in (in_tokens, out_tokens)):
        raise MalformedUpstreamResponse()
    message: dict[str, Any] = {"role": "assistant", "content": text or None}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "id": payload.get("id") if isinstance(payload.get("id"), str) else f"b14go_{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "model": upstream_model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
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


_GO_APPROVED_ORIGIN = "https://opencode.ai/inference/go"
# The registry origin (.../go/v1) remains the approved model-list anchor.
# Provider inference endpoints are grouped by API family under this origin:
# OpenAI-compatible models use /openai/v1 and Anthropic models use
# /anthropic/v1.
_GO_INFERENCE_BASES = {
    "chat/completions": _GO_APPROVED_ORIGIN + "/openai/v1",
    "responses": _GO_APPROVED_ORIGIN + "/openai/v1",
    "messages": _GO_APPROVED_ORIGIN + "/anthropic/v1",
}


def _go_url(wire: str) -> str:
    from .platform import _require_spec
    spec = _require_spec("opencode-go")
    if spec.base_origin != _GO_APPROVED_ORIGIN + "/v1":
        raise PilotNotConfigured("OpenCode Go origin does not match the owner approved endpoint.")
    base = _GO_INFERENCE_BASES.get(wire)
    if base is None:
        raise PilotNotConfigured("OpenCode Go wire family is not approved.")
    return base + "/" + wire


async def _go_vendor_diagnostic(
    response: httpx.Response, *, upstream_model: str, session_id: str | None,
    wire: str, headers: dict[str, str],
) -> dict[str, Any]:
    """Read a bounded error prefix for server logs; never alter the public error."""
    from .redaction import redact_sensitive
    raw = bytearray()
    try:
        iterator = response.aiter_bytes(chunk_size=512)
        try:
            async for block in iterator:
                raw.extend(block[:512 - len(raw)])
                if len(raw) == 512:
                    break
        finally:
            await iterator.aclose()
        message = raw.decode("utf-8", errors="replace")
        # Also mask exact values already used for this request, including a
        # provider session echo. No header value becomes diagnostic metadata.
        for key in ("Authorization", "x-api-key", "x-opencode-session"):
            value = headers.get(key, "")
            if key == "Authorization" and value.startswith("Bearer "):
                value = value[7:]
            if value:
                message = message.replace(value, "[REDACTED]")
        message = redact_sensitive(message)
        message = re.sub(r"(?i)\bbearer\s+[^\s\"'<>;,]+", "[REDACTED]", message)
        message = re.sub(r"(?i)\bsk-[A-Za-z0-9_.-]*", "[REDACTED]", message)
        message = re.sub(
            r"""(?i)\b(?:api[ _-]?key|access[_-]?token|refresh[_-]?token|"""
            r"""client[_-]?secret|password|token|secret|authorization)\b["']?"""
            r"""\s*[:=]\s*["']?[^\s"';,}]*""",
            "[REDACTED]", message,
        )
        message = re.sub(r"[A-Za-z0-9_+/=.-]{24,}", "[REDACTED]", message)
        message = re.sub(r"[\x00-\x1f\x7f]", " ", message)
        message = message[:200]
    except Exception:
        # An unreadable error body must still map to the original HTTP error.
        message = "[vendor body unavailable]"
    return {
        "vendor_status": response.status_code,
        "vendor_message": message,
        "provider_id": "opencode-go",
        "upstream_model": upstream_model,
        "vendor_path": "/inference/go/" + (
            "anthropic/v1/" if wire == "messages" else "openai/v1/"
        ) + wire,
        "session_header_kind": "minted" if session_id is None else "conversation",
    }


async def _raise_go_vendor_error(
    response: httpx.Response, *, upstream_model: str, session_id: str | None,
    wire: str, headers: dict[str, str],
) -> None:
    from .platform import _raise_upstream_error
    diagnostic = await _go_vendor_diagnostic(
        response, upstream_model=upstream_model, session_id=session_id,
        wire=wire, headers=headers,
    )
    try:
        _raise_upstream_error(response.status_code, "opencode-go")
    except PilotError as exc:
        # PilotError.to_dict and both HTTP gateways serialize only their
        # original public fields. This attribute is server-log-only.
        exc._go_vendor_diagnostic = diagnostic
        raise


def log_go_vendor_error(
    logger: Any, error: PilotError, *, request_id: str,
    request_path: str, attempt: int, fallback: bool,
) -> bool:
    """Extend alpha_error for Go only, once per failed physical attempt."""
    diagnostic = getattr(error, "_go_vendor_diagnostic", None)
    if not isinstance(diagnostic, dict) or diagnostic.get("provider_id") != "opencode-go":
        return False
    logger.warning(
        "alpha_error request_id=%s code=%s status=%d attempt=%d "
        "provider_id=%s upstream_model=%s request_path=%s vendor_path=%s "
        "session_header_kind=%s fallback=%s vendor_status=%d vendor_message=%s",
        request_id, error.code, error.status_code, attempt,
        diagnostic["provider_id"], diagnostic["upstream_model"],
        json.dumps(request_path[:200]), diagnostic["vendor_path"],
        diagnostic["session_header_kind"], "fallback" if fallback else "primary",
        diagnostic["vendor_status"],
        json.dumps(diagnostic["vendor_message"], ensure_ascii=True),
    )
    error._go_vendor_logged = True
    return True


async def call_go_model(*, model_id: str, upstream_model: str,
                        messages: list[dict[str, Any]], session_id: str | None,
                        max_tokens: int | None = None, temperature: float | None = None,
                        tools: Any = None, tool_choice: Any = None,
                        transport: httpx.AsyncBaseTransport | None = None) -> dict[str, Any]:
    wire, body, h = prepare_go_request(model_id=model_id, upstream_model=upstream_model,
                                       messages=messages, session_id=session_id,
                                       max_tokens=max_tokens, temperature=temperature,
                                       tools=tools, tool_choice=tool_choice)
    _authorization_gate(model_id, upstream_model)
    headers = await _authenticated_headers(h, wire)
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=build_provider_http_timeout(), transport=transport) as client:
            async with client.stream("POST", _go_url(wire), headers=headers, json=body, follow_redirects=False) as resp:
                if not 200 <= resp.status_code < 300:
                    await _raise_go_vendor_error(
                        resp, upstream_model=upstream_model, session_id=session_id,
                        wire=wire, headers=headers,
                    )
                # Pre-decode byte cap (#4379): the post-buffer len() check could
                # only fire after the whole body was already in RAM.
                from .platform import MAX_COMPLETED_RESPONSE_BYTES, _read_bounded_body
                raw = await _read_bounded_body(resp, cap=MAX_COMPLETED_RESPONSE_BYTES)
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
                                response_bytes=len(raw),
                                declared_names=frozenset(
                                    item["name"] for item in body.get("tools") or []
                                ) or None)


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


class _GoResponsesToolStream:
    """Buffer Responses tool events and emit only complete function calls.

    The transport spreads one call across several frames: the item opens, the
    arguments arrive as deltas, then the item closes. A partial argument string
    handed to a caller would make it run a tool with the wrong arguments, so a
    call travels only after the provider closes it, and every call is checked
    against the tool names this request actually declared.

    This decoder owns no authority: it decodes a request to use a tool, never
    the permission to use one.
    """

    def __init__(self, *, names: frozenset[str], upstream_model: str) -> None:
        self.names = names
        self.upstream_model = upstream_model
        self.finish_reason: str | None = None
        self.done = False
        self.saw_output = False
        self._pending: dict[str, dict[str, Any]] = {}
        self._closed: set[str] = set()
        self._emitted_ids: set[str] = set()
        self._index = 0

    def _open(self, key: str) -> dict[str, Any]:
        return self._pending.setdefault(
            key, {"id": None, "name": None, "arguments": ""}
        )

    def _record(self, key: str, item: dict[str, Any]) -> None:
        call = self._open(key)
        for field in ("call_id", "name", "arguments"):
            value = item.get(field)
            if field == "arguments" and isinstance(value, dict):
                # A provider may hand the closed item back as a parsed object.
                # Re-encode it; treating it as absent would answer the caller
                # with an empty argument set for a call that had one.
                value = json.dumps(value, ensure_ascii=False)
            if isinstance(value, str) and value:
                call["id" if field == "call_id" else field] = value

    def _close(self, key: str) -> StreamEvent:
        call = self._open(key)
        arguments = call["arguments"].strip() or "{}"
        if len(arguments) > MAX_TOOL_ARGUMENT_CHARS:
            raise MalformedUpstreamResponse()
        try:
            validated = validate_tool_calls([{
                "id": call["id"],
                "type": "function",
                "function": {"name": call["name"], "arguments": arguments},
            }], 0)[0]
        except InvalidToolDeclaration as exc:
            raise MalformedUpstreamResponse() from exc
        name = validated["function"]["name"]
        if name not in self.names or validated["id"] in self._emitted_ids:
            # A call for a tool nobody declared, or the same call twice, is a
            # provider defect rather than a turn of the conversation.
            raise MalformedUpstreamResponse()
        self._closed.add(key)
        self._emitted_ids.add(validated["id"])
        self.saw_output = True
        event = StreamToolCall(
            validated["id"], name, validated["function"]["arguments"], self._index,
        )
        self._index += 1
        return StreamEvent(model=self.upstream_model, tool_call=event)

    def decode(self, event: str, payload: Any) -> list[StreamEvent]:
        if not isinstance(payload, dict):
            raise MalformedUpstreamResponse()
        actual = payload.get("model")
        if actual is not None and actual != self.upstream_model:
            raise MalformedUpstreamResponse()
        kind = payload.get("type") or event
        if kind == "response.output_text.delta":
            text = payload.get("delta")
            if not isinstance(text, str):
                raise MalformedUpstreamResponse()
            self.saw_output = self.saw_output or bool(text.strip())
            return [StreamEvent(model=self.upstream_model, delta_content=text)]
        if kind == "response.output_item.added":
            item = payload.get("item")
            if isinstance(item, dict) and item.get("type") == "function_call":
                self._record(str(item.get("id")), item)
            return []
        if kind == "response.function_call_arguments.delta":
            delta = payload.get("delta")
            if not isinstance(delta, str):
                raise MalformedUpstreamResponse()
            call = self._open(str(payload.get("item_id")))
            call["arguments"] += delta
            if len(call["arguments"]) > MAX_TOOL_ARGUMENT_CHARS:
                raise MalformedUpstreamResponse()
            return []
        if kind == "response.function_call_arguments.done":
            arguments = payload.get("arguments")
            if isinstance(arguments, str) and arguments:
                self._open(str(payload.get("item_id")))["arguments"] = arguments
            return []
        if kind == "response.output_item.done":
            item = payload.get("item")
            if not isinstance(item, dict):
                raise MalformedUpstreamResponse()
            if item.get("type") != "function_call":
                return []
            key = str(item.get("id"))
            self._record(key, item)
            return [self._close(key)]
        if kind == "response.completed":
            return self._completed(payload)
        if kind in ("response.failed", "response.incomplete", "error"):
            raise MalformedUpstreamResponse()
        return []

    def _completed(self, payload: dict[str, Any]) -> list[StreamEvent]:
        response = payload.get("response")
        if not isinstance(response, dict) or response.get("status") != "completed":
            raise MalformedUpstreamResponse()
        if response.get("model") not in (None, self.upstream_model):
            raise MalformedUpstreamResponse()
        events: list[StreamEvent] = []
        # The completed envelope is the authority on what the turn produced. A
        # provider may close the response after an item's arguments are done
        # without repeating output_item.done, so any call still open is closed
        # from this envelope instead of being dropped.
        output = response.get("output")
        if output is not None and not isinstance(output, list):
            raise MalformedUpstreamResponse()
        for item in output or []:
            if isinstance(item, dict) and item.get("type") == "function_call":
                key = str(item.get("id"))
                self._record(key, item)
                if key not in self._closed:
                    events.append(self._close(key))
        if self._pending and len(self._closed) < len(self._pending):
            raise MalformedUpstreamResponse()
        self.finish_reason = "tool_calls" if self._emitted_ids else "stop"
        if not self.saw_output:
            raise UpstreamEmptyAnswer(self.finish_reason, streamed=True)
        usage = _go_usage(response.get("usage", {}), "input_tokens", "output_tokens")
        self.done = True
        events.append(StreamEvent(
            model=self.upstream_model, finish_reason=self.finish_reason, usage=usage,
        ))
        return events


async def stream_go_model(*, model_id: str, upstream_model: str,
                          messages: list[dict[str, Any]], session_id: str | None,
                          max_tokens: int | None = None, temperature: float | None = None,
                          tools: Any = None, tool_choice: Any = None,
                          transport: httpx.AsyncBaseTransport | None = None) -> AsyncIterator[StreamEvent]:
    wire, body, h = prepare_go_request(model_id=model_id, upstream_model=upstream_model,
                                       messages=messages, session_id=session_id, max_tokens=max_tokens,
                                       temperature=temperature, streaming=True,
                                       tools=tools, tool_choice=tool_choice)
    _authorization_gate(model_id, upstream_model)
    headers = await _authenticated_headers(h, wire)
    from .platform import MAX_RESPONSE_BYTES, _iter_sse_bounded_slices, _pop_sse_frames
    # A declared tool switches the Responses lane onto the tool decoder, which
    # emits each call only after its arguments are complete.
    tool_stream: _GoResponsesToolStream | None = None
    if body.get("tools"):
        tool_stream = _GoResponsesToolStream(
            names=frozenset(item["name"] for item in body["tools"]),
            upstream_model=upstream_model,
        )
    buffer = b""
    saw_text = False
    saw_end = False
    last_reason = None
    try:
        async with httpx.AsyncClient(timeout=build_provider_http_timeout(), transport=transport) as client:
            async with client.stream("POST", _go_url(wire), headers=headers, json=body, follow_redirects=False) as resp:
                if not 200 <= resp.status_code < 300:
                    await _raise_go_vendor_error(
                        resp, upstream_model=upstream_model, session_id=session_id,
                        wire=wire, headers=headers,
                    )
                # One HTTP block may contain many valid events. Slice each
                # incoming block immediately (no read-ahead) and bound only
                # incomplete/individual SSE frames, never cumulative output.
                async for block in _iter_sse_bounded_slices(resp):
                    buffer += block
                    frames, buffer = _pop_sse_frames(buffer)
                    if len(buffer) > MAX_RESPONSE_BYTES:
                        raise UpstreamResponseTooLarge(MAX_RESPONSE_BYTES)
                    for frame in frames:
                        if len(frame) > MAX_RESPONSE_BYTES:
                            raise UpstreamResponseTooLarge(MAX_RESPONSE_BYTES)
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
                            if tool_stream is not None:
                                # The decoder already raised on a turn that
                                # produced neither text nor a call.
                                if not tool_stream.saw_output:
                                    raise UpstreamEmptyAnswer(
                                        tool_stream.finish_reason, streamed=True
                                    )
                                saw_end = True
                                yield StreamEvent(
                                    done=True, finish_reason=tool_stream.finish_reason,
                                )
                                return
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
                        if tool_stream is not None:
                            for event in tool_stream.decode(event_type, payload):
                                yield event
                            if tool_stream.done:
                                saw_end = True
                                yield StreamEvent(
                                    done=True, finish_reason=tool_stream.finish_reason,
                                )
                                return
                            continue
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
