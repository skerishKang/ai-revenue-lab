"""Identity-bound Engine service for completed-execution idempotency replay.

#1964 source slice (governance-compliant, no manifest activation). A trusted
durable ``CloudflareD1IdempotencyAdapter`` is the only replay authority: the
service reuses the exact records written by Core's contextual execution path
(``app_id`` + ``context.idempotency_key`` with state ``completed``).

Replay is NOT lookup (CTO review R1): the caller must present the original
request's ``request_fingerprint`` (the exact authority Core's ``begin()``
requires before it will hand back a completed result). Without it, a caller
who merely knows an ``idempotency_key`` could read another request's result
inside the same app scope — that authority widening is fail-closed here.

Absence of the adapter is fail-closed — the service never installs a
process-local store and never re-executes or fabricates a result. The Engine
contract manifest keeps ``execution_idempotency_replay_completed`` DEFERRED
until the #1235 Production activation blockers are proven in a separately
authorized change.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.idempotency_binding import CloudflareD1IdempotencyAdapter
from app.service import (
    MAX_REQUEST_BODY_BYTES,
    ServiceResponse,
    _service_error,
)

IDEMPOTENCY_COMPLETED_REPLAY_PATH = "/internal/v1/idempotency/completed/replay"

_STATE_COMPLETED = "completed"
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_REQUEST_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")


class IdempotencyReplayEngineService:
    """Fail-closed completed-execution replay over the durable adapter."""

    def __init__(self, *, idempotency_adapter: Any | None = None) -> None:
        if idempotency_adapter is not None and not isinstance(
            idempotency_adapter, CloudflareD1IdempotencyAdapter
        ):
            raise ValueError(
                "idempotency replay requires a trusted CloudflareD1IdempotencyAdapter"
            )
        self._idempotency_adapter = idempotency_adapter

    def health(self) -> ServiceResponse:
        return ServiceResponse(status_code=200, body={"ok": True, "service": "idempotency-replay"})

    async def handle(
        self,
        *,
        method: str,
        path: str,
        content_type: str | None = None,
        body: bytes = b"",
    ) -> ServiceResponse:
        normalized_method = method.upper() if isinstance(method, str) else ""
        if path != IDEMPOTENCY_COMPLETED_REPLAY_PATH:
            return _service_error("not_found", "Internal Engine route not found.", status_code=404)
        if normalized_method != "POST":
            return _service_error("method_not_allowed", "Method not allowed.", status_code=405)
        if (
            not isinstance(content_type, str)
            or content_type.split(";", 1)[0].strip().lower() != "application/json"
        ):
            return _service_error(
                "unsupported_media_type", "Content-Type must be application/json.", status_code=415
            )
        if not isinstance(body, (bytes, bytearray, memoryview)):
            return _service_error("invalid_request", "Request body is invalid.", status_code=400)
        raw = bytes(body)
        if len(raw) > MAX_REQUEST_BODY_BYTES:
            return _service_error(
                "request_too_large", "Request body exceeds the internal Engine safety limit.", status_code=413
            )
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _service_error(
                "invalid_json", "Request body must contain valid UTF-8 JSON.", status_code=400
            )

        if not isinstance(payload, dict):
            return _service_error("invalid_request", "Request body must be a JSON object.", status_code=400)

        app_id = payload.get("app_id")
        if not isinstance(app_id, str) or not app_id.strip():
            return _service_error("invalid_request", "app_id must be a non-empty string.", status_code=400)
        idempotency_key = payload.get("idempotency_key")
        if not isinstance(idempotency_key, str) or not _IDENTIFIER_RE.fullmatch(idempotency_key):
            return _service_error(
                "invalid_request",
                "idempotency_key must be a bounded safe identifier.",
                status_code=400,
            )
        request_fingerprint = payload.get("request_fingerprint")
        if not isinstance(request_fingerprint, str) or not _REQUEST_FINGERPRINT_RE.fullmatch(
            request_fingerprint
        ):
            return _service_error(
                "invalid_request",
                "request_fingerprint must be the original request's 64-character lowercase hex digest.",
                status_code=400,
            )

        if self._idempotency_adapter is None:
            return _service_error(
                "idempotency_unavailable",
                "Trusted durable idempotency authority is unavailable.",
                status_code=503,
            )

        try:
            replay_body = await self._replay_payload(
                app_id=app_id,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
            )
        except Exception:
            return _service_error(
                "idempotency_unavailable",
                "Trusted durable idempotency authority is unavailable.",
                status_code=503,
            )
        return ServiceResponse(status_code=200, body=replay_body)

    async def _replay_payload(
        self,
        *,
        app_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> dict[str, Any]:
        assert self._idempotency_adapter is not None
        # The durable record is keyed by the exact pair Core's contextual
        # execution writes (app_id, context.idempotency_key) and is bound to a
        # request_fingerprint at begin/complete time. Replay reuses Core's
        # authority semantics (CTO review R1): the adapter's public read
        # surface returns the completed result ONLY when the presented
        # fingerprint matches the one bound to the record. Replay never grants
        # new authority and never re-executes.
        public = await self._idempotency_adapter.read_completed(
            app_id=app_id,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
        )
        if public is None:
            return {
                "ok": True,
                "replayed": False,
                "idempotency_key": idempotency_key,
                "reason": "completed_execution_not_found",
            }
        return {
            "ok": True,
            "replayed": True,
            "idempotency_key": idempotency_key,
            "result": public,
        }
