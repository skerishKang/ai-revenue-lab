"""Authenticated, render-only B66 certified PDF download.

The existing approved assignment owns template selection. QuoteCore supplies
fully resolved values; this route neither interprets text nor calculates money.
"""

from __future__ import annotations

import inspect
import json
import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .auth_routes import auth_ready, current_user_id
from .b66_saved_quote_skill_store import SavedQuoteSkillStoreError, validate_row_id
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .claw_memory_routes import _resolve_memory_workspace

MAX_PDF_REQUEST_BYTES = 32 * 1024
MAX_PDF_RESPONSE_BYTES = 32 * 1024 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_NO_STORE = {
    "Cache-Control": "private, no-store, max-age=0", "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
}


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code, "message": "견적 PDF를 만들지 못했습니다."}},
        status_code=status, headers=_NO_STORE,
    )


def _duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(_: str) -> None:
    raise ValueError("non-finite JSON value")


def _approved_profile(saved: dict[str, Any], *, saved_skill_id: str, workspace_id: str) -> str | None:
    skill = saved.get("skill")
    fingerprint = saved.get("skill_fingerprint")
    if (
        saved.get("saved_skill_id") != saved_skill_id
        or saved.get("workspace_id") != workspace_id
        or saved.get("status") != "approved"
        or not isinstance(fingerprint, str) or not _SHA256.fullmatch(fingerprint)
        or not isinstance(skill, dict)
        or skill.get("fingerprint") != fingerprint
        or skill.get("calculationAuthority") != "quote-core"
        or skill.get("rendererContract") != "quote-template-renderer.v1"
    ):
        return None
    approval = skill.get("approval")
    profile = skill.get("internalTemplate")
    if (
        not isinstance(approval, dict) or approval.get("status") != "approved"
        or approval.get("skillFingerprint") != fingerprint
        or not isinstance(profile, dict)
    ):
        return None
    profile_hash = profile.get("fingerprint")
    profile_approval = profile.get("approval")
    if not isinstance(profile_hash, str) or not _SHA256.fullmatch(profile_hash):
        return None
    # The canonical built-in serializes with approval=null. The persisted
    # approved Skill already binds its internalTemplate; the private certificate
    # additionally binds this exact profile. This is not a runtime fallback.
    if profile_approval is None:
        if profile.get("builtin") is not True:
            return None
    elif (
        not isinstance(profile_approval, dict)
        or profile_approval.get("status") != "approved"
        or profile_approval.get("contentFingerprint") != profile_hash
    ):
        return None
    return profile_hash


def _filename(model: dict[str, Any]) -> str:
    facts = model.get("facts")
    meta = facts.get("meta") if isinstance(facts, dict) else None
    number = meta.get("quoteNo", "") if isinstance(meta, dict) else ""
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", str(number)[:120]).strip("._-")
    return "quote-" + (safe or "quotation") + ".pdf"


async def b66_certified_preview_base(request: Request) -> Response:
    if not auth_ready(request):
        return _error(401, "unauthorized")
    try:
        uid = current_user_id(request)
    except Exception:
        uid = None
    if not uid:
        return _error(401, "unauthorized")
    if set(request.query_params.keys()) != {"saved_skill_id"}:
        return _error(400, "unsupported_field")
    try:
        saved_skill_id = validate_row_id(request.query_params.get("saved_skill_id"))
    except SavedQuoteSkillStoreError:
        return _error(400, "invalid_saved_skill_id")

    skill_store = getattr(request.app.state, "b66_saved_quote_skill_store", None)
    get_skill = getattr(skill_store, "get_skill", None)
    preview_store = getattr(request.app.state, "b66_certified_preview_store", None)
    get_preview = getattr(preview_store, "get_preview", None)
    if not callable(get_skill) or not callable(get_preview):
        return _error(503, "certified_preview_unavailable")

    try:
        workspace_id = await _resolve_memory_workspace(request, uid)
    except Exception:
        workspace_id = None
    if workspace_id is None:
        return _error(503, "workspace_authority_unavailable")

    try:
        value = get_skill(user_id=uid, workspace_id=workspace_id, saved_skill_id=saved_skill_id)
        saved = await value if inspect.isawaitable(value) else value
    except Exception:
        return _error(503, "saved_quote_skill_read_failed")
    if saved is None:
        return _error(404, "saved_quote_skill_not_found")

    profile_fingerprint = (
        _approved_profile(saved, saved_skill_id=saved_skill_id, workspace_id=workspace_id)
        if isinstance(saved, dict) else None
    )
    if profile_fingerprint is None:
        return _error(503, "saved_quote_skill_invalid")

    try:
        value = get_preview(
            skill_fingerprint=saved["skill_fingerprint"],
            profile_fingerprint=profile_fingerprint,
        )
        body = await value if inspect.isawaitable(value) else value
    except Exception:
        return _error(503, "certified_preview_unavailable")
    if body is None:
        return _error(404, "certified_preview_not_found")

    return Response(
        body,
        media_type="image/png",
        headers={
            **_NO_STORE,
            "Content-Disposition": 'inline; filename="cgi-certified-preview.png"',
        },
    )


