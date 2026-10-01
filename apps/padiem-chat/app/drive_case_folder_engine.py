"""Chat -> Engine private client for Project Drive case-folder selection (#3190).

The browser never chooses an Engine origin or RPC method: this client calls the
fixed private Service Binding RPCs on the existing ``PADIEM_AI_ENGINE`` seam and
validates every response against an operation-specific closed schema. Malformed
Engine responses (extra/missing keys, wrong types, unknown status) become a
bounded 502; raw Engine error text never reaches a product response.

Binding activation is deliberately deferred: the composition root injects this
client only when the Service Binding exists, otherwise the routes fail closed
with 503.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping
from typing import Any

from .worker_config import P01_ENGINE_SERVICE_BINDING_NAME

DRIVE_CASE_FOLDER_ENGINE_SEAM_VERSION = "chat-drive-case-folder-engine.v1"

# The existing Chat -> Engine Service Binding is reused; this seam declares no
# second Engine binding name of its own.
PADIEM_AI_ENGINE_BINDING_NAME = P01_ENGINE_SERVICE_BINDING_NAME

STATUS_OPERATION = "drive_case_folder_status"
FOLDERS_OPERATION = "drive_case_folder_folders"
SELECT_OPERATION = "drive_case_folder_select"
CLEAR_OPERATION = "drive_case_folder_clear"
PDF_CANDIDATES_OPERATION = "b67_case_pdf_candidates"
PDF_READ_OPERATION = "b67_case_pdf_read"

DRIVE_CASE_FOLDER_OPERATIONS = (
    STATUS_OPERATION,
    FOLDERS_OPERATION,
    SELECT_OPERATION,
    CLEAR_OPERATION,
)
DRIVE_CASE_PDF_OPERATIONS = (PDF_CANDIDATES_OPERATION, PDF_READ_OPERATION)

MAX_FOLDER_QUERY_CHARS = 200
MAX_CANDIDATE_FOLDERS = 25
MAX_CANDIDATE_NAME_CHARS = 160
MAX_PDF_QUERY_CHARS = 200
MAX_PDF_FILE_ID_CHARS = 200
MAX_PDF_NAME_CHARS = 512
MAX_PDF_CANDIDATES = 25
MAX_PDF_BYTES = 4_000_000
MAX_PDF_BASE64_CHARS = ((MAX_PDF_BYTES + 2) // 3) * 4

_STATUS_KEYS = frozenset({"ok", "status", "contract_version"})
_STATUS_FIELDS = frozenset({"configured", "space_kind", "scope_token", "updated_at"})
_FOLDERS_KEYS = frozenset({"ok", "folders", "more", "exhaustive", "contract_version"})
_FOLDER_FIELDS = frozenset({"folder_id", "name", "space_kind", "modified_time"})
_SELECT_KEYS = frozenset({"ok", "outcome", "status", "contract_version"})
_SELECT_STATUS_FIELDS = frozenset({"configured", "space_kind", "updated_at"})
_CLEAR_KEYS = frozenset({"ok", "cleared"})
_PDF_CANDIDATES_KEYS = frozenset({"ok", "files", "more", "direct_child_only", "contract_version"})
_PDF_READ_KEYS = frozenset({"ok", "file", "content_base64", "byte_size", "version_evidence", "authorization", "contract_version"})
_PDF_FILE_FIELDS = frozenset({"file_id", "name", "mime_type", "size_bytes", "modified_time", "space_kind", "intake_state"})
_PDF_VERSION_FIELDS = frozenset({"version", "modified_time", "md5_checksum", "sha256_checksum", "head_revision_id"})
_PDF_AUTHORIZATION_FIELDS = frozenset({"direct_parent_proof", "source_type"})

_SPACE_KINDS = frozenset({"my_drive", "shared_drive"})
_OUTCOMES = frozenset({"created", "idempotent", "replaced"})
_SELECT_OUTCOMES = _OUTCOMES
_PDF_INTAKE_STATES = frozenset({"size_unverified", "execution_fallback_required", "browser_pdf_ready"})

# Engine error code -> bounded Chat failure.
_ERROR_TAXONOMY: dict[str, tuple[int, str]] = {
    "drive_not_connected": (409, "Google Drive is not connected for this workspace."),
    "drive_case_folder_unavailable": (503, "Drive case folder authority is unavailable."),
    "binding_authority_unavailable": (503, "Selected-folder authority is unavailable."),
    "drive_authority_unavailable": (503, "Drive authority is unavailable."),
    "drive_port_unavailable": (503, "Drive read authority is unavailable."),
    "drive_workspace_mismatch": (403, "Drive authority rejected the workspace."),
    "drive_connector_mismatch": (403, "Drive authority rejected the connector."),
    "noncanonical_drive_grant": (403, "Drive authority rejected the grant."),
    "no_binding": (404, "No selected Drive case folder is configured."),
    "binding_store_unavailable": (503, "Selected-folder storage is unavailable."),
    "folder_not_selectable": (422, "The selected Drive resource cannot be used."),
    "non_folder_selection": (422, "The selected Drive resource is not a folder."),
    "shortcut_selection": (422, "A Drive shortcut cannot be selected."),
    "folder_lookup_failed": (422, "Drive folder could not be verified."),
    "drive_binding_drift": (409, "The selected folder belongs to a different Drive connection."),
    "drive_case_pdf_unavailable": (503, "Drive case PDF acquisition is unavailable."),
    "drive_provider_unavailable": (502, "Drive provider read is unavailable."),
    "drive_provider_contract_failed": (502, "Drive provider metadata is invalid."),
    "drive_parent_contract_failed": (502, "Drive parent verification failed."),
    "drive_case_folder_scope_denied": (403, "Drive resource is outside the selected case folder."),
    "invalid_query": (400, "PDF search query is invalid."),
    "invalid_file_id": (400, "PDF selection is invalid."),
    "not_pdf": (415, "Selected Drive resource is not an eligible PDF."),
    "pdf_size_unverifiable": (422, "Selected PDF size could not be verified."),
    "execution_fallback_required": (413, "Selected PDF requires bounded execution fallback."),
    "pdf_integrity_mismatch": (502, "Selected PDF bytes failed integrity verification."),
    "pdf_signature_mismatch": (415, "Selected Drive content is not a PDF payload."),
}
_DEFAULT_ERROR = (502, "Drive case folder operation failed.")


class DriveCaseFolderEngineError(ValueError):
    """Bounded Chat-side failure for the private Engine seam."""

    def __init__(self, code: str, safe_message: str, *, status_code: int = 502) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.status_code = status_code


def _bounded_text(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or len(cleaned) > limit:
        return None
    return cleaned


def _optional_text(value: object, limit: int) -> str | None:
    if value is None:
        return None
    return _bounded_text(value, limit)


class CloudflareDriveCaseFolderEngineClient:
    """Private Service Binding client; one closed validation per operation."""

    def __init__(self, binding: object | None = None) -> None:
        if binding is None or any(
            not callable(getattr(binding, operation, None))
            for operation in DRIVE_CASE_FOLDER_OPERATIONS
        ):
            raise ValueError("engine binding must expose every drive case-folder RPC")
        self._binding = binding

    def __repr__(self) -> str:
        return "CloudflareDriveCaseFolderEngineClient(configured)"

    # --- operations -------------------------------------------------------

    async def status(self, *, workspace_ref: str, project_id: str) -> dict[str, Any]:
        payload = {"workspace_ref": workspace_ref, "project_id": project_id}
        result = await self._call(STATUS_OPERATION, payload)
        self._require_exact_keys(result, _STATUS_KEYS, STATUS_OPERATION)
        return self._status_body(result, _STATUS_FIELDS)

    async def folders(
        self, *, workspace_ref: str, project_id: str, query: object = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"workspace_ref": workspace_ref, "project_id": project_id}
        if query is not None:
            bounded = _bounded_text(query, MAX_FOLDER_QUERY_CHARS)
            if bounded is None:
                raise DriveCaseFolderEngineError(
                    "invalid_query", "Folder search query is invalid.", status_code=400
                )
            payload["query"] = bounded
        result = await self._call(FOLDERS_OPERATION, payload)
        self._require_exact_keys(result, _FOLDERS_KEYS, FOLDERS_OPERATION)
        raw_folders = result.get("folders")
        if not isinstance(raw_folders, list) or len(raw_folders) > MAX_CANDIDATE_FOLDERS:
            raise self._malformed(FOLDERS_OPERATION)
        folders: list[dict[str, Any]] = []
        for item in raw_folders:
            if not isinstance(item, Mapping) or set(item) != _FOLDER_FIELDS:
                raise self._malformed(FOLDERS_OPERATION)
            folder_id = _bounded_text(item.get("folder_id"), MAX_CANDIDATE_NAME_CHARS)
            name = _bounded_text(item.get("name"), MAX_CANDIDATE_NAME_CHARS)
            space_kind = item.get("space_kind")
            if folder_id is None or name is None or space_kind not in _SPACE_KINDS:
                raise self._malformed(FOLDERS_OPERATION)
            folders.append(
                {
                    "folder_id": folder_id,
                    "name": name,
                    "space_kind": space_kind,
                    "modified_time": _optional_text(item.get("modified_time"), 64),
                }
            )
        if not isinstance(result.get("more"), bool) or not isinstance(result.get("exhaustive"), bool):
            raise self._malformed(FOLDERS_OPERATION)
        return {"folders": folders, "more": result["more"], "exhaustive": result["exhaustive"]}

    async def select(self, *, workspace_ref: str, project_id: str, folder_id: object) -> dict[str, Any]:
        bounded = _bounded_text(folder_id, MAX_CANDIDATE_NAME_CHARS)
        if bounded is None:
            raise DriveCaseFolderEngineError(
                "invalid_folder_id", "Folder selection is invalid.", status_code=400
            )
        result = await self._call(
            SELECT_OPERATION,
            {"workspace_ref": workspace_ref, "project_id": project_id, "folder_id": bounded},
        )
        self._require_exact_keys(result, _SELECT_KEYS, SELECT_OPERATION)
        if result.get("outcome") not in _SELECT_OUTCOMES:
            raise self._malformed(SELECT_OPERATION)
        return self._status_body(result, _SELECT_STATUS_FIELDS)

    async def clear(self, *, workspace_ref: str, project_id: str) -> dict[str, Any]:
        result = await self._call(
            CLEAR_OPERATION, {"workspace_ref": workspace_ref, "project_id": project_id}
        )
        self._require_exact_keys(result, _CLEAR_KEYS, CLEAR_OPERATION)
        if not isinstance(result.get("cleared"), bool):
            raise self._malformed(CLEAR_OPERATION)
        return {"cleared": result["cleared"]}

    async def pdf_candidates(
        self, *, workspace_ref: str, project_id: str, query: object = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"workspace_ref": workspace_ref, "project_id": project_id}
        if query is not None:
            bounded = _bounded_text(query, MAX_PDF_QUERY_CHARS)
            if bounded is None:
                raise DriveCaseFolderEngineError(
                    "invalid_query", "PDF search query is invalid.", status_code=400
                )
            payload["query"] = bounded
        result = await self._call(PDF_CANDIDATES_OPERATION, payload)
        self._require_exact_keys(result, _PDF_CANDIDATES_KEYS, PDF_CANDIDATES_OPERATION)
        raw_files = result.get("files")
        if not isinstance(raw_files, list) or len(raw_files) > MAX_PDF_CANDIDATES:
            raise self._malformed(PDF_CANDIDATES_OPERATION)
        files = [self._pdf_file_body(item, PDF_CANDIDATES_OPERATION) for item in raw_files]
        if not isinstance(result.get("more"), bool) or result.get("direct_child_only") is not True:
            raise self._malformed(PDF_CANDIDATES_OPERATION)
        if _bounded_text(result.get("contract_version"), 128) is None:
            raise self._malformed(PDF_CANDIDATES_OPERATION)
        return {"files": files, "more": result["more"], "direct_child_only": True}

    async def read_pdf(
        self, *, workspace_ref: str, project_id: str, file_id: object
    ) -> dict[str, Any]:
        bounded_file_id = _bounded_text(file_id, MAX_PDF_FILE_ID_CHARS)
        if bounded_file_id is None:
            raise DriveCaseFolderEngineError(
                "invalid_file_id", "PDF selection is invalid.", status_code=400
            )
        result = await self._call(
            PDF_READ_OPERATION,
            {"workspace_ref": workspace_ref, "project_id": project_id, "file_id": bounded_file_id},
        )
        self._require_exact_keys(result, _PDF_READ_KEYS, PDF_READ_OPERATION)
        file_body = self._pdf_file_body(result.get("file"), PDF_READ_OPERATION)
        if file_body["intake_state"] != "browser_pdf_ready":
            raise self._malformed(PDF_READ_OPERATION)

        byte_size = result.get("byte_size")
        encoded = result.get("content_base64")
        if (
            isinstance(byte_size, bool)
            or not isinstance(byte_size, int)
            or byte_size < 1
            or byte_size > MAX_PDF_BYTES
            or not isinstance(encoded, str)
            or not encoded
            or len(encoded) > MAX_PDF_BASE64_CHARS
        ):
            raise self._malformed(PDF_READ_OPERATION)
        try:
            payload = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise self._malformed(PDF_READ_OPERATION) from None
        if len(payload) != byte_size or not payload.startswith(b"%PDF-"):
            raise self._malformed(PDF_READ_OPERATION)

        version = result.get("version_evidence")
        if not isinstance(version, Mapping) or set(version) != _PDF_VERSION_FIELDS:
            raise self._malformed(PDF_READ_OPERATION)
        version_body: dict[str, str | None] = {}
        for key in _PDF_VERSION_FIELDS:
            value = version.get(key)
            if value is not None and _bounded_text(value, 512) is None:
                raise self._malformed(PDF_READ_OPERATION)
            version_body[key] = value

        authorization = result.get("authorization")
        if (
            not isinstance(authorization, Mapping)
            or set(authorization) != _PDF_AUTHORIZATION_FIELDS
            or authorization.get("direct_parent_proof") is not True
            or authorization.get("source_type") != "drive"
        ):
            raise self._malformed(PDF_READ_OPERATION)
        if _bounded_text(result.get("contract_version"), 128) is None:
            raise self._malformed(PDF_READ_OPERATION)

        return {
            "file": file_body,
            "content_base64": encoded,
            "byte_size": byte_size,
            "version_evidence": version_body,
            "authorization": {"direct_parent_proof": True, "source_type": "drive"},
        }

    @staticmethod
    def _pdf_file_body(value: object, operation: str) -> dict[str, Any]:
        if not isinstance(value, Mapping) or set(value) != _PDF_FILE_FIELDS:
            raise CloudflareDriveCaseFolderEngineClient._malformed(operation)
        file_id = _bounded_text(value.get("file_id"), MAX_PDF_FILE_ID_CHARS)
        name = _bounded_text(value.get("name"), MAX_PDF_NAME_CHARS)
        mime_type = value.get("mime_type")
        size_bytes = value.get("size_bytes")
        modified_time = value.get("modified_time")
        space_kind = value.get("space_kind")
        intake_state = value.get("intake_state")
        if file_id is None or name is None or mime_type != "application/pdf":
            raise CloudflareDriveCaseFolderEngineClient._malformed(operation)
        if isinstance(size_bytes, bool) or (
            size_bytes is not None and (not isinstance(size_bytes, int) or size_bytes < 0)
        ):
            raise CloudflareDriveCaseFolderEngineClient._malformed(operation)
        if modified_time is not None and _bounded_text(modified_time, 128) is None:
            raise CloudflareDriveCaseFolderEngineClient._malformed(operation)
        if space_kind not in _SPACE_KINDS or intake_state not in _PDF_INTAKE_STATES:
            raise CloudflareDriveCaseFolderEngineClient._malformed(operation)
        if intake_state in {"browser_pdf_ready", "execution_fallback_required"}:
            if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or size_bytes < 1:
                raise CloudflareDriveCaseFolderEngineClient._malformed(operation)
        return {
            "file_id": file_id,
            "name": name,
            "mime_type": "application/pdf",
            "size_bytes": size_bytes,
            "modified_time": modified_time,
            "space_kind": space_kind,
            "intake_state": intake_state,
        }

    # --- helpers ----------------------------------------------------------

    async def _call(self, operation: str, payload: dict[str, Any]) -> Mapping[str, Any]:
        method = getattr(self._binding, operation, None)
        if not callable(method):
            if operation in DRIVE_CASE_PDF_OPERATIONS:
                raise DriveCaseFolderEngineError(
                    "drive_case_pdf_unavailable",
                    "Drive case PDF acquisition is unavailable.",
                    status_code=503,
                )
            raise DriveCaseFolderEngineError(
                "drive_case_folder_engine_failed",
                "Drive case folder service is unavailable.",
                status_code=502,
            )
        try:
            result = await method(payload)
        except DriveCaseFolderEngineError:
            raise
        except Exception:
            raise DriveCaseFolderEngineError(
                "drive_case_folder_engine_failed",
                "Drive case folder service is unavailable.",
                status_code=502,
            ) from None
        if not isinstance(result, Mapping):
            raise self._malformed(operation)
        if result.get("ok") is False:
            code, _engine_message = self._validated_error(result, operation)
            if code not in _ERROR_TAXONOMY:
                # An arbitrary upstream code is never propagated to a product.
                raise DriveCaseFolderEngineError(
                    "drive_case_folder_failed", _DEFAULT_ERROR[1], status_code=502
                )
            status_code, message = _ERROR_TAXONOMY[code]
            raise DriveCaseFolderEngineError(code, message, status_code=status_code)
        if result.get("ok") is not True:
            raise self._malformed(operation)
        return result

    @staticmethod
    def _validated_error(result: Mapping[str, Any], operation: str) -> tuple[str, str]:
        """Validate the canonical Engine error envelope exactly.

        The Engine message is type-checked only and never used as a product
        message (D): Chat always answers with its own static taxonomy text.
        """

        malformed = CloudflareDriveCaseFolderEngineClient._malformed(operation)
        if set(result) != {"ok", "error"}:
            raise malformed
        error = result.get("error")
        if not isinstance(error, Mapping) or set(error) != {"code", "message", "retryable", "metadata"}:
            raise malformed
        code = error.get("code")
        message = error.get("message")
        if not isinstance(code, str) or not code.strip() or len(code) > 64:
            raise malformed
        if not isinstance(message, str) or not message.strip():
            raise malformed
        if not isinstance(error.get("retryable"), bool):
            raise malformed
        if error.get("metadata") is not None:
            raise malformed
        return code.strip(), message

    @staticmethod
    def _require_exact_keys(result: Mapping[str, Any], keys: frozenset[str], operation: str) -> None:
        if set(result) != keys:
            raise CloudflareDriveCaseFolderEngineClient._malformed(operation)

    @staticmethod
    def _malformed(operation: str) -> DriveCaseFolderEngineError:
        if operation in DRIVE_CASE_PDF_OPERATIONS:
            return DriveCaseFolderEngineError(
                "drive_case_pdf_response_invalid",
                "Drive case PDF service returned an invalid response.",
                status_code=502,
            )
        return DriveCaseFolderEngineError(
            "drive_case_folder_response_invalid",
            "Drive case folder service returned an invalid response.",
            status_code=502,
        )

    @staticmethod
    def _status_body(result: Mapping[str, Any], fields: frozenset[str]) -> dict[str, Any]:
        status = result.get("status")
        if not isinstance(status, Mapping) or set(status) != fields:
            raise CloudflareDriveCaseFolderEngineClient._malformed("status")
        configured = status.get("configured")
        if not isinstance(configured, bool):
            raise CloudflareDriveCaseFolderEngineClient._malformed("status")
        space_kind = status.get("space_kind")
        if space_kind is not None and space_kind not in _SPACE_KINDS:
            raise CloudflareDriveCaseFolderEngineClient._malformed("status")
        body = {
            "configured": configured,
            "space_kind": space_kind,
            "updated_at": _optional_text(status.get("updated_at"), 64),
        }
        if "scope_token" in fields:
            body["scope_token"] = _optional_text(status.get("scope_token"), 64)
        return body


def drive_case_folder_engine_seam_snapshot() -> dict[str, Any]:
    """Deterministic, network-free snapshot of this seam's posture."""

    return {
        "seam_version": DRIVE_CASE_FOLDER_ENGINE_SEAM_VERSION,
        "binding_name": PADIEM_AI_ENGINE_BINDING_NAME,
        "operations": list(DRIVE_CASE_FOLDER_OPERATIONS),
        "pdf_operations": list(DRIVE_CASE_PDF_OPERATIONS),
        "browser_selects_endpoint": False,
        "response_schema_closed": True,
        "raw_engine_error_text": False,
        "production_binding_activated": False,
        "live_provider_calls": 0,
    }


__all__ = [
    "DRIVE_CASE_FOLDER_ENGINE_SEAM_VERSION",
    "PADIEM_AI_ENGINE_BINDING_NAME",
    "STATUS_OPERATION",
    "FOLDERS_OPERATION",
    "SELECT_OPERATION",
    "CLEAR_OPERATION",
    "PDF_CANDIDATES_OPERATION",
    "PDF_READ_OPERATION",
    "DRIVE_CASE_FOLDER_OPERATIONS",
    "DRIVE_CASE_PDF_OPERATIONS",
    "MAX_FOLDER_QUERY_CHARS",
    "MAX_CANDIDATE_FOLDERS",
    "DriveCaseFolderEngineError",
    "CloudflareDriveCaseFolderEngineClient",
    "drive_case_folder_engine_seam_snapshot",
]
