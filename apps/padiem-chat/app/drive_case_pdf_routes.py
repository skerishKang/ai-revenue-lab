"""Project-scoped B67 Drive PDF intake routes (#3355).

The authority boundary is intentionally reused from #3190:

    auth_ready
    -> current_user_id
    -> owned project
    -> canonical session shadow
    -> Control Plane connector workspace
    -> existing P01 Engine Service Binding

No browser-provided workspace, Drive grant, provider endpoint, ancestry proof,
or OAuth authority is accepted here. file_id is selection intent only; the
Engine re-fetches Drive metadata and re-authorizes selected-folder scope before
returning bytes.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

from .drive_case_folder_engine import DriveCaseFolderEngineError
from .drive_case_folder_routes import _resolve_context

MAX_PDF_QUERY_CHARS = 200
MAX_PDF_FILE_ID_CHARS = 200

_ALLOWED_COLLECTION_QUERY_KEYS = frozenset({"query"})


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status_code)


def _invalid(code: str, message: str) -> JSONResponse:
    return _error(code, message, 400)


def _generic_failure() -> JSONResponse:
    return _error(
        "drive_case_pdf_failed",
        "Drive 사건 PDF 요청을 처리하지 못했습니다.",
        502,
    )


def _engine_error(exc: DriveCaseFolderEngineError) -> JSONResponse:
    status_code = int(exc.status_code or 502)
    if status_code not in (400, 401, 403, 404, 409, 413, 415, 422, 502, 503):
        status_code = 502
    return _error(exc.code, exc.safe_message, status_code)


async def drive_case_pdfs_collection(request: Request) -> JSONResponse:
    _uid, pid, workspace_ref, client, error = await _resolve_context(request)
    if error is not None:
        return error

    query_keys = set(request.query_params.keys())
    if query_keys - _ALLOWED_COLLECTION_QUERY_KEYS:
        return _invalid("invalid_request", "지원하지 않는 PDF 검색 매개변수가 포함되어 있습니다.")

    query = None
    if "query" in query_keys:
        candidate = request.query_params.get("query")
        if not isinstance(candidate, str):
            return _invalid("invalid_query", "PDF 검색어가 올바르지 않습니다.")
        candidate = candidate.strip()
        if not candidate or len(candidate) > MAX_PDF_QUERY_CHARS:
            return _invalid("invalid_query", "PDF 검색어가 올바르지 않습니다.")
        query = candidate

    try:
        body = await client.pdf_candidates(
            workspace_ref=workspace_ref,
            project_id=pid,
            query=query,
        )
    except DriveCaseFolderEngineError as exc:
        return _engine_error(exc)
    except Exception:
        return _generic_failure()

    return JSONResponse(
        {
            "files": body["files"],
            "more": body["more"],
            "direct_child_only": body["direct_child_only"],
        }
    )


async def drive_case_pdf_detail(request: Request) -> JSONResponse:
    _uid, pid, workspace_ref, client, error = await _resolve_context(request)
    if error is not None:
        return error

    if set(request.query_params.keys()):
        return _invalid("invalid_request", "PDF 읽기 요청에는 query 매개변수를 사용할 수 없습니다.")

    file_id = request.path_params.get("file_id")
    if not isinstance(file_id, str):
        return _invalid("invalid_file_id", "PDF 선택 값이 올바르지 않습니다.")
    file_id = file_id.strip()
    if not file_id or len(file_id) > MAX_PDF_FILE_ID_CHARS:
        return _invalid("invalid_file_id", "PDF 선택 값이 올바르지 않습니다.")

    try:
        body = await client.read_pdf(
            workspace_ref=workspace_ref,
            project_id=pid,
            file_id=file_id,
        )
    except DriveCaseFolderEngineError as exc:
        return _engine_error(exc)
    except Exception:
        return _generic_failure()

    return JSONResponse(body)


DRIVE_CASE_PDF_ROUTE_PATHS = {
    "candidates": "/api/projects/{project_id}/drive-case-pdfs",
    "read": "/api/projects/{project_id}/drive-case-pdfs/{file_id}",
}

BROWSER_WORKSPACE_REF_AUTHORITY = False
BROWSER_BINDING_REF_AUTHORITY = False
BROWSER_DRIVE_GRANT_AUTHORITY = False
BROWSER_PROVIDER_ENDPOINT_AUTHORITY = False
FILE_ID_IS_SELECTION_INTENT = True
SECOND_ENGINE_BINDING = False
PRODUCTION_MUTATION = False


__all__ = [
    "MAX_PDF_QUERY_CHARS",
    "MAX_PDF_FILE_ID_CHARS",
    "DRIVE_CASE_PDF_ROUTE_PATHS",
    "BROWSER_WORKSPACE_REF_AUTHORITY",
    "BROWSER_BINDING_REF_AUTHORITY",
    "BROWSER_DRIVE_GRANT_AUTHORITY",
    "BROWSER_PROVIDER_ENDPOINT_AUTHORITY",
    "FILE_ID_IS_SELECTION_INTENT",
    "SECOND_ENGINE_BINDING",
    "PRODUCTION_MUTATION",
    "drive_case_pdfs_collection",
    "drive_case_pdf_detail",
]
