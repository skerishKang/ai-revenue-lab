"""Private B67 case-folder PDF byte transfer (#4379).

The Engine -> Chat seam used to ship a whole PDF as Base64 characters inside a
JSON RPC result: a 4 MB file crossed as 5.4 MB of text and was decoded back to
bytes on the other side. This module replaces that round trip with one bounded
octet-stream frame on an internal fetch route:

    4-byte big-endian header length | UTF-8 JSON header | raw PDF bytes

The frame is the same convention Chat already accepts for a binary original in
``chat_routes._decode_completed_binary_attachment``, so no new transport
primitive is introduced. Metadata travels in the JSON header rather than in
HTTP headers because a Drive file name is not header-safe.

Authorization is unchanged: the caller names only a Chat-resolved workspace and
project plus a selection-intent file id, and the same selected-folder authority
re-resolves Drive metadata before a single byte is read. The route stays on the
existing Engine service binding and the existing caller identity.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Mapping
from typing import Any

from app.connector_bindings import DRIVE_REFERENCE_APP_ID
from app.drive_case_folder_binding import DriveCaseFolderBindingError
from app.drive_case_pdf_service import DriveCasePdfError, DriveCasePdfService
from app.service import _service_error

B67_CASE_PDF_BINARY_PATH = "/internal/v1/projects/drive-case-pdf/read"
B67_CASE_PDF_BINARY_CONTRACT_VERSION = "engine-b67-case-pdf-binary.v1"
B67_CASE_PDF_BINARY_CONTENT_TYPE = "application/octet-stream"

MAX_BINARY_PDF_HEADER_BYTES = 65536
MIN_BINARY_PDF_FRAME_BYTES = 6

_REQUEST_KEYS = frozenset({"app_id", "workspace_ref", "project_id", "file_id"})
_BINARY_HEADER_KEYS = frozenset(
    {
        "file",
        "byte_size",
        "sha256",
        "version_evidence",
        "authorization",
        "contract_version",
    }
)

PUBLIC_B67_CASE_PDF_BINARY_ROUTE_IS_BROWSER_REACHABLE = False


@dataclasses.dataclass(frozen=True)
class DriveCasePdfBinaryResponse:
    """Completed internal response: status, one body buffer and its type."""

    status_code: int
    body: bytes
    content_type: str


def _error(code: str, message: str, status_code: int) -> DriveCasePdfBinaryResponse:
    result = _service_error(code, message, status_code=status_code)
    return DriveCasePdfBinaryResponse(
        status_code=status_code,
        body=json.dumps(
            dict(result.body), ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8"),
        content_type="application/json; charset=utf-8",
    )


def encode_binary_pdf_frame(header: Mapping[str, Any], payload: bytes) -> bytes:
    """Frame one closed JSON header and the exact PDF bytes behind it."""

    encoded = json.dumps(
        dict(header), ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    if not encoded or len(encoded) > MAX_BINARY_PDF_HEADER_BYTES:
        raise ValueError("binary PDF frame header is out of bounds")
    if not payload:
        raise ValueError("binary PDF frame payload is empty")
    return len(encoded).to_bytes(4, "big") + encoded + payload


def decode_binary_pdf_frame(raw: bytes) -> tuple[dict[str, Any], bytes]:
    """Inverse of :func:`encode_binary_pdf_frame`; raises on any malformed frame."""

    if len(raw) < MIN_BINARY_PDF_FRAME_BYTES:
        raise ValueError("binary PDF frame is truncated")
    header_size = int.from_bytes(raw[:4], "big")
    if not 0 < header_size <= MAX_BINARY_PDF_HEADER_BYTES:
        raise ValueError("binary PDF frame header size is out of bounds")
    if len(raw) <= 4 + header_size:
        raise ValueError("binary PDF frame has no payload")
    header = json.loads(raw[4 : 4 + header_size].decode("utf-8"))
    if not isinstance(header, dict) or set(header) != _BINARY_HEADER_KEYS:
        raise ValueError("binary PDF frame header is not the closed contract")
    payload = raw[4 + header_size :]
    if not payload:
        raise ValueError("binary PDF frame payload is empty")
    return header, payload


def _bounded(value: object, *, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > limit:
        return None
    return normalized


def _parse_request(body: bytes) -> dict[str, str] | DriveCasePdfBinaryResponse:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error("invalid_request", "Request body must be a JSON object.", 400)
    if not isinstance(payload, Mapping):
        return _error("invalid_request", "Request body must be a JSON object.", 400)
    data = dict(payload)
    if set(data) != _REQUEST_KEYS:
        return _error("invalid_request", "Request fields do not match the contract.", 400)
    if data.get("app_id") != DRIVE_REFERENCE_APP_ID:
        return _error(
            "drive_case_folder_scope_denied",
            "Drive case PDF reader application is not authorized.",
            403,
        )
    workspace_ref = _bounded(data.get("workspace_ref"), limit=200)
    project_id = _bounded(data.get("project_id"), limit=200)
    file_id = _bounded(data.get("file_id"), limit=200)
    if workspace_ref is None or project_id is None or file_id is None:
        return _error("invalid_request", "Request scope fields are invalid.", 400)
    return {
        "workspace_ref": workspace_ref,
        "project_id": project_id,
        "file_id": file_id,
    }


async def drive_case_pdf_binary_read(
    service: DriveCasePdfService | None,
    *,
    body: bytes,
) -> DriveCasePdfBinaryResponse:
    """Serve one authorized case PDF as raw bytes, or a bounded JSON error."""

    if service is None:
        return _error(
            "drive_case_pdf_unavailable",
            "Drive case PDF acquisition is unavailable.",
            503,
        )

    request = _parse_request(body)
    if isinstance(request, DriveCasePdfBinaryResponse):
        return request

    try:
        read = await service.read_binary(
            workspace_ref=request["workspace_ref"],
            project_id=request["project_id"],
            file_id=request["file_id"],
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

    payload = read["payload"]
    header = {
        "file": read["file"],
        "byte_size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "version_evidence": read["version_evidence"],
        "authorization": read["authorization"],
        "contract_version": B67_CASE_PDF_BINARY_CONTRACT_VERSION,
    }
    try:
        frame = encode_binary_pdf_frame(header, payload)
    except ValueError:
        return _error(
            "drive_case_pdf_failed",
            "Drive case PDF operation failed.",
            500,
        )
    return DriveCasePdfBinaryResponse(
        status_code=200,
        body=frame,
        content_type=B67_CASE_PDF_BINARY_CONTENT_TYPE,
    )


def drive_case_pdf_binary_snapshot() -> dict[str, Any]:
    return {
        "path": B67_CASE_PDF_BINARY_PATH,
        "contract_version": B67_CASE_PDF_BINARY_CONTRACT_VERSION,
        "content_type": B67_CASE_PDF_BINARY_CONTENT_TYPE,
        "transport": "length-prefixed json header plus raw pdf bytes",
        "content_base64_in_response": False,
        "canonical_selected_folder_authority_reused": True,
        "canonical_drive_app_id_reused": True,
        "browser_reachable": PUBLIC_B67_CASE_PDF_BINARY_ROUTE_IS_BROWSER_REACHABLE,
        "production_mutation": False,
    }


__all__ = [
    "B67_CASE_PDF_BINARY_CONTRACT_VERSION",
    "B67_CASE_PDF_BINARY_CONTENT_TYPE",
    "B67_CASE_PDF_BINARY_PATH",
    "DriveCasePdfBinaryResponse",
    "MAX_BINARY_PDF_HEADER_BYTES",
    "MIN_BINARY_PDF_FRAME_BYTES",
    "PUBLIC_B67_CASE_PDF_BINARY_ROUTE_IS_BROWSER_REACHABLE",
    "decode_binary_pdf_frame",
    "drive_case_pdf_binary_read",
    "drive_case_pdf_binary_snapshot",
    "encode_binary_pdf_frame",
]
