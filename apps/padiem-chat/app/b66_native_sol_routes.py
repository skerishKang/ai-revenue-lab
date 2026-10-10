"""#4117: opt-in authenticated native Sol PDF response boundary.

This does not activate or implement a Sol runtime. A separately certified native
Sol client and trusted release metadata must be injected by the server owner.
Never delegate to the legacy single-page PDF Worker or the browser renderer.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import re
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from .auth_routes import auth_ready, current_user_id
from .b66_saved_quote_skill_store import SavedQuoteSkillStoreError, validate_row_id
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .claw_memory_routes import _resolve_memory_workspace
from .b66_certified_pdf_routes import (
    MAX_PDF_REQUEST_BYTES, MAX_PDF_RESPONSE_BYTES, _NO_STORE, _approved_profile,
    _duplicate_keys, _error, _filename, _invalid_constant,
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _certified_release(releases: Any, item_count: int) -> dict[str, Any] | None:
    if not isinstance(releases, dict) or not (1 <= item_count <= 100):
        return None
    # The v1 certificate has no 4+ coverage. A distinct v2 certificate must
    # be explicitly injected; do not inherit the v1 certificate by inference.
    release = releases.get("v1" if item_count <= 3 else "v2")
    if (
        not isinstance(release, dict)
        or release.get("status") != "CERTIFIED"
        or release.get("renderer") != "sol61-native"
        or not isinstance(release.get("certificateSha256"), str)
        or not _HEX64.fullmatch(release["certificateSha256"])
        or type(release.get("minItems")) is not int
        or type(release.get("maxItems")) is not int
        or not (release["minItems"] <= item_count <= release["maxItems"])
        or (item_count <= 3 and release["maxItems"] > 3)
        or (item_count >= 4 and release["minItems"] < 4)
    ):
        return None
    return release


def _valid_quote_model(model: Any) -> int:
    if (
        not isinstance(model, dict) or model.get("derivedBy") != "quote-core"
        or not isinstance(model.get("template"), dict)
        or model["template"].get("approved") is not True
        or not isinstance(model.get("coreTotals"), dict)
        or not isinstance(model.get("writtenWords"), str)
        or not isinstance(model.get("taxReview"), dict)
        or model["taxReview"].get("required") is not False
    ):
        return 0
    effective = model["coreTotals"].get("effectiveItems")
    if not isinstance(effective, list) or not effective:
        return 0
    return len(effective) if len(effective) <= 100 else 0


async def b66_native_sol_pdf(request: Request) -> Response:
    if not auth_ready(request):
        return _error(401, "unauthorized")
    try:
        user_id = current_user_id(request)
    except Exception:
        user_id = None
    if not user_id:
        return _error(401, "unauthorized")
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return _error(415, "unsupported_media_type")
    try:
        body = await read_bounded_request_body(request, max_bytes=MAX_PDF_REQUEST_BYTES)
        data = json.loads(body.decode("utf-8"), object_pairs_hook=_duplicate_keys,
                          parse_constant=_invalid_constant)
    except RequestBodyTooLarge:
        return _error(413, "request_too_large")
    except (ValueError, UnicodeDecodeError, RecursionError):
        return _error(400, "invalid_json")
    if not isinstance(data, dict) or set(data) != {"saved_skill_id", "render_model"}:
        return _error(400, "unsupported_field")
    try:
        saved_skill_id = validate_row_id(data["saved_skill_id"])
    except SavedQuoteSkillStoreError:
        return _error(400, "invalid_saved_skill_id")
    model = data["render_model"]
    item_count = _valid_quote_model(model)
    if not item_count:
        return _error(422, "invalid_render_model")

    # Both are intentionally absent in the production factory. A verified
    # runtime and independently issued release certificate are prerequisites.
    client = getattr(request.app.state, "b66_native_sol_pdf_client", None)
    render = getattr(client, "render_pdf", None)
    releases = getattr(request.app.state, "b66_native_sol_releases", None)
    release = _certified_release(releases, item_count)
    store = getattr(request.app.state, "b66_saved_quote_skill_store", None)
    get_skill = getattr(store, "get_skill", None)
    if not callable(render) or release is None or not callable(get_skill):
        return _error(503, "native_sol_not_certified")
    try:
        workspace_id = await _resolve_memory_workspace(request, user_id)
    except Exception:
        workspace_id = None
    if workspace_id is None:
        return _error(503, "workspace_authority_unavailable")
    try:
        saved_value = get_skill(
            user_id=user_id, workspace_id=workspace_id, saved_skill_id=saved_skill_id)
        saved = await saved_value if inspect.isawaitable(saved_value) else saved_value
    except Exception:
        return _error(503, "saved_quote_skill_read_failed")
    if saved is None:
        return _error(404, "saved_quote_skill_not_found")
    profile = (_approved_profile(saved, saved_skill_id=saved_skill_id,
                                  workspace_id=workspace_id)
               if isinstance(saved, dict) else None)
    if not profile:
        return _error(503, "saved_quote_skill_invalid")
    if model["template"].get("fingerprint") != profile:
        return _error(422, "render_template_mismatch")
    try:
        result = render(
            saved_skill_id=saved_skill_id,
            skill_fingerprint=saved["skill_fingerprint"],
            profile_fingerprint=profile,
            render_model=model,
            release=release,
        )
        result = await result if inspect.isawaitable(result) else result
    except Exception:
        return _error(503, "native_sol_renderer_unavailable")

    # No header may be invented from the submitted model or unverified
    # renderer result. Require an exact native identity and response SHA.
    if not isinstance(result, dict):
        return _error(503, "native_sol_response_invalid")
    pdf = result.get("pdf")
    page_count = result.get("pageCount")
    if (
        result.get("renderer") != "sol61-native"
        or result.get("certificateSha256") != release["certificateSha256"]
        or result.get("skillFingerprint") != saved["skill_fingerprint"]
        or result.get("profileFingerprint") != profile
        or not isinstance(pdf, bytes)
        or not (8 <= len(pdf) <= MAX_PDF_RESPONSE_BYTES)
        or not pdf.startswith(b"%PDF-")
        or b"%%EOF" not in pdf[-1024:]
        or type(page_count) is not int or not (1 <= page_count <= 100)
        or (item_count <= 3 and page_count != 1)
        or not isinstance(result.get("pdfSha256"), str)
        or not _HEX64.fullmatch(result["pdfSha256"])
        or hashlib.sha256(pdf).hexdigest() != result["pdfSha256"]
    ):
        return _error(503, "native_sol_response_invalid")
    return Response(pdf, media_type="application/pdf", headers={
        **_NO_STORE,
        "Content-Disposition": f'inline; filename="{_filename(model)}"',
        "X-B66-Sol-Renderer": "sol61-native",
        "X-B66-Sol-Certificate-Sha256": release["certificateSha256"],
        "X-B66-Sol-Pdf-Sha256": result["pdfSha256"],
        "X-B66-Sol-Profile-Fingerprint": profile,
        "X-B66-Sol-Skill-Fingerprint": saved["skill_fingerprint"],
        "X-B66-Sol-Page-Count": str(page_count),
    })
