"""#7500: the Util app's server-side Excel open & review.

The Util 탭's Excel 화면 reads the uploaded workbook through the repository's
one XLSX reading authority: ``padiem_ai_core.document_normalization.read_xlsx_table``
(the same bounded, sanitized openpyxl path the Chat attachment and file-lane
XLSX flows use) — no second parser exists here. Refusals reuse the shipped
Korean guidance wording via ``binary_documents.guidance_for_reason_code``.

The gates match the other Util surfaces and run in review order: a signed-in
session (quote route rule), the request header/format checks, the body read
under the hard and per-grade upload size caps (the document-conversion
policy), and only then the existing conversion usage bucket when the usage
gate is enforced — a malformed or oversized request never spends a daily
unit. The review is deterministic — it reaches no model, provider lane or
stored artifact, and the uploaded bytes are discarded after the response.
"""
from __future__ import annotations

from urllib.parse import unquote

from starlette.requests import Request
from starlette.responses import JSONResponse

from padiem_ai_core.document_normalization import (
    MAX_BINARY_DOCUMENT_BYTES,
    MAX_XLSX_ROWS,
    DocumentNormalizationError,
    read_xlsx_table,
)

from .auth_routes import auth_ready, current_user_id
from .binary_documents import guidance_for_reason_code
from .bounded_request_body import RequestBodyTooLarge, open_bounded_spooled_request
from .member_grade_access import verified_member_grade

UTIL_EXCEL_REVIEW_PATH = "/api/util/excel/review"
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

#: The preview table shows the head of the first readable sheet; the row bound
#: always stays inside ``read_xlsx_table``'s own MAX_XLSX_ROWS authority.
PREVIEW_ROW_LIMIT = 8
#: One review request lists at most this many sheets; a workbook past the cap
#: still reviews the head sheets and the summary says the list was cut.
MAX_REVIEW_SHEETS = 12
MAX_GOAL_CHARS = 500
_GRADE_KEYS = ("free", "plus", "pro", "max", "admin")


def _error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def _quota_denied(decision) -> JSONResponse:
    """The shared conversion-quota refusal shape (document_convert_routes)."""

    body = {
        "error": {
            "code": decision.code or "conversion_quota_exhausted",
            "message": decision.user_message or "오늘 변환 한도를 다 썼어요. 내일 다시 이용해 주세요.",
        }
    }
    if decision.limit is not None:
        body["conversion"] = {"daily_limit": decision.limit, "remaining": 0}
    return JSONResponse(body, status_code=decision.status_code or 429)


async def _grade_for_caps(request: Request, user_id: str) -> str:
    """Verified grade for the size cap; any failure falls back to free (pdfmd)."""

    try:
        grade = await verified_member_grade(request, user_id)
    except Exception:
        return "free"
    normalized = str(grade or "").strip().lower()
    return normalized if normalized in _GRADE_KEYS else "free"


def _policy_size_limit(settings: object, grade: str) -> int | None:
    """One per-grade upload cap; a missing grade falls back to free and an
    explicit ``None`` (the admin "unlimited" dial) is preserved (pdfmd rule)."""

    values = getattr(settings, "conversion_max_bytes", None)
    if not isinstance(values, dict):
        return None
    value = values.get(grade)
    if value is None:
        value = values.get("free")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _refusal(exc: DocumentNormalizationError) -> JSONResponse:
    """Translate one Core reason code through the shipped Korean guidance."""

    message = guidance_for_reason_code(exc.code, XLSX_MEDIA_TYPE)
    if message is None and exc.code == "xlsx_no_headers":
        # A sheet without a header row surfaces through the existing
        # "no readable values" wording — no new copy is introduced here.
        message = guidance_for_reason_code("xlsx_empty", XLSX_MEDIA_TYPE)
    if message is None:
        message = "XLSX 파일을 안전하게 읽지 못했습니다."
    status = 413 if exc.code == "document_size_limit" else 422
    return _error(exc.code, message, status)


