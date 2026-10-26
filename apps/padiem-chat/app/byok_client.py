"""PADIEM Custom direct provider execution (B14-independent).

The customer-owned key goes straight to the explicitly selected provider
origin. This module never calls the B14 service binding, B14 router, model
registry, default/fallback selection or the platform provider secret store.
Each provider keeps its official wire contract:

* OpenAI / OpenRouter: ``/chat/completions`` with OpenAI SSE ``[DONE]``.
* Anthropic: ``/v1/messages`` with ``x-api-key`` and ``anthropic-version``.
* Google Gemini: ``/v1beta/models/{model}:streamGenerateContent`` with SSE.

Responses are normalized to the product ``{"answer": ...}`` shape plus optional
usage fields; vendor bodies never reach the browser.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable
from urllib.parse import quote

from . import httpx_compat as httpx
from .b14_client import PADIEM_IDENTITY_INSTRUCTION
from .byok_credentials import (
    CustomProvider,
    ResolvedCustomSelection,
    resolve_custom_selection,
)
from .byok_endpoint import (
    CustomEndpointError,
    CustomEndpointUnverifiedError,
    CustomEndpointVerificationError,
    HttpsDnsResolver,
    verify_public_endpoint,
)
from .request_contract import CustomModelSelection

MAX_CUSTOM_RESPONSE_BYTES = 10 * 1024 * 1024
MAX_CUSTOM_MODEL_LIST = 500
MAX_CUSTOM_ANSWER_CHARS = 200_000
CUSTOM_SESSION_HEADER = "padiem-chat-custom/1.0"
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_MAX_TOKENS = 4096


@dataclass
class CustomProviderError(Exception):
    status_code: int
    code: str
    user_message: str
    upstream_status: int | None = None

    def __str__(self) -> str:
        return self.user_message


@dataclass(frozen=True, slots=True)
class OwnerCustomCredential:
    selection: ResolvedCustomSelection
    api_key: str
    endpoint: str


def _malformed() -> CustomProviderError:
    return CustomProviderError(
        502,
        "malformed_custom_provider_response",
        "PADIEM Custom 공급사 응답 형식을 확인할 수 없습니다. 다시 시도해 주세요.",
    )


def _empty_answer() -> CustomProviderError:
    return CustomProviderError(
        502,
        "empty_custom_provider_answer",
        "PADIEM Custom 공급사가 표시할 답변을 만들지 못했습니다. 다시 시도해 주세요.",
    )


def _response_too_large() -> CustomProviderError:
    return CustomProviderError(
        502,
        "custom_provider_response_too_large",
        "PADIEM Custom 공급사 응답이 허용 크기를 초과했습니다.",
    )


def _raise_for_status(status: int) -> None:
    if 300 <= status < 400:
        raise CustomProviderError(
            502,
            "custom_provider_redirect_blocked",
            "PADIEM Custom 공급사가 다른 주소로 이동을 요청해 차단했습니다.",
        )
    if status in (401, 403):
        raise CustomProviderError(
            502,
            "custom_provider_auth_failed",
            "PADIEM Custom 공급사가 API 키를 거부했습니다. 키를 확인해 주세요.",
            upstream_status=status,
        )
    if status == 429:
        raise CustomProviderError(
            429,
            "custom_provider_rate_limited",
            "PADIEM Custom 공급사 사용 한도에 도달했습니다. 잠시 후 다시 시도해 주세요.",
        )
    if 500 <= status < 600:
        raise CustomProviderError(
            502,
            "custom_provider_unavailable",
            "PADIEM Custom 공급사를 현재 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.",
        )
    if not 200 <= status < 300:
        raise CustomProviderError(
            502,
            "custom_provider_rejected",
            "PADIEM Custom 공급사가 요청을 처리하지 못했습니다.",
            upstream_status=status,
        )


def _system_text(system_context: str | None) -> str:
    parts = [PADIEM_IDENTITY_INSTRUCTION]
    if isinstance(system_context, str) and system_context.strip():
        parts.append(system_context.strip())
    return "\n\n".join(parts)


def _openai_messages(
    messages: list[dict[str, str]], system_context: str | None
) -> list[dict[str, str]]:
    return [{"role": "system", "content": _system_text(system_context)}, *messages]


def _anthropic_messages(
    messages: list[dict[str, str]],
) -> list[dict[str, str]]:
    return [
        {"role": "assistant" if item["role"] == "assistant" else "user",
         "content": item["content"]}
        for item in messages
    ]


def _google_contents(
    messages: list[dict[str, str]],
) -> list[dict[str, Any]]:
    return [
        {
            "role": "model" if item["role"] == "assistant" else "user",
            "parts": [{"text": item["content"]}],
        }
        for item in messages
    ]


def _headers(spec: CustomProvider, api_key: str) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": CUSTOM_SESSION_HEADER,
    }
    if spec.auth == "anthropic":
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = ANTHROPIC_VERSION
    elif spec.auth == "google":
        headers["x-goog-api-key"] = api_key
    else:
        headers["Authorization"] = "Bearer " + api_key
    if spec.provider_id == "opencode-go":
        headers["x-opencode-session"] = "chat_" + uuid.uuid4().hex
    for name, value in spec.extra_headers:
        headers[name] = value
    return headers


def _request_url(
    spec: CustomProvider, endpoint: str, upstream_model: str, stream: bool
) -> str:
    base = endpoint.rstrip("/")
    if spec.wire == "anthropic-messages":
        return base + "/messages"
    if spec.wire == "google-generate-content":
        verb = "streamGenerateContent?alt=sse" if stream else "generateContent"
        return base + "/models/" + quote(upstream_model, safe="") + ":" + verb
    return base + "/chat/completions"


def _request_body(
    spec: CustomProvider,
    upstream_model: str,
    messages: list[dict[str, str]],
    system_context: str | None,
    stream: bool,
) -> dict[str, Any]:
    if spec.wire == "anthropic-messages":
        body: dict[str, Any] = {
            "model": upstream_model,
            "max_tokens": ANTHROPIC_MAX_TOKENS,
            "messages": _anthropic_messages(messages),
            "stream": stream,
        }
        system = _system_text(system_context)
        if system:
            body["system"] = system
        return body
    if spec.wire == "google-generate-content":
        return {
            "contents": _google_contents(messages),
            "systemInstruction": {"parts": [{"text": _system_text(system_context)}]},
        }
    body = {
        "model": upstream_model,
        "messages": _openai_messages(messages, system_context),
    }
    if stream:
        body["stream"] = True
    return body


def _text_part(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(
            part.get("text", "")
            for part in value
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    return ""


def _usage(
    input_tokens: Any = None,
    output_tokens: Any = None,
    total_tokens: Any = None,
    cost: Any = None,
) -> dict[str, Any] | None:
    usage: dict[str, Any] = {}
    for name, value in (
        ("input_tokens", input_tokens),
        ("output_tokens", output_tokens),
        ("total_tokens", total_tokens),
    ):
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            usage[name] = value
    if "total_tokens" not in usage and "input_tokens" in usage and "output_tokens" in usage:
        usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
    if isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost >= 0:
        usage["cost_usd"] = float(cost)
    return usage or None


def _openai_usage(payload: dict[str, Any]) -> dict[str, Any] | None:
    raw = payload.get("usage")
    if not isinstance(raw, dict):
        return None
    cost = raw.get("cost", raw.get("total_cost"))
    return _usage(
        raw.get("prompt_tokens"),
        raw.get("completion_tokens"),
        raw.get("total_tokens"),
        cost,
    )


def _anthropic_usage(payload: dict[str, Any]) -> dict[str, Any] | None:
    raw = payload.get("usage")
    if not isinstance(raw, dict):
        return None
    return _usage(raw.get("input_tokens"), raw.get("output_tokens"))


def _google_usage(payload: dict[str, Any]) -> dict[str, Any] | None:
    raw = payload.get("usageMetadata")
    if not isinstance(raw, dict):
        return None
    return _usage(
        raw.get("promptTokenCount"),
        raw.get("candidatesTokenCount"),
        raw.get("totalTokenCount"),
    )


def _parse_json(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise _malformed() from exc
    if not isinstance(payload, dict):
        raise _malformed()
    return payload


def _normalize_openai_json(
    payload: dict[str, Any], expected_model: str, *, enforce_model: bool
) -> dict[str, Any]:
    actual = payload.get("model")
    if actual is not None and not isinstance(actual, str):
        raise _malformed()
    if enforce_model and actual is not None and actual != expected_model:
        # The selected OpenCode Go model is never silently replaced.
        raise _malformed()
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise _malformed()
    item = choices[0]
    message = item.get("message") if isinstance(item, dict) else None
    if not isinstance(message, dict):
        raise _malformed()
    text = _text_part(message.get("content"))
    if not text.strip():
        raise _empty_answer()
    return {"answer": text, "usage": _openai_usage(payload)}


def _normalize_anthropic_json(payload: dict[str, Any]) -> dict[str, Any]:
    content = payload.get("content")
    if not isinstance(content, list):
        raise _malformed()
    text = "".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict)
        and block.get("type") == "text"
        and isinstance(block.get("text"), str)
    )
    if not text.strip():
        raise _empty_answer()
    return {"answer": text, "usage": _anthropic_usage(payload)}


def _normalize_google_json(payload: dict[str, Any]) -> dict[str, Any]:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        if payload.get("promptFeedback"):
            raise _empty_answer()
        raise _malformed()
    text = ""
    if candidates:
        first = candidates[0]
        content = first.get("content") if isinstance(first, dict) else None
        parts = content.get("parts") if isinstance(content, dict) else None
        if isinstance(parts, list):
            text = "".join(
                part.get("text", "")
                for part in parts
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            )
    if not text.strip():
        raise _empty_answer()
    return {"answer": text, "usage": _google_usage(payload)}


class _SseEventStream:
    """Bounded SSE reader shared by the three streaming wire contracts."""

    def __init__(self, response: Any):
        self._response = response
        self._total = 0

    async def events(self) -> AsyncIterator[tuple[str, str]]:
        buffer = b""
        event_name = ""
        data_lines: list[str] = []
        async for chunk in self._response.aiter_bytes():
            if not isinstance(chunk, (bytes, bytearray, memoryview)):
                raise _malformed()
            data = bytes(chunk)
            self._total += len(data)
            if self._total > MAX_CUSTOM_RESPONSE_BYTES:
                raise _response_too_large()
            buffer += data
            while True:
                newline = buffer.find(b"\n")
                if newline < 0:
                    break
                line, buffer = buffer[:newline], buffer[newline + 1:]
                if line.endswith(b"\r"):
                    line = line[:-1]
                if line == b"":
                    if data_lines:
                        yield event_name, "\n".join(data_lines)
                    event_name = ""
                    data_lines = []
                    continue
                if line.startswith(b":"):
                    continue
                field, _, raw_value = line.partition(b":")
                value = raw_value[1:] if raw_value.startswith(b" ") else raw_value
                if field == b"event":
                    event_name = value.decode("utf-8", "replace")
                elif field == b"data":
                    data_lines.append(value.decode("utf-8", "replace"))
        if data_lines:
            yield event_name, "\n".join(data_lines)


def _stream_payload(data: str) -> dict[str, Any] | None:
    if data.strip() == "[DONE]":
        return None
    try:
        payload = json.loads(data)
    except (ValueError, UnicodeError) as exc:
        raise _malformed() from exc
    if not isinstance(payload, dict):
        raise _malformed()
    if payload.get("error"):
        raise CustomProviderError(
            502,
            "custom_provider_rejected",
            "PADIEM Custom 공급사가 스트리밍 요청을 거부했습니다.",
        )
    return payload


async def _openai_stream(
    response: Any, expected_model: str, *, enforce_model: bool
) -> dict[str, Any]:
    text: list[str] = []
    usage: dict[str, Any] | None = None
    finished = False
    done = False
    async for _event, data in _SseEventStream(response).events():
        if data.strip() == "[DONE]":
            done = True
        else:
            payload = _stream_payload(data)
            if payload is None:
                continue
            actual = payload.get("model")
            if actual is not None and not isinstance(actual, str):
                raise _malformed()
            if enforce_model and actual is not None and actual != expected_model:
                raise _malformed()
            choices = payload.get("choices")
            if isinstance(choices, list) and choices:
                item = choices[0]
                if isinstance(item, dict):
                    delta = item.get("delta")
                    if isinstance(delta, dict):
                        text.append(_text_part(delta.get("content")))
                    if item.get("finish_reason"):
                        finished = True
            usage = _openai_usage(payload) or usage
        if done:
            break
    if not done and not finished:
        raise _malformed()
    answer = "".join(text)
    if not answer.strip():
        raise _empty_answer()
    return {"answer": answer, "usage": usage}


async def _anthropic_stream(response: Any) -> dict[str, Any]:
    text: list[str] = []
    input_tokens: Any = None
    output_tokens: Any = None
    stopped = False
    async for _event, data in _SseEventStream(response).events():
        payload = _stream_payload(data)
        if payload is None:
            continue
        kind = payload.get("type")
        if kind == "error":
            raise CustomProviderError(
                502,
                "custom_provider_rejected",
                "PADIEM Custom 공급사가 스트리밍 요청을 거부했습니다.",
            )
        if kind == "message_start":
            message = payload.get("message")
            usage = message.get("usage") if isinstance(message, dict) else None
            if isinstance(usage, dict):
                input_tokens = usage.get("input_tokens", input_tokens)
        elif kind == "content_block_start":
            block = payload.get("content_block")
            if isinstance(block, dict) and block.get("type") == "text":
                text.append(block.get("text") if isinstance(block.get("text"), str) else "")
        elif kind == "content_block_delta":
            delta = payload.get("delta")
            if isinstance(delta, dict) and delta.get("type") == "text_delta":
                fragment = delta.get("text")
                if isinstance(fragment, str):
                    text.append(fragment)
        elif kind == "message_delta":
            delta = payload.get("delta")
            if isinstance(delta, dict):
                usage = payload.get("usage")
                if isinstance(usage, dict):
                    output_tokens = usage.get("output_tokens", output_tokens)
        elif kind == "message_stop":
            stopped = True
            break
    if not stopped:
        raise _malformed()
    answer = "".join(text)
    if not answer.strip():
        raise _empty_answer()
    return {
        "answer": answer,
        "usage": _usage(input_tokens, output_tokens),
    }


async def _google_stream(response: Any) -> dict[str, Any]:
    text: list[str] = []
    usage: dict[str, Any] | None = None
    async for _event, data in _SseEventStream(response).events():
        payload = _stream_payload(data)
        if payload is None:
            continue
        candidates = payload.get("candidates")
        if isinstance(candidates, list) and candidates:
            first = candidates[0]
            content = first.get("content") if isinstance(first, dict) else None
            parts = content.get("parts") if isinstance(content, dict) else None
            if isinstance(parts, list):
                text.extend(
                    part.get("text", "")
                    for part in parts
                    if isinstance(part, dict) and isinstance(part.get("text"), str)
                )
        usage = _google_usage(payload) or usage
    # Gemini SSE has no [DONE] sentinel; the stream end is the terminator.
    answer = "".join(text)
    if not answer.strip():
        raise _empty_answer()
    return {"answer": answer, "usage": usage}


async def _read_bounded(response: Any) -> bytes:
    raw = bytearray()
    async for chunk in response.aiter_bytes():
        if not isinstance(chunk, (bytes, bytearray, memoryview)):
            raise _malformed()
        raw.extend(bytes(chunk))
        if len(raw) > MAX_CUSTOM_RESPONSE_BYTES:
            raise _response_too_large()
    return bytes(raw)


class CustomProviderClient:
    """Direct HTTP client for the explicitly selected PADIEM Custom provider."""

    def __init__(
        self,
        *,
        transport: Any | None = None,
        timeout_seconds: float = 120.0,
        endpoint_resolver: Any | None = None,
    ):
        self._transport = transport
        self._timeout_seconds = float(timeout_seconds)
        self._endpoint_resolver = endpoint_resolver or HttpsDnsResolver()

    async def _safe_endpoint(self, spec: CustomProvider, endpoint: str) -> str:
        try:
            return await verify_public_endpoint(
                endpoint,
                default_endpoint=spec.base_origin,
                resolver=self._endpoint_resolver,
            )
        except (CustomEndpointVerificationError, CustomEndpointUnverifiedError) as exc:
            # A stored endpoint that no longer resolves to public unicast
            # addresses is a runtime safety refusal, not malformed input.
            raise CustomProviderError(502, exc.code, str(exc)) from exc
        except CustomEndpointError as exc:
            raise CustomProviderError(422, exc.code, str(exc)) from exc

    async def _stream_request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: dict[str, Any] | None,
        consume: Callable[[Any], Any],
    ) -> Any:
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                async with client.stream(
                    method,
                    url,
                    headers=headers,
                    json=body,
                    follow_redirects=False,
                ) as response:
                    _raise_for_status(int(response.status_code))
                    return await consume(response)
        except CustomProviderError:
            raise
        except httpx.ReadTimeout as exc:
            raise CustomProviderError(
                504,
                "custom_provider_timeout",
                "PADIEM Custom 공급사 응답이 시간 안에 도착하지 않았습니다.",
            ) from exc
        except httpx.RequestError as exc:
            raise CustomProviderError(
                502,
                "custom_provider_unreachable",
                "PADIEM Custom 공급사에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.",
            ) from exc

    async def complete(
        self,
        *,
        selection: ResolvedCustomSelection,
        api_key: str,
        endpoint: str,
        messages: list[dict[str, str]],
        system_context: str | None = None,
        stream: bool | None = None,
    ) -> dict[str, Any]:
        spec = selection.provider
        effective_endpoint = await self._safe_endpoint(spec, endpoint)
        use_stream = spec.stream_by_default if stream is None else bool(stream)
        url = _request_url(spec, effective_endpoint, selection.upstream_model, use_stream)
        body = _request_body(
            spec, selection.upstream_model, messages, system_context, use_stream
        )
        headers = _headers(spec, api_key)

        enforce_model = spec.provider_id == "opencode-go"
        if spec.wire == "openai-chat":
            if use_stream:
                payload = await self._stream_request(
                    "POST", url, headers=headers, body=body, consume=
                    lambda response: _openai_stream(
                        response,
                        selection.upstream_model,
                        enforce_model=enforce_model,
                    ),
                )
            else:
                raw = await self._stream_request(
                    "POST", url, headers=headers, body=body,
                    consume=_read_bounded,
                )
                payload = _normalize_openai_json(
                    _parse_json(raw),
                    selection.upstream_model,
                    enforce_model=enforce_model,
                )
        elif spec.wire == "anthropic-messages":
            if use_stream:
                payload = await self._stream_request(
                    "POST", url, headers=headers, body=body,
                    consume=_anthropic_stream,
                )
            else:
                raw = await self._stream_request(
                    "POST", url, headers=headers, body=body,
                    consume=_read_bounded,
                )
                payload = _normalize_anthropic_json(_parse_json(raw))
        else:
            if use_stream:
                payload = await self._stream_request(
                    "POST", url, headers=headers, body=body,
                    consume=_google_stream,
                )
            else:
                raw = await self._stream_request(
                    "POST", url, headers=headers, body=body,
                    consume=_read_bounded,
                )
                payload = _normalize_google_json(_parse_json(raw))

        answer = payload["answer"]
        if len(answer) > MAX_CUSTOM_ANSWER_CHARS:
            raise _response_too_large()
        return {
            "answer": answer,
            "usage": payload.get("usage"),
            "provider": spec.provider_id,
            "model": selection.model_id,
        }

    async def list_models(
        self,
        *,
        provider_id: str,
        api_key: str,
        endpoint: str,
    ) -> dict[str, Any]:
        spec = _require_provider(provider_id)
        if spec.models_path is None:
            return {"models": list(spec.models), "source": "registry"}
        effective_endpoint = await self._safe_endpoint(spec, endpoint)
        url = effective_endpoint.rstrip("/") + "/" + spec.models_path
        if spec.wire == "google-generate-content":
            url += "?pageSize=1000"
        headers = _headers(spec, api_key)
        headers.pop("Content-Type", None)
        raw = await self._stream_request(
            "GET", url, headers=headers, body=None, consume=_read_bounded
        )
        payload = _parse_json(raw)
        if spec.wire == "google-generate-content":
            rows = payload.get("models")
            models = []
            if isinstance(rows, list):
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    methods = row.get("supportedGenerationMethods")
                    if isinstance(methods, list) and "generateContent" not in methods:
                        continue
                    name = row.get("name")
                    if isinstance(name, str) and name.startswith("models/"):
                        name = name[len("models/"):]
                    if isinstance(name, str) and name:
                        models.append(name)
            source = "provider"
        elif spec.wire == "anthropic-messages":
            rows = payload.get("data")
            models = [
                row.get("id") for row in rows or []
                if isinstance(row, dict) and isinstance(row.get("id"), str)
            ] if isinstance(rows, list) else []
            source = "provider"
        else:
            rows = payload.get("data")
            models = [
                row.get("id") for row in rows or []
                if isinstance(row, dict) and isinstance(row.get("id"), str)
            ] if isinstance(rows, list) else []
            source = "provider"
        unique = sorted({model for model in models if model})
        return {
            "models": unique[:MAX_CUSTOM_MODEL_LIST],
            "source": source,
        }

    async def test_connection(
        self, *, provider_id: str, api_key: str, endpoint: str
    ) -> dict[str, Any]:
        spec = _require_provider(provider_id)
        if spec.models_path is None:
            raise CustomProviderError(
                422,
                "custom_connection_test_unsupported",
                "이 공급사는 연결 테스트를 지원하지 않습니다.",
            )
        listed = await self.list_models(
            provider_id=provider_id, api_key=api_key, endpoint=endpoint
        )
        return {"models_count": len(listed["models"]), "source": listed["source"]}


def _require_provider(provider_id: str) -> CustomProvider:
    from .byok_credentials import CUSTOM_PROVIDERS

    spec = CUSTOM_PROVIDERS.get(provider_id)
    if spec is None:
        raise CustomProviderError(
            422,
            "custom_provider_unsupported",
            "지원하지 않는 PADIEM Custom 공급사입니다.",
        )
    return spec


async def resolve_owner_custom_credential(
    app_state: Any,
    *,
    uid: str,
    selection: CustomModelSelection,
) -> OwnerCustomCredential:
    """Resolve the explicit provider and the owner's sealed key without dispatch.

    Products that must prove the request is executable before claiming a
    durable attempt token use this; the dispatch itself stays in
    ``complete_owner_custom``.
    """
    resolved = resolve_custom_selection(selection.provider, selection.model)
    store = getattr(app_state, "custom_credential_store", None)
    client = getattr(app_state, "custom_provider_client", None)
    if store is None or client is None:
        raise CustomProviderError(
            503,
            "custom_provider_unavailable",
            "PADIEM Custom을 현재 사용할 수 없습니다.",
        )
    try:
        credential = await store.credential(uid, resolved.provider.provider_id)
    except Exception:
        raise CustomProviderError(
            503,
            "custom_credential_unavailable",
            "PADIEM Custom 자격증명을 확인할 수 없습니다.",
        )
    if not credential:
        raise CustomProviderError(
            409,
            "custom_credential_required",
            "PADIEM Custom API 키를 먼저 등록해 주세요.",
        )
    api_key, endpoint = credential
    return OwnerCustomCredential(
        selection=resolved,
        api_key=api_key,
        endpoint=endpoint,
    )


async def complete_owner_custom(
    app_state: Any,
    *,
    uid: str,
    selection: CustomModelSelection,
    messages: list[dict[str, str]],
    system_context: str | None = None,
) -> dict[str, Any]:
    """The one owner-key -> explicit provider contract shared by Chat/Claw/B66.

    Only the canonical session owner's sealed key is used. No B14 client,
    router, registry, default/fallback policy or platform provider secret store
    is read on this path.
    """
    owner = await resolve_owner_custom_credential(
        app_state, uid=uid, selection=selection,
    )
    client = getattr(app_state, "custom_provider_client", None)
    return await client.complete(
        selection=owner.selection,
        api_key=owner.api_key,
        endpoint=owner.endpoint,
        messages=messages,
        system_context=system_context,
    )


# Prefixes are hints only. A provider response must verify the candidate before
# registration; a caller-supplied endpoint always retains the existing SSRF guard.
_BYOK_PREFIXES = (("sk-ant-", "anthropic"), ("AIza", "gemini"),
    ("sk-or-", "openrouter"), ("sk-proj-", "openai"), ("sk-", "openai"),
    ("gsk_", "groq"), ("xai-", "xai"), ("pplx-", "perplexity"),
    ("hf_", "huggingface"))
_BYOK_PREFERRED = {
    "openai": ("gpt-4.1-mini", "gpt-4o-mini"),
    "anthropic": ("claude-haiku-4-5",), "gemini": ("gemini-2.5-flash-lite",),
    "openrouter": ("openai/gpt-4.1-mini",),
}


def byok_provider_candidate(key: str, base_url: str | None = None) -> str | None:
    for prefix, provider in _BYOK_PREFIXES:
        if key.startswith(prefix):
            return provider
    return "openai" if base_url else None


async def detect_byok(client: CustomProviderClient, *, key: str, base_url=None) -> dict:
    """No persistence, vendor bodies or credential echoes at this boundary."""
    from .byok_credentials import CUSTOM_PROVIDERS, validate_custom_model_id
    from .byok_endpoint import normalize_custom_endpoint
    provider = byok_provider_candidate(key, base_url)
    result = {"provider": provider, "endpoint": None, "models": [],
              "verified": False, "reason": "공급자 선택이 필요합니다. 고급 입력에서 공급자·주소를 지정해 주세요."}
    if provider is None:
        return result
    try:
        spec = CUSTOM_PROVIDERS[provider]
        endpoint = normalize_custom_endpoint(base_url, default_endpoint=spec.base_origin)
        if key in endpoint:
            raise CustomEndpointError()
        result["endpoint"] = endpoint
        try:
            listed = await _probe_byok(client, spec, key, endpoint)
        except CustomProviderError as exc:
            # Only OpenAI's 401 permits one explicit alternative. Never fan out
            # after 403, network failure, or a caller-specified endpoint.
            if provider != "openai" or base_url or exc.upstream_status != 401:
                raise
            provider = "deepseek"
            spec = CUSTOM_PROVIDERS[provider]
            endpoint = spec.base_origin
            result.update(provider=provider, endpoint=endpoint)
            listed = await _probe_byok(client, spec, key, endpoint)
        models = []
        for model in listed:
            if not isinstance(model, str) or key in model:
                continue
            try:
                model = validate_custom_model_id(model)
            except ValueError:
                continue
            if model not in models:
                models.append(model)
        preferred = _BYOK_PREFERRED.get(provider, spec.models)
        models.sort(key=lambda m: (preferred.index(m) if m in preferred else len(preferred), m))
        if not models:
            result["reason"] = "사용 가능한 모델을 찾지 못했습니다. 고급 입력에서 모델을 지정해 주세요."
            return result
        result.update(models=models, verified=True, reason="공급자 연결을 확인했습니다.")
    except CustomEndpointError:
        result.update(endpoint=None, reason="공개 HTTPS API 주소를 확인한 뒤 고급 입력을 이용해 주세요.")
    except CustomProviderError as exc:
        if exc.upstream_status in (401, 403):
            result["reason"] = "공급자가 키를 거부했습니다(401·403). 키·권한을 확인하거나 고급 입력을 이용해 주세요."
        else:
            result["reason"] = "공급자 연결을 확인하지 못했습니다. 네트워크·한도를 확인하거나 고급 입력을 이용해 주세요."
    except Exception:
        result["reason"] = "공급자 연결을 확인하지 못했습니다. 네트워크를 확인하거나 고급 입력을 이용해 주세요."
    return result


async def _probe_byok(client, spec, key, endpoint):
    # Public catalogs alone cannot establish key validity (OpenRouter/HF).
    if spec.provider_id in {"openrouter", "huggingface"} and endpoint == spec.base_origin:
        url = (endpoint + "/key" if spec.provider_id == "openrouter"
               else "https://huggingface.co/api/whoami-v2")
        await client._stream_request("GET", url, headers=_headers(spec, key),
                                     body=None, consume=_read_bounded)
    if spec.models_path is not None:
        try:
            result = await client.list_models(provider_id=spec.provider_id,
                                              api_key=key, endpoint=endpoint)
            return result["models"]
        except CustomProviderError as exc:
            if exc.upstream_status not in (404, 405) or not spec.models:
                raise
    if not spec.models:
        return []
    endpoint = await client._safe_endpoint(spec, endpoint)
    model = spec.upstream_model(spec.models[0])
    body = _request_body(spec, model, [{"role": "user", "content": "Hi"}], None, False)
    body["max_tokens"] = 1
    raw = await client._stream_request("POST", _request_url(spec, endpoint, model, False),
        headers=_headers(spec, key), body=body, consume=_read_bounded)
    if not isinstance(_parse_json(raw).get("choices"), list):
        raise _malformed()
    return list(spec.models)
