"""#3580 B62 owner-only Hark local Office chooser, fail-closed in production.

A browser never supplies a P01 approval, command, path, credential, selected
root, workspace or device. Only a trusted owner/run-scoped source may return a
previously authorized listing and start a canonical Engine approval pause.
Existing /api/claw/approvals/decision remains the ONLY owner decision route.
"""
from __future__ import annotations

import inspect
import re
from typing import Any, Protocol

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .bounded_request_body import read_bounded_request_body, RequestBodyTooLarge

LIST_PATH = "/api/claw/office/candidates"
SELECT_PATH = "/api/claw/office/candidates/select"
_RUN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,127}$")
_TOKEN = re.compile(r"^[a-f0-9]{64}$")
_FORMATS = frozenset({"xls", "xlsx"})
_STATUSES = frozenset({"awaiting_approval", "running", "completed", "failed", "denied"})
_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache", "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


class TrustedHarkOfficeChooserSource(Protocol):
    configured: bool

    async def candidates(self, *, owner_id: str, run_id: str) -> Any: ...
    async def select(self, *, owner_id: str, run_id: str, candidate_ref: str) -> Any: ...


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code}},
        status_code=status, headers=_HEADERS,
    )


def _run(value: Any) -> str | None:
    return value if isinstance(value, str) and _RUN.fullmatch(value) else None


def _candidate(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    name = item.get("filename")
    kind = item.get("kind")
    size = item.get("size_bytes")
    token = item.get("candidate_ref")
    # Drop all source fields outside the public metadata allowlist.
    if (not isinstance(name, str) or not 1 <= len(name) <= 160
            or any(ord(ch) < 32 or ch in "/\\:" for ch in name)
            or kind not in _FORMATS or not name.casefold().endswith("." + kind)
            or type(size) is not int or not 0 < size <= 1_048_576
            or not isinstance(token, str) or not _TOKEN.fullmatch(token)):
        return None
    return {
        "filename": name, "kind": kind, "size_bytes": size,
        "candidate_ref": token,
    }


async def candidates(request: Request) -> JSONResponse:
    owner_id = current_user_id(request) if auth_ready(request) else None
    if owner_id is None:
        return _error(401, "unauthorized")
    run_id = _run(request.query_params.get("run_id"))
    if run_id is None:
        return _error(400, "invalid_run_id")
    source = getattr(request.app.state, "claw_office_chooser_source", None)
    if getattr(source, "configured", False) is not True:
        return _error(503, "office_chooser_unconfigured")
    try:
        result = source.candidates(owner_id=owner_id, run_id=run_id)
        if inspect.isawaitable(result):
            result = await result
    except Exception:
        return _error(503, "office_chooser_unavailable")
    if not isinstance(result, dict) or result.get("run_id") != run_id:
        return _error(404, "office_candidates_unavailable")
    if (result.get("read_authorized") is not False
            or result.get("metadata_only") is not True
            or type(result.get("candidates")) is not list
            or len(result["candidates"]) > 40):
        return _error(503, "office_chooser_invalid_source")
    projected = [_candidate(item) for item in result["candidates"]]
    if any(item is None for item in projected) or len({
        item["candidate_ref"] for item in projected if item is not None
    }) != len(projected):
        return _error(503, "office_chooser_invalid_source")
    return JSONResponse({
        "ok": True,
        "contract_version": "hark-office-owner-chooser.v1",
        "run_id": run_id,
        "candidates": projected,
        "limited": result.get("limited") is True,
        "metadata_only": True, "read_authorized": False,
        "requires_engine_approval": True,
    }, headers=_HEADERS)


async def select_candidate(request: Request) -> JSONResponse:
    owner_id = current_user_id(request) if auth_ready(request) else None
    if owner_id is None:
        return _error(401, "unauthorized")
    if (request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            != "application/json"):
        return _error(415, "unsupported_media_type")
    try:
        raw = await read_bounded_request_body(request, max_bytes=1024)
    except RequestBodyTooLarge:
        return _error(413, "request_too_large")
    try:
        import json
        body = json.loads(raw)
    except (UnicodeDecodeError, ValueError, TypeError):
        return _error(400, "invalid_json")
    if not isinstance(body, dict) or set(body) != {"run_id", "candidate_ref"}:
        return _error(400, "invalid_selection_shape")
    run_id, candidate_ref = _run(body["run_id"]), body["candidate_ref"]
    if run_id is None or not isinstance(candidate_ref, str) or not _TOKEN.fullmatch(candidate_ref):
        return _error(400, "invalid_selection")
    source = getattr(request.app.state, "claw_office_chooser_source", None)
    if getattr(source, "configured", False) is not True:
        return _error(503, "office_chooser_unconfigured")
    try:
        result = source.select(
            owner_id=owner_id, run_id=run_id, candidate_ref=candidate_ref,
        )
        if inspect.isawaitable(result):
            result = await result
    except Exception:
        return _error(503, "office_selection_unavailable")
    # Source is ONLY permitted to return a genuinely persisted canonical Engine
    # pause for the exact chosen request, never a local "approved" shortcut.
    if (not isinstance(result, dict)
            or result.get("run_id") != run_id
            or result.get("candidate_ref") != candidate_ref
            or result.get("approval_required") is not True
            or result.get("status") != "awaiting_approval"
            or _run(result.get("engine_run_id")) is None):
        return _error(409, "p01_engine_pause_not_verified")
    return JSONResponse({
        "ok": True, "run_id": run_id,
        "engine_run_id": result["engine_run_id"],
        "status": "awaiting_approval",
        "approval_required": True,
        "file_read_authorized": False,
        "processing_started": False,
    }, headers=_HEADERS)


PRODUCTION_HARK_OFFICE_CHOOSER_ENABLED = False
