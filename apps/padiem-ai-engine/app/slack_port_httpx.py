"""httpx Slack Web API read port for the Engine Worker (#2356).

Implements the trusted :class:`padiem_ai_core.slack_capability.SlackReadPort`
contract here in the Engine, never in Padiem AI Core. The Engine runs as a
Python Worker (Pyodide) where all outbound HTTP is async through ``httpx``.

Slack differs from the Telegram port in one transport detail: the bot token is
carried as a bearer authorization header, not inside the provider URL. Every
exception that could carry request context is still sanitized to a fixed safe
code before it leaves this module. The token value is never logged, never
included in any error string, and never crosses into Core, model or task
state.

Authority boundaries promoted from the reviewed B54 contract
(``apps/korean-ai-code-agent/src/kagent/slack_contracts.py``):

* the official Slack Web API host (``slack.com``) is the only transport;
* only the six promoted READ methods (``auth.test``, ``conversations.list``,
  ``conversations.history``, ``conversations.replies``, ``users.info``,
  ``files.info``) are callable; chat.postMessage/conversations.join/
  files.upload and every other write method are NOT implemented here and no
  send path exists;
* channel-scoped reads stay inside the server-derived channel allowlist
  (``ENGINE_SLACK_ALLOWED_CHANNELS``); ``conversations.list`` responses are
  filtered to that allowlist, and private channels are returned only when
  explicitly listed in ``ENGINE_SLACK_PRIVATE_CHANNELS`` (which must be a
  subset of the allowlist) — an empty allowlist fails closed;
* Events ingress and request-signature verification are out of scope for this
  port: inbound stays on the reviewed B54 product-local routes and this port
  never receives or replays events.
"""

from __future__ import annotations

import json
import re
from typing import Any, Awaitable

import httpx

from padiem_ai_core.slack_capability import (
    MAX_SLACK_CHANNELS,
    SLACK_API_HOST,
    SLACK_READONLY_AUTH_SCOPE,
    SlackReadPort,
)

# Worker secret name. The value itself is never written to source, logs or
# error messages — only the name is declared here so callers know which
# secret to inject.
ENGINE_SLACK_BOT_TOKEN = "ENGINE_SLACK_BOT_TOKEN"

# Server-derived configuration (not secrets): comma-separated channel ids.
ENGINE_SLACK_ALLOWED_CHANNELS = "ENGINE_SLACK_ALLOWED_CHANNELS"
ENGINE_SLACK_PRIVATE_CHANNELS = "ENGINE_SLACK_PRIVATE_CHANNELS"

SLACK_AUTH_TEST_PATH = "/api/auth.test"
SLACK_CONVERSATIONS_LIST_PATH = "/api/conversations.list"
SLACK_CONVERSATIONS_HISTORY_PATH = "/api/conversations.history"
SLACK_CONVERSATIONS_REPLIES_PATH = "/api/conversations.replies"
SLACK_USERS_INFO_PATH = "/api/users.info"
SLACK_FILES_INFO_PATH = "/api/files.info"
ALLOWED_SLACK_METHOD_PATHS = frozenset(
    {
        SLACK_AUTH_TEST_PATH,
        SLACK_CONVERSATIONS_LIST_PATH,
        SLACK_CONVERSATIONS_HISTORY_PATH,
        SLACK_CONVERSATIONS_REPLIES_PATH,
        SLACK_USERS_INFO_PATH,
        SLACK_FILES_INFO_PATH,
    }
)
CHANNEL_GATED_SLACK_PATHS = frozenset(
    {SLACK_CONVERSATIONS_HISTORY_PATH, SLACK_CONVERSATIONS_REPLIES_PATH}
)

MAX_SLACK_RESPONSE_BYTES = 1_000_000
PROVIDER_REQUEST_FAILED = "slack_provider_request_failed"

_BOT_TOKEN_RE = re.compile(r"^xoxb-[0-9A-Za-z\-]{10,256}$")
_CHANNEL_ID_RE = re.compile(r"^[A-Z][A-Z0-9]{5,24}$")
_SAFE_PORT_ERROR_RE = re.compile(
    r"^(scope_not_permitted|method_not_permitted|host_not_permitted|channel_not_allowed"
    r"|channel_id_invalid|response_too_large|provider_response_invalid|provider_http_[0-9]{3})$"
)


def parse_slack_channel_ids(value: str | None) -> frozenset[str]:
    """Parse a server-derived Slack channel allowlist. Fail-closed on garbage."""

    if value is None or not value.strip():
        return frozenset()
    channel_ids: set[str] = set()
    for item in value.split(","):
        token = item.strip()
        if not token:
            continue
        if not _CHANNEL_ID_RE.fullmatch(token):
            raise ValueError("channel_id_invalid")
        channel_ids.add(token)
    if len(channel_ids) > MAX_SLACK_CHANNELS:
        raise ValueError("channel_id_invalid")
    return frozenset(channel_ids)


