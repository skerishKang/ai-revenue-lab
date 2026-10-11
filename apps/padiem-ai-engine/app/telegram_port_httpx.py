"""httpx Telegram Bot API read port for the Engine Worker (#2353).

Implements the trusted :class:`padiem_ai_core.telegram_capability.TelegramReadPort`
contract here in the Engine, never in Padiem AI Core. The Engine runs as a
Python Worker (Pyodide) where all outbound HTTP is async through ``httpx``.

Telegram differs from the Google connectors in one safety-critical way: the
bot token is embedded in the provider URL path (``/bot<token>/<method>``), so
every exception that could carry the request URL is sanitized to a fixed safe
code before it leaves this module. The token value is never logged, never
included in any error string, and never crosses into Core, model or task
state.

Authority boundaries promoted from the reviewed B54 contract
(``apps/korean-ai-code-agent/src/kagent/telegram_contracts.py``):

* the official Bot API host (``api.telegram.org``) is the only transport;
* only the two promoted READ methods (``getMe``, ``getChat``) are callable;
  sendMessage/sendDocument/editMessageText/answerCallbackQuery are NOT
  implemented here and no send path exists;
* ``getChat`` is restricted to the server-derived paired-chat allowlist
  (``ENGINE_TELEGRAM_PAIRED_CHAT_IDS``); an unpaired or empty allowlist fails
  closed, so the bot can never read arbitrary private chats;
* webhook/getUpdates are out of scope for this port: inbound stays on the
  reviewed B62 routes and this port never registers a webhook.
"""

from __future__ import annotations

import json
import re
from typing import Any, Awaitable

import httpx

from padiem_ai_core.telegram_capability import (
    TELEGRAM_API_HOST,
    TELEGRAM_READONLY_AUTH_SCOPE,
    TelegramReadPort,
)

# Worker secret name. The value itself is never written to source, logs or
# error messages — only the name is declared here so callers know which
# secret to inject.
ENGINE_TELEGRAM_BOT_TOKEN = "ENGINE_TELEGRAM_BOT_TOKEN"

# Server-derived configuration (not a secret): comma-separated paired chat ids.
ENGINE_TELEGRAM_PAIRED_CHAT_IDS = "ENGINE_TELEGRAM_PAIRED_CHAT_IDS"

TELEGRAM_GET_ME_PATH = "/getMe"
TELEGRAM_GET_CHAT_PATH = "/getChat"
ALLOWED_TELEGRAM_METHOD_PATHS = frozenset({TELEGRAM_GET_ME_PATH, TELEGRAM_GET_CHAT_PATH})

MAX_TELEGRAM_RESPONSE_BYTES = 1_000_000
PROVIDER_REQUEST_FAILED = "telegram_provider_request_failed"

_BOT_TOKEN_RE = re.compile(r"^[0-9]{6,64}:[A-Za-z0-9_-]{20,128}$")
_SAFE_PORT_ERROR_RE = re.compile(
    r"^(scope_not_permitted|method_not_permitted|host_not_permitted|chat_not_paired"
    r"|chat_id_invalid|response_too_large|provider_response_invalid|provider_http_[0-9]{3})$"
)


def parse_paired_chat_ids(value: str | None) -> frozenset[int]:
    """Parse the server-derived paired-chat allowlist. Fail-closed on garbage."""

    if value is None or not value.strip():
        return frozenset()
    chat_ids: set[int] = set()
    for item in value.split(","):
        token = item.strip()
        if not token:
            continue
        try:
            chat_id = int(token)
        except ValueError as exc:
            raise ValueError("chat_id_invalid") from exc
        if chat_id == 0 or not -(2**63) < chat_id < 2**63:
            raise ValueError("chat_id_invalid")
        chat_ids.add(chat_id)
    return frozenset(chat_ids)