async def b66_certified_pdf(request: Request) -> Response:
    if not auth_ready(request):
        return _error(401, "unauthorized")
    try:
        uid = current_user_id(request)
    except Exception:
        uid = None
    if not uid:
        return _error(401, "unauthorized")
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return _error(415, "unsupported_media_type")
    try:
        body = await read_bounded_request_body(request, max_bytes=MAX_PDF_REQUEST_BYTES)
        data = json.loads(body.decode("utf-8"), object_pairs_hook=_duplicate_keys, parse_constant=_invalid_constant)
    except RequestBodyTooLarge:
        return _error(413, "request_too_large")
    except (ValueError, UnicodeDecodeError, RecursionError):
        return _error(400, "invalid_json")
    if not isinstance(data, dict) or set(data) != {"saved_skill_id", "render_model"}:
        return _error(400, "unsupported_field")
    try:
        saved_skill_id = validate_row_id(data.get("saved_skill_id"))
    except SavedQuoteSkillStoreError:
        return _error(400, "invalid_saved_skill_id")
    model = data.get("render_model")
    if (
        not isinstance(model, dict)
        or model.get("derivedBy") != "quote-core"
        or not isinstance(model.get("coreTotals"), dict)
        or not isinstance(model.get("writtenWords"), str)
        or not isinstance(model.get("taxReview"), dict)
        or model["taxReview"].get("required") is not False
        or not isinstance(model.get("template"), dict)
    ):
        return _error(422, "invalid_render_model")
    skill_store = getattr(request.app.state, "b66_saved_quote_skill_store", None)
    get_skill = getattr(skill_store, "get_skill", None)
    pdf_client = getattr(request.app.state, "b66_pdf_renderer_client", None)
    render_pdf = getattr(pdf_client, "render_pdf", None)
    if not callable(get_skill) or not callable(render_pdf):
        return _error(503, "certified_pdf_unavailable")
    try:
        workspace_id = await _resolve_memory_workspace(request, uid)
    except Exception:
        workspace_id = None
    if workspace_id is None:
        return _error(503, "workspace_authority_unavailable")
    try:
        value = get_skill(user_id=uid, workspace_id=workspace_id, saved_skill_id=saved_skill_id)
        saved = await value if inspect.isawaitable(value) else value
    except Exception:
        return _error(503, "saved_quote_skill_read_failed")
    if saved is None:
        return _error(404, "saved_quote_skill_not_found")
    profile_fingerprint = _approved_profile(saved, saved_skill_id=saved_skill_id, workspace_id=workspace_id) if isinstance(saved, dict) else None
    if profile_fingerprint is None:
        return _error(503, "saved_quote_skill_invalid")
    if model["template"].get("fingerprint") != profile_fingerprint:
        return _error(422, "render_template_mismatch")
    try:
        result = render_pdf(
            saved_skill_id=saved_skill_id,
            skill_fingerprint=saved["skill_fingerprint"],
            profile_fingerprint=profile_fingerprint,
            render_model=model,
        )
        result = await result if inspect.isawaitable(result) else result
    except Exception:
        return _error(503, "certified_pdf_unavailable")
    if (
        not isinstance(result, tuple) or len(result) != 3
        or type(result[0]) is not int or not isinstance(result[1], bytes)
        or not isinstance(result[2], str)
    ):
        return _error(503, "certified_pdf_failed")
    status, pdf, content_type = result
    if status == 422:
        return _error(422, "certified_pdf_input_rejected")
    if status != 200:
        return _error(503, "certified_pdf_unavailable")
    if (
        content_type.split(";", 1)[0].strip().lower() != "application/pdf"
        or not pdf.startswith(b"%PDF-")
        or len(pdf) > MAX_PDF_RESPONSE_BYTES
    ):
        return _error(503, "certified_pdf_failed")
    return Response(
        pdf, media_type="application/pdf",
        headers={**_NO_STORE, "Content-Disposition": f'attachment; filename="{_filename(model)}"'},
    )
