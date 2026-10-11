"""Private Engine RPC seam for Project Drive case-folder selection (#3190).

The Engine Worker exposes these operations as **Service Binding RPC methods**,
never as a public ``fetch()`` route: a browser/public edge must not be able to
reach ``/internal/v1/projects/drive-case-folder/...``.

This module owns the operation -> internal-path mapping and the closed response
envelope so the seam stays testable without a Workers runtime:

    Chat Worker -> private Service Binding -> Default.<operation>(payload)
        -> drive_case_folder_rpc(service, operation=..., payload=...)
        -> DriveCaseFolderEngineService.handle(...)

The request schema is the service's own closed schema (workspace_ref /
project_id / query / folder_id only) and the response is the service's bounded
body; raw binding/workspace/actor refs, selected folder ids and credentials are
never returned.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from app.drive_case_folder_service import (
    CLEAR_PATH,
    FOLDERS_PATH,
    SELECT_PATH,
    STATUS_PATH,
    DriveCaseFolderEngineService,
)
from app.service import MAX_REQUEST_BODY_BYTES, ServiceResponse, _service_error

DRIVE_CASE_FOLDER_RPC_VERSION = "engine-drive-case-folder-rpc.v1"

OPERATION_PATHS = {
    "drive_case_folder_status": STATUS_PATH,
    "drive_case_folder_folders": FOLDERS_PATH,
    "drive_case_folder_select": SELECT_PATH,
    "drive_case_folder_clear": CLEAR_PATH,
}

DRIVE_CASE_FOLDER_RPC_OPERATIONS = tuple(OPERATION_PATHS)

PUBLIC_DRIVE_CASE_FOLDER_FETCH_ROUTE = False

# Top-level payload keys accepted per operation (closed).
_OPERATION_KEYS = {
    "drive_case_folder_status": frozenset({"workspace_ref", "project_id"}),
    "drive_case_folder_folders": frozenset({"workspace_ref", "project_id", "query"}),
    "drive_case_folder_select": frozenset({"workspace_ref", "project_id", "folder_id"}),
    "drive_case_folder_clear": frozenset({"workspace_ref", "project_id"}),
}


def _rpc_error(code: str, message: str, *, status_code: int = 400) -> dict[str, Any]:
    """Canonical Engine error envelope: exactly ``{ok, error}``.

    The inner error always carries ``{code, message, retryable, metadata}`` so
    every Drive case-folder RPC failure matches the service error contract.
    """

    return _service_error(code, message, status_code=status_code).body  # type: ignore[return-value]


async def drive_case_folder_rpc(
    service: DriveCaseFolderEngineService | None,
    *,
    operation: str,
    payload: object,
) -> dict[str, Any]:
    """Run one private RPC operation, returning the bounded response body.

    ``payload`` is validated twice: the operation keyset here, and the service's
    own closed schema. A missing service (absent composition) fails closed with
    a bounded 503 so a product can never read Drive state without authority.
    """

    if operation not in OPERATION_PATHS:
        return _rpc_error("not_found", "Unknown Engine RPC operation.", status_code=404)

    if service is None:
        return _rpc_error(
            "drive_case_folder_unavailable",
            "Drive case folder authority is unavailable.",
            status_code=503,
        )

    if not isinstance(payload, Mapping):
        return _rpc_error("invalid_request", "Request body must be an object.")

    body = dict(payload)
    unknown = set(body) - _OPERATION_KEYS[operation]
    if unknown:
        return _rpc_error("invalid_request", "Request contains unsupported fields.")

    encoded = json.dumps(body).encode("utf-8")
    if len(encoded) > MAX_REQUEST_BODY_BYTES:
        return _rpc_error(
            "request_too_large", "Request body exceeds the internal limit.", status_code=413
        )

    response: ServiceResponse = await service.handle(
        method="POST",
        path=OPERATION_PATHS[operation],
        content_type="application/json",
        body=encoded,
    )
    if not isinstance(response.body, dict):
        return _service_error(
            "drive_case_folder_failed", "Drive case folder operation failed.", status_code=500
        ).body  # type: ignore[return-value]
    return response.body


def drive_case_folder_rpc_snapshot() -> dict[str, Any]:
    """Deterministic, network-free snapshot of this seam's posture."""

    return {
        "rpc_version": DRIVE_CASE_FOLDER_RPC_VERSION,
        "operations": list(DRIVE_CASE_FOLDER_RPC_OPERATIONS),
        "public_fetch_route": PUBLIC_DRIVE_CASE_FOLDER_FETCH_ROUTE,
        "service_binding_only": True,
        "closed_request_schema": True,
        "returns_raw_refs": False,
        "live_provider_calls": 0,
    }


__all__ = [
    "DRIVE_CASE_FOLDER_RPC_VERSION",
    "OPERATION_PATHS",
    "DRIVE_CASE_FOLDER_RPC_OPERATIONS",
    "PUBLIC_DRIVE_CASE_FOLDER_FETCH_ROUTE",
    "drive_case_folder_rpc",
    "drive_case_folder_rpc_snapshot",
]