class HttpxTelegramReadPort(TelegramReadPort):
    """Bounded Telegram Bot API GET port over httpx.

    Constructed only when the bot token secret and a non-empty server-derived
    paired-chat allowlist are present; the composition root
    (``worker_identity._telegram_port_for_env``) refuses to build the port
    otherwise, keeping Production fail-closed.
    """

    def __init__(
        self,
        *,
        bot_token: str,
        paired_chat_ids: frozenset[int],
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not isinstance(bot_token, str) or not _BOT_TOKEN_RE.fullmatch(bot_token):
            raise ValueError("bot_token_invalid")
        if not isinstance(paired_chat_ids, frozenset) or any(
            not isinstance(item, int) or isinstance(item, bool) for item in paired_chat_ids
        ):
            raise ValueError("chat_id_invalid")
        self._bot_token = bot_token
        self._paired_chat_ids = paired_chat_ids
        self._transport = transport

    # --- bounded provider GET -------------------------------------------

    async def _stream_get(
        self,
        *,
        url: str,
        params: dict[str, str] | None,
        max_response_bytes: int,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(
            transport=self._transport, timeout=timeout_seconds, follow_redirects=False
        ) as client:
            async with client.stream("GET", url, params=params) as response:
                status = response.status_code
                if status < 200 or status >= 300:
                    raise ValueError(f"provider_http_{status}")
                chunks = bytearray()
                async for chunk in response.aiter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > max_response_bytes:
                        raise ValueError("response_too_large")
                body = bytes(chunks)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ValueError("provider_response_invalid") from None
        if not isinstance(payload, dict):
            raise ValueError("provider_response_invalid")
        return payload

    # --- TelegramReadPort --------------------------------------------------

    async def get_json(
        self,
        *,
        binding_ref: str,
        actor_ref: str,
        required_scopes: tuple[str, ...],
        base_url: str,
        path: str,
        query: dict[str, str],
        timeout_seconds: int,
        max_response_bytes: int,
    ) -> dict[str, Any] | Awaitable[dict[str, Any]]:
        # (1) Scope gate: the port only ever runs the promoted readonly scope.
        if not set(required_scopes) <= {TELEGRAM_READONLY_AUTH_SCOPE}:
            raise ValueError("scope_not_permitted")
        # (2) Method gate: only the two promoted READ methods exist here.
        if path not in ALLOWED_TELEGRAM_METHOD_PATHS:
            raise ValueError("method_not_permitted")
        # (3) Host gate: the official Bot API host is the only transport.
        host = base_url.split("://", 1)[-1].split("/", 1)[0]
        if host != TELEGRAM_API_HOST:
            raise ValueError("host_not_permitted")
        # (4) Pairing gate: chat reads stay inside the server-derived allowlist.
        if path == TELEGRAM_GET_CHAT_PATH:
            raw_chat_id = (query or {}).get("chat_id")
            try:
                chat_id = int(str(raw_chat_id))
            except (TypeError, ValueError):
                raise ValueError("chat_id_invalid") from None
            if chat_id == 0 or not -(2**63) < chat_id < 2**63 or chat_id not in self._paired_chat_ids:
                raise ValueError("chat_not_paired")
        # (5) Token-bearing request. From here on, every error path must be a
        # safe fixed code: the URL embeds the raw bot token.
        url = f"https://{TELEGRAM_API_HOST}/bot{self._bot_token}{path}"
        params = {key: str(value) for key, value in (query or {}).items()} or None
        bound = max(1, min(int(max_response_bytes), MAX_TELEGRAM_RESPONSE_BYTES))
        try:
            return await self._stream_get(
                url=url,
                params=params,
                max_response_bytes=bound,
                timeout_seconds=timeout_seconds,
            )
        except ValueError as exc:
            if _SAFE_PORT_ERROR_RE.fullmatch(str(exc)):
                raise
            # Raised below (outside the handler) so neither __cause__ nor an
            # implicit __context__ can carry the token-bearing URL.
            failure: Exception = ValueError(PROVIDER_REQUEST_FAILED)
        except Exception:
            failure = ValueError(PROVIDER_REQUEST_FAILED)
        raise failure


__all__ = [
    "ALLOWED_TELEGRAM_METHOD_PATHS",
    "ENGINE_TELEGRAM_BOT_TOKEN",
    "ENGINE_TELEGRAM_PAIRED_CHAT_IDS",
    "HttpxTelegramReadPort",
    "TelegramReadPort",
    "parse_paired_chat_ids",
]
