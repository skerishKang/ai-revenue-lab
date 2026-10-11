"""#3580 Hark owner-only PDF preview from canonically ACKed Broker Office output.

This is the *existing* B62 private owner-run-verified Office reader projected
to its owner, without any new file read permission, device authority or Drive
WRITE. Server gets owner from cookie only; the browser supplies only run id.
"""
from __future__ import annotations

import inspect
import re

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .auth_routes import auth_ready, current_user_id
from .claw_local_office_binary_reader import MAX_OFFICE_BYTES, VerifiedOfficeBinary

OFFICE_PDF_PREVIEW_PATH = "/api/claw/office/runs/{run_id}/pdf"
_RUN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,127}$")
_HEADERS = {
    "Cache-Control": "private, no-store, max-age=0",
    "Pragma": "no-cache",
    "Vary": "Cookie",
    "Content-Security-Policy": "sandbox",
    "Cross-Origin-Resource-Policy": "same-origin",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "SAMEORIGIN",
}


def _refuse(status: int, code: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": {"code": code}},
                        status_code=status, headers=_HEADERS)


async def claw_office_pdf_preview(request: Request) -> Response:
    owner_id = current_user_id(request) if auth_ready(request) else None
    if owner_id is None:
        return _refuse(401, "unauthorized")
    run_id = request.path_params.get("run_id")
    if type(run_id) is not str or not _RUN.fullmatch(run_id):
        return _refuse(400, "invalid_run_id")
    source = getattr(request.app.state, "local_task_result_source", None)
    reader = getattr(source, "read_staged_office_output", None)
    if not callable(reader) or getattr(source, "configured", True) is not True:
        return _refuse(503, "office_pdf_source_unconfigured")
    try:
        output = reader(owner_id=owner_id, run_ref=run_id, kind="pdf")
        if inspect.isawaitable(output):
            output = await output
    except Exception:
        # Never disclose missing run vs foreign owner, device, Drive or Broker.
        return _refuse(404, "office_pdf_unavailable")
    if (not isinstance(output, VerifiedOfficeBinary)
            or output.kind != "pdf" or output.media_type != "application/pdf"
            or not isinstance(output.content, bytes)
            or not 8 <= len(output.content) <= MAX_OFFICE_BYTES
            or not output.content.startswith(b"%PDF-")
            or b"%%EOF" not in output.content[-1024:]):
        return _refuse(503, "office_pdf_invalid")
    return Response(
        output.content, media_type="application/pdf", headers={
            **_HEADERS,
            "Content-Disposition": 'inline; filename="hark-office.pdf"',
            "Content-Length": str(len(output.content)),
        },
    )


OFFICE_PDF_PREVIEW_NEW_APPROVAL_AUTHORITY = False
OFFICE_PDF_PREVIEW_DRIVE_WRITE = False
