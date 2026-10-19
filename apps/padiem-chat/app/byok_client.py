"""PADIEM Custom direct provider execution (B14-independent).

The customer-owned key goes straight to the explicitly selected provider
origin. This module never calls the B14 service binding, B14 router, model
registry, default/fallback selection or the platform provider secret store.
Provider responses are normalized to the same ``{"answer": ...}`` product shape
used by the managed path; vendor bodies never reach the browser.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from . import httpx_compat as httpx
from .b14_client import PADIEM_IDENTITY_INSTRUCTION
from .byok_credentials import CustomProvider, resolve_custom_selection
from .request_contract import CustomModelSelection

MAX_CUSTOM_RESPONSE_BYTES = 1_000_000
CUSTOM_SESSION_HEADER = "padiem-chat-custom/1.0"


@dataclass
class CustomProviderError(Exception):
    status_code: int
    code: str
    user_message: str

    def __str__(self) -> str:
        return self.user_message


def _wire_messages(
    messages: list[dict[str, str]], system_context: str | None
) -> list[dict[str, str]]:
    parts = [PADIEM_IDENTITY_INSTRUCTION]
    if isinstance(system_context, str) and system_context.strip():
        parts.append(system_context.strip())
    return [{"role": "system", "content": "\n\n".join(parts)}, *messages]


def _malformed() -> CustomProviderError:
    return CustomProviderError(
        502,
        "malformed_custom_provider_response",
        "PADIEM Custom 공급사 응답 형식을 확인할 수 없습니다. 다시 시도해 주세요.",
    )


async def _read_bounded(response: Any) -> bytes:
    raw = bytearray()
    async for chunk in response.aiter_bytes():
        if not isinstance(chunk, (bytes, bytearray, memoryview)):
            raise _malformed()
        raw.extend(bytes(chunk))
        if len(raw) > MAX_CUSTOM_RESPONSE_BYTES:
            raise CustomProviderError(
                502,
                "custom_provider_response_too_large",
                "PADIEM Custom 공급사 응답이 허용 크기를 초과했습니다.",
            )
    return bytes(raw)


def _normalize(spec: CustomProvider, raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise _malformed() from exc
    if not isinstance(payload, dict):
        raise _malformed()
    actual = payload.get("model")
    if actual is not None and actual != spec.upstream_model:
        # The selected model is never silently replaced.
        raise _malformed()
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise _malformed()
    item = choices[0]
    message = item.get("message") if isinstance(item, dict) else None
    if not isinstance(message, dict):
        raise _malformed()
    text = message.get("content")
    if not isinstance(text, str) or not text.strip():
        raise CustomProviderError(
            502,
            "empty_custom_provider_answer",
            "PADIEM Custom 공급사가 표시할 답변을 만들지 못했습니다. 다시 시도해 주세요.",
        )
    return {"answer": text}


class CustomProviderClient:
    """Direct HTTP client for the explicitly selected PADIEM Custom provider."""

    def __init__(self, *, transport: Any | None = None, timeout_seconds: float = 120.0):
        self._transport = transport
        self._timeout_seconds = float(timeout_seconds)

    async def complete(
        self,
        *,
        spec: CustomProvider,
        api_key: str,
        messages: list[dict[str, str]],
        system_context: str | None = None,
    ) -> dict[str, Any]:
        url = spec.base_origin.rstrip("/") + "/" + spec.wire
        body = {
            "model": spec.upstream_model,
            "messages": _wire_messages(messages, system_context),
        }
        headers = {
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            "User-Agent": CUSTOM_SESSION_HEADER,
            "x-opencode-session": "chat_" + uuid.uuid4().hex,
        }
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds,
                transport=self._transport,
            ) as client:
                async with client.stream(
                    "POST", url, headers=headers, json=body, follow_redirects=False
                ) as response:
                    status = int(response.status_code)
                    if status in (401, 403):
                        raise CustomProviderError(
                            502,
                            "custom_provider_auth_failed",
                            "PADIEM Custom 공급사가 API 키를 거부했습니다. 키를 확인해 주세요.",
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
                        )
                    raw = await _read_bounded(response)
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
        return _normalize(spec, raw)


async def resolve_owner_custom_credential(
    app_state: Any,
    *,
    uid: str,
    selection: CustomModelSelection,
) -> tuple[CustomProvider, str]:
    """Resolve the explicit provider and the owner's sealed key without dispatch.

    Products that must prove the request is executable before claiming a
    durable attempt token use this; the dispatch itself stays in
    ``complete_owner_custom``.
    """
    spec = resolve_custom_selection(selection.provider, selection.model)
    store = getattr(app_state, "custom_credential_store", None)
    client = getattr(app_state, "custom_provider_client", None)
    if store is None or client is None:
        raise CustomProviderError(
            503,
            "custom_provider_unavailable",
            "PADIEM Custom을 현재 사용할 수 없습니다.",
        )
    try:
        api_key = await store.api_key(uid, spec.provider_id)
    except Exception:
        raise CustomProviderError(
            503,
            "custom_credential_unavailable",
            "PADIEM Custom 자격증명을 확인할 수 없습니다.",
        )
    if not api_key:
        raise CustomProviderError(
            409,
            "custom_credential_required",
            "PADIEM Custom API 키를 먼저 등록해 주세요.",
        )
    return spec, api_key


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
    spec, api_key = await resolve_owner_custom_credential(
        app_state, uid=uid, selection=selection,
    )
    client = getattr(app_state, "custom_provider_client", None)
    return await client.complete(
        spec=spec,
        api_key=api_key,
        messages=messages,
        system_context=system_context,
    )