async def util_excel_review(request: Request) -> JSONResponse:
    if not auth_ready(request) or current_user_id(request) is None:
        return _error("unauthorized", "로그인이 필요합니다.", 401)
    user_id = current_user_id(request)

    settings = getattr(request.app.state, "settings", None)
    usage_gate = getattr(request.app.state, "usage_gate", None)
    usage_gate_enforced = usage_gate is not None and getattr(
        request.app.state, "usage_gate_enforced", False
    )
    grade: str | None = None
    if settings is not None or usage_gate_enforced:
        grade = await _grade_for_caps(request, user_id)
    size_limit = None
    if settings is not None and grade is not None:
        size_limit = _policy_size_limit(settings, grade)

    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    declared_media = request.headers.get("x-padiem-media-type")
    encoded_name = request.headers.get("x-padiem-filename")
    if (
        media_type != "application/octet-stream"
        or declared_media != XLSX_MEDIA_TYPE
        or not encoded_name
        or len(encoded_name) > 512
    ):
        return _error("invalid_document", "XLSX 파일만 업로드할 수 있습니다.", 422)
    try:
        upload_name = unquote(encoded_name, encoding="utf-8", errors="strict")
    except (UnicodeDecodeError, ValueError):
        return _error("invalid_document", "파일 이름이 올바르지 않습니다.", 422)
    goal = str(request.query_params.get("goal") or "")[:MAX_GOAL_CHARS]

    try:
        async with open_bounded_spooled_request(
            request, max_bytes=MAX_BINARY_DOCUMENT_BYTES
        ) as spool:
            payload = spool.read()
    except RequestBodyTooLarge:
        return _error("document_too_large", "파일이 너무 큽니다.", 413)
    if not payload:
        return _error("invalid_document", "XLSX 파일만 업로드할 수 있습니다.", 422)
    if size_limit is not None and len(payload) > size_limit:
        return _error(
            "document_size_limit",
            f"파일이 회원 등급의 변환 크기 상한({size_limit // (1024 * 1024)}MB)을 넘었습니다.",
            413,
        )

    # #7500 리뷰 후속: the daily usage bucket is charged only after the request
    # carries a well-formed XLSX upload within the size caps — a malformed or
    # oversized request spends no quota, and the read below starts only once
    # the deduction succeeded.
    if usage_gate_enforced:
        decision = await usage_gate.authorize_conversion(user_id=user_id, grade=grade)
        if not decision.allowed:
            return _quota_denied(decision)

    sheets: list[dict] = []
    preview: dict | None = None
    try:
        for index in range(MAX_REVIEW_SHEETS):
            try:
                table = read_xlsx_table(
                    name=upload_name,
                    media_type=XLSX_MEDIA_TYPE,
                    payload=payload,
                    sheet_index=index,
                    max_rows=MAX_XLSX_ROWS,
                )
            except DocumentNormalizationError as exc:
                if exc.code == "xlsx_sheet_missing":
                    break
                if exc.code == "xlsx_no_headers":
                    # An empty (header-less) sheet is listed, not fatal: the
                    # review reports what each sheet holds (#7500 빈 시트).
                    sheets.append({"index": index, "title": None, "rows": 0,
                                   "columns": 0, "truncated": False, "empty": True})
                    continue
                raise
            sheets.append({
                "index": index,
                "title": table.sheet_title,
                "rows": table.total_rows_seen,
                "columns": len(table.headers),
                "truncated": table.truncated,
                "empty": False,
            })
            if preview is None:
                preview = {
                    "sheet_title": table.sheet_title,
                    "sheet_index": index,
                    "headers": list(table.headers),
                    "rows": [list(row) for row in table.rows[:PREVIEW_ROW_LIMIT]],
                    "truncated": table.truncated,
                }
    except DocumentNormalizationError as exc:
        return _refusal(exc)
    except Exception:
        return _error(
            "excel_review_unavailable",
            "지금 검토를 마칠 수 없습니다. 잠시 후 다시 시도해 주세요.",
            503,
        )

    if preview is None:
        # Every listed sheet is header-less: nothing readable in the workbook.
        return _refusal(DocumentNormalizationError("xlsx_empty", "no readable values"))

    empty_indices = [sheet["index"] for sheet in sheets if sheet["empty"]]
    truncated_titles = [sheet["title"] for sheet in sheets
                        if sheet["truncated"] and not sheet["empty"]]
    review = {
        "file_name": upload_name,
        "sheets": sheets,
        "sheet_list_truncated": sum(1 for sheet in sheets if not sheet["empty"]) >= MAX_REVIEW_SHEETS,
        "preview": preview,
        "summary": {
            "sheet_count": len(sheets),
            "readable_sheet_count": sum(1 for sheet in sheets if not sheet["empty"]),
            "empty_sheet_indices": empty_indices,
            "truncated_sheet_titles": truncated_titles,
            "total_data_rows": sum(sheet["rows"] for sheet in sheets),
            "row_bound": MAX_XLSX_ROWS,
            "review_note": goal or None,
        },
    }
    return JSONResponse({"ok": True, "review": review})
