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

DRIVE_CASE_FOLDER_OPERATIONS = (
    STATUS_OPERATION,
    FOLDERS_OPERATION,
    SELECT_OPERATION,
    CLEAR_OPERATION,
)

MAX_FOLDER_QUERY_CHARS = 200
MAX_CANDIDATE_FOLDERS = 25
MAX_CANDIDATE_NAME_CHARS = 160

_STATUS_KEYS = frozenset({"ok", "status", "contract_version"})
_STATUS_FIELDS = frozenset({"configured", "space_kind", "scope_token", "updated_at"})
_FOLDERS_KEYS = frozenset({"ok", "folders", "more", "exhaustive", "contract_version"})
_FOLDER_FIELDS = frozenset({"folder_id", "name", "space_kind", "modified_time"})
_SELECT_KEYS = frozenset({"ok", "outcome", "status", "contract_version"})
_SELECT_STATUS_FIELDS = frozenset({"configured", "space_kind", "updated_at"})
_CLEAR_KEYS = frozenset({"ok", "cleared"})

_SPACE_KINDS = frozenset({"my_drive", "shared_drive"})
_OUTCOMES = frozenset({"created", "idempotent", "replaced"})
_SELECT_OUTCOMES = _OUTCOMES

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

    # --- helpers ----------------------------------------------------------

    async def _call(self, operation: str, payload: dict[str, Any]) -> Mapping[str, Any]:
        try:
            result = await getattr(self._binding, operation)(payload)
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
        del operation
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
    "DRIVE_CASE_FOLDER_OPERATIONS",
    "MAX_FOLDER_QUERY_CHARS",
    "MAX_CANDIDATE_FOLDERS",
    "DriveCaseFolderEngineError",
    "CloudflareDriveCaseFolderEngineClient",
    "drive_case_folder_engine_seam_snapshot",
]
