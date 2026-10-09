"""HTTPS multipart sendDocument transport for the existing Telegram artifact adapter.

This is the concrete implementation of #3666's injected TelegramDocumentSendPort,
NOT another connector/approval/artifact authority. The trusted adapter provides
the token and chat id only after channel re-resolution, scoped materialization
and existing approval checks. This transport never reads credentials from an
environment or a model prompt and is not wired to any Production service.

#2010 SEND/WRITE is NOT authorized: the module's presence enables no live send.
A later separately approved host composition must opt into using this class.

Telegram Bot API documentation: https://core.telegram.org/bots/api#senddocument
Uses multipart/form-data for new document bytes. Requests go to the one pinned
Bot API host, use TLS verification, never follow redirects or retry, and never
include a raw provider body or token in an exception message.
"""

from __future__ import annotations

import http.client
import json
import re
import secrets
import ssl
from typing import Any
from urllib.parse import quote

from .contracts import ContractError
from .telegram_bot_runtime import (
    MAX_BOT_API_RESPONSE_BYTES,
    TELEGRAM_API_HOST,
    _bot_token,
    _provider_int,
)
from .telegram_contracts import MAX_TELEGRAM_FILE_BYTES

# Static contract markers for the inactive source-only slice.
REAL_MULTIPART_TRANSPORT_IMPLEMENTED = True
PRODUCTION_TELEGRAM_SEND_ACTIVATED = False
MODEL_DIRECT_TELEGRAM_HTTP = False
NEW_CONNECTOR_IDENTITY_AUTHORITY = False
NEW_SECRET_STORE = False
AUTO_RETRY = False
MAX_MULTIPART_OVERHEAD_BYTES = 2048

_MIME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*$")


def _filename_utf8(value: str) -> bytes:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ContractError("Telegram document filename must be bounded text")
    if value in {".", ".."} or any(ch in value for ch in ('/', '\\', '"', ':')):
        raise ContractError("Telegram document filename cannot contain path/header separators")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ContractError("Telegram document filename cannot contain control characters")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ContractError("Telegram document filename must be valid UTF-8") from None
    if not 1 <= len(encoded) <= 255:
        raise ContractError("Telegram document filename exceeds 255 UTF-8 bytes")
    return encoded


def _mime_type(value: str) -> bytes:
    if not isinstance(value, str) or len(value) > 127 or not _MIME_RE.fullmatch(value):
        raise ContractError("Telegram document MIME type is invalid")
    return value.encode("ascii")


def _timeout(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 60:
        raise ContractError("Telegram document timeout must be between 1 and 60 seconds")
    return value


def _multipart_document(
    *,
    chat_id: int,
    document_bytes: bytes,
    filename_utf8: bytes,
    mime_type: bytes,
    boundary: str,
) -> bytes:
    """Build one bounded multipart body; no local path or file_id/URL shortcut."""
    boundary_bytes = boundary.encode("ascii")
    body = (
        b"--" + boundary_bytes + b'\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n'
        + str(chat_id).encode("ascii") + b"\r\n"
        + b"--" + boundary_bytes
        + b'\r\nContent-Disposition: form-data; name="document"; filename="'
        + filename_utf8 + b'"\r\nContent-Type: ' + mime_type + b"\r\n\r\n"
        + document_bytes
        + b"\r\n--" + boundary_bytes + b"--\r\n"
    )
    if len(body) > len(document_bytes) + MAX_MULTIPART_OVERHEAD_BYTES:
        raise ContractError("Telegram multipart envelope exceeds the bounded overhead")
    return body


class StdlibTelegramDocumentSendPort:
    """Concrete HTTPS implementation of TelegramDocumentSendPort (#3666).

    Source-only: not constructed or injected into Production by this change.
    Caller must be the trusted #3666 adapter; never call from model code.
    """

    def send_document(
        self,
        *,
        token: bytes,
        provider_chat_id: int,
        document_bytes: bytes,
        filename: str,
        mime_type: str,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        token_text = _bot_token(token)  # existing trusted Bot API token contract
        chat_id = _provider_int(provider_chat_id, "chat id")  # negative group ids valid
        timeout = _timeout(timeout_seconds)
        if not isinstance(document_bytes, bytes) or not 1 <= len(document_bytes) <= MAX_TELEGRAM_FILE_BYTES:
            raise ContractError("Telegram document must contain 1..10 MiB of bytes")
        name_bytes = _filename_utf8(filename)
        content_type = _mime_type(mime_type)

        # A random boundary makes file content unable to synthesize an
        # attacker-chosen multipart separator. No token/destination in logs.
        boundary = "padiem" + secrets.token_hex(16)
        body = _multipart_document(
            chat_id=chat_id,
            document_bytes=document_bytes,
            filename_utf8=name_bytes,
            mime_type=content_type,
            boundary=boundary,
        )

        conn: http.client.HTTPSConnection | None = None
        try:
            conn = http.client.HTTPSConnection(
                TELEGRAM_API_HOST,
                port=443,
                timeout=timeout,
                context=ssl.create_default_context(),
            )
            conn.request(
                "POST",
                f"/bot{quote(token_text, safe=':_-')}/sendDocument",
                body=body,
                headers={
                    "accept": "application/json",
                    "cache-control": "no-store",
                    "content-type": f"multipart/form-data; boundary={boundary}",
                    "content-length": str(len(body)),
                    "user-agent": "padiem-claw-telegram/0.1",
                },
            )
            response = conn.getresponse()
            status = response.status
            if isinstance(status, bool) or not isinstance(status, int) or not 200 <= status <= 599:
                raise ContractError("Telegram document response has invalid HTTP status")
            if 300 <= status < 400:
                raise ContractError("Telegram document redirect is refused")
            raw = response.read(MAX_BOT_API_RESPONSE_BYTES + 1)
            if len(raw) > MAX_BOT_API_RESPONSE_BYTES:
                raise ContractError("Telegram document response exceeds source bound")

            received_type = (response.getheader("content-type") or "").lower()
            if not received_type.startswith("application/json"):
                if status == 200:
                    raise ContractError("Telegram document success response must be JSON")
                return {"ok": False, "error_code": status, "description": ""}

            try:
                payload = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeError):
                if status == 200:
                    raise ContractError("Telegram document response is invalid JSON") from None
                return {"ok": False, "error_code": status, "description": ""}

            if type(payload) is not dict or type(payload.get("ok")) is not bool:
                raise ContractError("Telegram document response envelope is invalid")
            if status != 200 and payload["ok"]:
                raise ContractError("Telegram document HTTP status and result disagree")
            if status != 200 and (
                type(payload.get("error_code")) is not int
                or not 0 <= payload["error_code"] <= 10_000
            ):
                # Preserve HTTP retryability without surfacing error-body text.
                return {"ok": False, "error_code": status, "description": ""}
            return payload
        except (OSError, TimeoutError, ssl.SSLError, http.client.HTTPException):
            # Raw exceptions can embed /bot<TOKEN>/sendDocument URLs.
            # Never include original exception messages or response bytes.
            raise OSError("Telegram document transport unavailable") from None
        finally:
            if conn is not None:
                conn.close()
