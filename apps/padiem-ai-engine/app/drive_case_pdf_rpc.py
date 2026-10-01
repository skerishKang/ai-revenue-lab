"""Private Service Binding RPC for B67 case-folder PDF acquisition (#3350).

No public fetch route is created. The browser/product may supply only project
scope already resolved by Chat plus search/file selection intent; Drive/OAuth
authority stays server-side.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.drive_case_folder_binding import DriveCaseFolderBindingError
from app.drive_case_pdf_service import DriveCasePdfError, DriveCasePdfService
from app.service import _service_error

B67_CASE_PDF_RPC_VERSION = "engine-b67-case-pdf-rpc.v1"

CANDIDATES_OPERATION = "b67_case_pdf_candidates"
READ_OPERATION = "b67_case_pdf_read"
B67_CASE_PDF_RPC_OPERATIONS = (CANDIDATES_OPERATION, READ_OPERATION)

_OPERATION_KEYS = {
    CANDIDATES_OPERATION: frozenset({"workspace_ref", "project_id", "query"}),
    READ_OPERATION: frozenset({"workspace_ref", "project_id", "file_id"}),
}
_REQUIRED_KEYS = {
    CANDIDATES_OPERATION: frozenset({"workspace_ref", "project_id"}),
    READ_OPERATION: frozenset({"workspace_ref", "project_id", "file_id"}),
}

PUBLIC_B67_CASE_PDF_FETCH_ROUTE = False


def _error(code: str, message: str, status_code: int) -> dict[str, Any]:
    return dict(_service_error(code, message, status_code=status_code).body)


async def drive_case_pdf_rpc(
    service: DriveCasePdfService | None,
    *,
    operation: str,
    payload: object,
) -> dict[str, Any]:
    if operation not in B67_CASE_PDF_RPC_OPERATIONS:
        return _error("not_found", "Unknown B67 PDF operation.", 404)
    if service is None:
        return _error(
            "drive_case_pdf_unavailable",
            "Drive case PDF acquisition is unavailable.",
            503,
        )
    if not isinstance(payload, Mapping):
        return _error("invalid_request", "Request body must be an object.", 400)

    body = dict(payload)
    if set(body) - _OPERATION_KEYS[operation]:
        return _error("invalid_request", "Request contains unsupported fields.", 400)
    if _REQUIRED_KEYS[operation] - set(body):
        return _error("invalid_request", "Request is missing required fields.", 400)

    workspace_ref = body.get("workspace_ref")
    project_id = body.get("project_id")
    if not isinstance(workspace_ref, str) or not isinstance(project_id, str):
        return _error("invalid_request", "Request scope fields are invalid.", 400)

    try:
        if operation == CANDIDATES_OPERATION:
            query = body.get("query")
            if query is not None and not isinstance(query, str):
                return _error("invalid_request", "PDF search query is invalid.", 400)
            return await service.candidates(
                workspace_ref=workspace_ref,
                project_id=project_id,
                query=query,
            )
        return await service.read(
            workspace_ref=workspace_ref,
            project_id=project_id,
            file_id=body.get("file_id"),
        )
    except DriveCasePdfError as exc:
        return _error(exc.code, exc.safe_message, exc.status_code)
    except DriveCaseFolderBindingError as exc:
        return _error(exc.code, exc.safe_message, exc.status_code)
    except Exception:
        return _error(
            "drive_case_pdf_failed",
            "Drive case PDF operation failed.",
            500,
        )


def drive_case_pdf_rpc_snapshot() -> dict[str, Any]:
    return {
        "rpc_version": B67_CASE_PDF_RPC_VERSION,
        "operations": list(B67_CASE_PDF_RPC_OPERATIONS),
        "service_binding_only": True,
        "public_fetch_route": PUBLIC_B67_CASE_PDF_FETCH_ROUTE,
        "closed_request_schema": True,
        "browser_drive_authority": False,
        "raw_credentials_present": False,
    }


__all__ = [
    "B67_CASE_PDF_RPC_VERSION",
    "CANDIDATES_OPERATION",
    "READ_OPERATION",
    "B67_CASE_PDF_RPC_OPERATIONS",
    "PUBLIC_B67_CASE_PDF_FETCH_ROUTE",
    "drive_case_pdf_rpc",
    "drive_case_pdf_rpc_snapshot",
]