class HttpxSlackReadPort(SlackReadPort):
    """Bounded Slack Web API POST port over httpx.

    Constructed only when the bot token secret and a non-empty server-derived
    channel allowlist are present; the composition root
    (``worker_identity._slack_port_for_env``) refuses to build the port
    otherwise, keeping Production fail-closed.
    """

    def __init__(
        self,
        *,
        bot_token: str,
        allowed_channel_ids: frozenset[str],
        explicitly_private_channel_ids: frozenset[str] = frozenset(),
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not isinstance(bot_token, str) or not _BOT_TOKEN_RE.fullmatch(bot_token):
            raise ValueError("bot_token_invalid")
        if not isinstance(allowed_channel_ids, frozenset) or any(
            not isinstance(item, str) or not _CHANNEL_ID_RE.fullmatch(item)
            for item in allowed_channel_ids
        ):
            raise ValueError("channel_id_invalid")
        if not isinstance(explicitly_private_channel_ids, frozenset) or any(
            not isinstance(item, str) or not _CHANNEL_ID_RE.fullmatch(item)
            for item in explicitly_private_channel_ids
        ):
            raise ValueError("channel_id_invalid")
        if not explicitly_private_channel_ids.issubset(allowed_channel_ids):
            raise ValueError("channel_id_invalid")
        if not allowed_channel_ids:
            raise ValueError("channel_id_invalid")
        self._bot_token = bot_token
        self._allowed_channel_ids = allowed_channel_ids
        self._explicitly_private_channel_ids = explicitly_private_channel_ids
        self._transport = transport

    # --- bounded provider POST -------------------------------------------

    async def _stream_post(
        self,
        *,
        url: str,
        headers: dict[str, str],
        data: dict[str, str],
        max_response_bytes: int,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(
            transport=self._transport, timeout=timeout_seconds, follow_redirects=False
        ) as client:
            async with client.stream("POST", url, headers=headers, data=data) as response:
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

    def _filter_conversations_list(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Server-derived scope filter for conversations.list provider output."""

        channels = payload.get("channels")
        if not isinstance(channels, list):
            return payload
        visible: list[Any] = []
        for channel in channels[: MAX_SLACK_CHANNELS * 4]:
            if not isinstance(channel, dict):
                continue
            channel_id = channel.get("id")
            if not isinstance(channel_id, str) or channel_id not in self._allowed_channel_ids:
                continue
            if channel.get("is_private") is True and (
                channel_id not in self._explicitly_private_channel_ids
            ):
                continue
            visible.append(channel)
        filtered = dict(payload)
        filtered["channels"] = visible
        return filtered

    # --- SlackReadPort -------------------------------------------------------

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
        if not set(required_scopes) <= {SLACK_READONLY_AUTH_SCOPE}:
            raise ValueError("scope_not_permitted")
        # (2) Method gate: only the six promoted READ methods exist here.
        if path not in ALLOWED_SLACK_METHOD_PATHS:
            raise ValueError("method_not_permitted")
        # (3) Host gate: the official Web API host is the only transport.
        host = base_url.split("://", 1)[-1].split("/", 1)[0]
        if host != SLACK_API_HOST:
            raise ValueError("host_not_permitted")
        # (4) Channel gate: channel reads stay inside the server-derived
        # allowlist; caller-supplied ids can never widen it.
        if path in CHANNEL_GATED_SLACK_PATHS:
            channel_id = (query or {}).get("channel")
            if not isinstance(channel_id, str) or not _CHANNEL_ID_RE.fullmatch(channel_id):
                raise ValueError("channel_id_invalid")
            if channel_id not in self._allowed_channel_ids:
                raise ValueError("channel_not_allowed")
        # (5) Token-bearing request. From here on, every error path must be a
        # safe fixed code: the bearer header carries the raw bot token.
        url = f"https://{SLACK_API_HOST}{path}"
        headers = {"Authorization": f"Bearer {self._bot_token}"}
        data = {key: str(value) for key, value in (query or {}).items()}
        bound = max(1, min(int(max_response_bytes), MAX_SLACK_RESPONSE_BYTES))
        try:
            payload = await self._stream_post(
                url=url,
                headers=headers,
                data=data,
                max_response_bytes=bound,
                timeout_seconds=timeout_seconds,
            )
        except ValueError as exc:
            if _SAFE_PORT_ERROR_RE.fullmatch(str(exc)):
                raise
            # Assigned below (outside the handler) so neither __cause__ nor an
            # implicit __context__ can carry the token-bearing request.
            failure: Exception = ValueError(PROVIDER_REQUEST_FAILED)
        except Exception:
            failure = ValueError(PROVIDER_REQUEST_FAILED)
        else:
            if path == SLACK_CONVERSATIONS_LIST_PATH:
                payload = self._filter_conversations_list(payload)
            return payload
        raise failure


__all__ = [
    "ALLOWED_SLACK_METHOD_PATHS",
    "CHANNEL_GATED_SLACK_PATHS",
    "ENGINE_SLACK_ALLOWED_CHANNELS",
    "ENGINE_SLACK_BOT_TOKEN",
    "ENGINE_SLACK_PRIVATE_CHANNELS",
    "HttpxSlackReadPort",
    "SlackReadPort",
    "parse_slack_channel_ids",
]
