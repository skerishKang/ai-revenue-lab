"""#3580/#4434 owner-only Office output read from canonically ACKed Broker staging.

This is the *existing* B62 private owner-run-verified Office reader projected
to its owner, without any new file read permission, device authority or Drive
WRITE. Server gets owner from cookie only; the browser supplies only run id.

#4434 completes the return half on the same seam: the owner of a completed run
can ask which Office outputs the approved PC produced (`/outputs`, metadata only,
never bytes) and download the revised workbook itself (`/xlsx`, attachment). Both
reuse `read_staged_office_output`, which already re-validates the owner-bound
completed run row, the stored command correlation, the canonical Broker terminal
fact and the whole-file digest before returning a single byte.
"""
from __future__ import annotations

import inspect
import re
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .auth_routes import auth_ready, current_user_id
from .claw_local_office_binary_reader import MAX_OFFICE_BYTES, VerifiedOfficeBinary

OFFICE_PDF_PREVIEW_PATH = "/api/claw/office/runs/{run_id}/pdf"
OFFICE_XLSX_DOWNLOAD_PATH = "/api/claw/office/runs/{run_id}/xlsx"
OFFICE_OUTPUTS_QUERY_PATH = "/api/claw/office/runs/{run_id}/outputs"
OFFICE_OUTPUT_KINDS = ("xlsx", "pdf")
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
# The container each kind has to start — and for PDF end — with. The private
# reader checked this before returning; the route repeats it because a browser
# gets the bytes, not the reader.
_SIGNATURES = {
    "pdf": {"starts": b"%PDF-", "ends": b"%%EOF", "floor": 8},
    "xlsx": {"starts": b"PK\x03\x04", "ends": None, "floor": 22},
}


def _refuse(status: int, code: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": {"code": code}},
                        status_code=status, headers=_HEADERS)


def _staged_reader(request: Request):
    """The existing private owner-run-verified source port, or None.

    Absent is a configuration fact, never a guess: an unconfigured staging lane
    answers 503, it does not answer "you have no files".
    """
    source = getattr(request.app.state, "local_task_result_source", None)
    reader = getattr(source, "read_staged_office_output", None)
    if not callable(reader) or getattr(source, "configured", True) is not True:
        return None
    return reader


async def _staged(reader, *, owner_id: str, run_id: str, kind: str):
    """One retrieval for the owner-facing byte routes, with its own refusal code.

    A source that raises is not this owner's run and answers the same bounded 404
    the PDF preview gives, so a caller cannot probe which run ids exist. A source
    that returns bytes which are not a well-formed container of that kind is a
    staging integrity failure and answers 503 — the existing split, kept.
    """
    try:
        output = reader(owner_id=owner_id, run_ref=run_id, kind=kind)
        if inspect.isawaitable(output):
            output = await output
    except Exception:
        # Never disclose missing run vs foreign owner, device, Drive or Broker.
        return _refuse(404, f"office_{kind}_unavailable")
    signature = _SIGNATURES[kind]
    if (not isinstance(output, VerifiedOfficeBinary) or output.kind != kind
            or not isinstance(output.content, bytes)
            or not signature["floor"] <= len(output.content) <= MAX_OFFICE_BYTES
            or not output.content.startswith(signature["starts"])
            or (signature["ends"] is not None
                and signature["ends"] not in output.content[-1024:])):
        return _refuse(503, f"office_{kind}_invalid")
    return output


def _attachment(filename: str) -> str:
    # The reader already refused a name with a path separator, over 160 chars or
    # not ending in the kind's own extension. A header value has its own
    # alphabet, so the real name travels RFC 5987-encoded exactly as the existing
    # Drive artifact download does, with no client-controlled literal.
    return f"attachment; filename*=UTF-8''{quote(filename, safe='')}"


async def claw_office_pdf_preview(request: Request) -> Response:
    owner_id = current_user_id(request) if auth_ready(request) else None
    if owner_id is None:
        return _refuse(401, "unauthorized")
    run_id = request.path_params.get("run_id")
    if type(run_id) is not str or not _RUN.fullmatch(run_id):
        return _refuse(400, "invalid_run_id")
    reader = _staged_reader(request)
    if reader is None:
        return _refuse(503, "office_pdf_source_unconfigured")
    output = await _staged(reader, owner_id=owner_id, run_id=run_id, kind="pdf")
    if isinstance(output, JSONResponse):
        return output
    if output.media_type != "application/pdf":
        return _refuse(503, "office_pdf_invalid")
    return Response(
        output.content, media_type="application/pdf", headers={
            **_HEADERS,
            "Content-Disposition": 'inline; filename="hark-office.pdf"',
            "Content-Length": str(len(output.content)),
        },
    )


async def claw_office_xlsx_download(request: Request) -> Response:
    """The revised workbook itself, as an attachment, to its own owner only."""
    owner_id = current_user_id(request) if auth_ready(request) else None
    if owner_id is None:
        return _refuse(401, "unauthorized")
    run_id = request.path_params.get("run_id")
    if type(run_id) is not str or not _RUN.fullmatch(run_id):
        return _refuse(400, "invalid_run_id")
    reader = _staged_reader(request)
    if reader is None:
        return _refuse(503, "office_xlsx_source_unconfigured")
    output = await _staged(reader, owner_id=owner_id, run_id=run_id, kind="xlsx")
    if isinstance(output, JSONResponse):
        return output
    return Response(
        output.content, media_type=output.media_type, headers={
            **_HEADERS,
            "Content-Disposition": _attachment(output.filename),
            "Content-Length": str(len(output.content)),
        },
    )


async def claw_office_outputs_query(request: Request) -> Response:
    """Which Office outputs this owner can retrieve for this run — metadata only.

    A kind that is not staged, not verified or not this owner's is simply not
    listed, and if nothing is retrievable the answer is the same bounded 404 the
    byte routes give: an empty list would tell a caller that the run is theirs
    and just happens to have no file, which is a fact this seam must not share.
    """
    owner_id = current_user_id(request) if auth_ready(request) else None
    if owner_id is None:
        return _refuse(401, "unauthorized")
    run_id = request.path_params.get("run_id")
    if type(run_id) is not str or not _RUN.fullmatch(run_id):
        return _refuse(400, "invalid_run_id")
    reader = _staged_reader(request)
    if reader is None:
        return _refuse(503, "office_outputs_source_unconfigured")
    outputs = []
    for kind in OFFICE_OUTPUT_KINDS:
        retrieved = await _staged(reader, owner_id=owner_id, run_id=run_id, kind=kind)
        if isinstance(retrieved, VerifiedOfficeBinary):
            outputs.append(retrieved.public_projection())
    if not outputs:
        return _refuse(404, "office_outputs_unavailable")
    return JSONResponse(
        {"ok": True, "run_id": run_id, "outputs": outputs,
         "private_staging_only": True, "raw_bytes_in_projection": False},
        headers=_HEADERS,
    )


OFFICE_PDF_PREVIEW_NEW_APPROVAL_AUTHORITY = False
OFFICE_PDF_PREVIEW_DRIVE_WRITE = False
OFFICE_XLSX_DOWNLOAD_NEW_APPROVAL_AUTHORITY = False
OFFICE_XLSX_DOWNLOAD_DRIVE_WRITE = False
