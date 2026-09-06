"""Identity-bound Engine service for completed-execution idempotency replay.

#1964 source slice (governance-compliant, no manifest activation). A trusted
durable ``CloudflareD1IdempotencyAdapter`` is the only replay authority: the
service reuses the exact records written by Core's contextual execution path
(``app_id`` + ``context.idempotency_key`` with state ``completed``). Absence of
the adapter is fail-closed — the service never installs a process-local store
and never re-executes or fabricates a result. The Engine contract manifest
keeps ``execution_idempotency_replay_completed`` DEFERRED until the #1235
Production activation blockers are proven in a separately authorized change.
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
        execution_id = payload.get("execution_id")
        if not isinstance(execution_id, str) or not _IDENTIFIER_RE.fullmatch(execution_id):
            return _service_error(
                "invalid_request",
                "execution_id must be a bounded safe identifier.",
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
                execution_id=execution_id,
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
        execution_id: str,
    ) -> dict[str, Any]:
        assert self._idempotency_adapter is not None
        # The durable record is keyed by the exact pair Core's contextual
        # execution writes (app_id, context.idempotency_key) with
        # request_fingerprint bound at begin/complete time. Replay proves
        # identity for the same app scope; it never grants new authority and
        # never re-executes.
        public = await self._completed_public_result(
            app_id=app_id, idempotency_key=execution_id
        )
        if public is None:
            return {
                "ok": True,
                "replayed": False,
                "execution_id": execution_id,
                "reason": "completed_execution_not_found",
            }
        return {
            "ok": True,
            "replayed": True,
            "execution_id": execution_id,
            "result": public,
        }

    async def _completed_public_result(
        self, *, app_id: str, idempotency_key: str
    ) -> dict[str, Any] | None:
        assert self._idempotency_adapter is not None
        record = await self._idempotency_adapter._record(
            app_id=app_id, idempotency_key=idempotency_key
        )
        if record is None:
            return None
        if record.get("state") != _STATE_COMPLETED:
            # A reservation still in flight is never replayable and never
            # treated as a completed result.
            return None
        if not record.get("result_json"):
            return None
        try:
            return dict(json.loads(str(record["result_json"])))
        except (TypeError, ValueError):
            return None
