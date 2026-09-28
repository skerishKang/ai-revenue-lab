"""Private Engine service for authenticated Project Drive case-folder selection.

#3190 source slice. Server-side authority only: the browser/Product never sends
a grant, binding, workspace or scope, and a folder id is treated as *selection
intent* that must be re-authorized against the live Drive connection before it
can be persisted.

Operations (fixed internal paths, one operation each, following the existing
Engine service convention):

* ``status``   - bounded, product-safe selected-folder status for a project;
* ``folders``  - bounded recent/search folder *candidates* (selection intent);
* ``select``   - re-fetch canonical Drive metadata for the intent folder id and
  persist/replace the #3188 selected-folder authority;
* ``clear``    - deactivate the project's selected folder.

Every operation resolves the **current** canonical Drive grant server-side and
fails closed when any dependency is missing. No second Drive client, tool
runtime, OAuth authority or database binding is created here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
import json
from typing import Any, Protocol

from padiem_ai_core.drive_capability import (
    DRIVE_GET_FILE_METADATA_TOOL_ID,
    DRIVE_LIST_RECENT_FILES_TOOL_ID,
    DRIVE_SEARCH_FILES_TOOL_ID,
    DriveContractError,
    build_drive_read_handlers,
)
from padiem_ai_core.drive_case_folder_scope import GOOGLE_FOLDER_MIME, DriveCaseResource
from padiem_ai_core.tool_runtime import ToolHandlerError

from app.connector_bindings import DriveGrant
from app.drive_case_folder_binding import (
    DriveCaseFolderBindingAuthority,
    DriveCaseFolderBindingError,
)
from app.service import MAX_REQUEST_BODY_BYTES, ServiceResponse, _service_error

DRIVE_CASE_FOLDER_SERVICE_VERSION = "engine-drive-case-folder-service.v1"

STATUS_PATH = "/internal/v1/projects/drive-case-folder/status"
FOLDERS_PATH = "/internal/v1/projects/drive-case-folder/folders"
SELECT_PATH = "/internal/v1/projects/drive-case-folder/select"
CLEAR_PATH = "/internal/v1/projects/drive-case-folder/clear"

DRIVE_CASE_FOLDER_PATHS = (STATUS_PATH, FOLDERS_PATH, SELECT_PATH, CLEAR_PATH)

# Closed request schema: operation intent only.
_STATUS_FIELDS = frozenset({"workspace_ref", "project_id"})
_FOLDERS_FIELDS = frozenset({"workspace_ref", "project_id", "query"})
_SELECT_FIELDS = frozenset({"workspace_ref", "project_id", "folder_id"})
_CLEAR_FIELDS = frozenset({"workspace_ref", "project_id"})

# Candidate list bounds: recent/search never follow every Drive page.
MAX_CANDIDATE_FOLDERS = 25
MAX_CANDIDATE_NAME_CHARS = 160
MAX_FOLDER_QUERY_CHARS = 200

_UNSAFE_AUTHORITY_FIELDS = frozenset(
    {
        "binding_ref",
        "actor_ref",
        "drive_grant",
        "grant",
        "app_id",
        "agent_id",
        "canonical_agent_id",
        "scope",
        "drive_case_folder_scope",
        "granted_capabilities",
        "workspace_grant",
        "tenant_id",
        "subject_id",
    }
)


class DriveCaseFolderGrantProvider(Protocol):
    """Resolves the current canonical Drive grant server-side."""

    async def current_drive_grant(self) -> DriveGrant | None: ...


class DriveCaseFolderEngineError(ValueError):
    """Fail-closed Engine service error safe for first-party products."""

    def __init__(self, code: str, safe_message: str, *, status_code: int = 400) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.status_code = status_code


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _bounded_text(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or len(cleaned) > limit:
        return None
    return cleaned


class DriveCaseFolderEngineService:
    """Composition seam: Engine authorities behind one closed request contract."""

    def __init__(
        self,
        *,
        grant_provider: DriveCaseFolderGrantProvider | None = None,
        drive_port: object | None = None,
        binding_authority: DriveCaseFolderBindingAuthority | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._grant_provider = grant_provider
        self._drive_port = drive_port
        self._binding_authority = binding_authority
        self._clock = clock if clock is not None else _utcnow

    def __repr__(self) -> str:
        return "DriveCaseFolderEngineService(configured)"

    # --- request handling -------------------------------------------------

    async def handle(
        self,
        *,
        method: str,
        path: str,
        content_type: str | None = None,
        body: bytes = b"",
    ) -> ServiceResponse:
        if path not in DRIVE_CASE_FOLDER_PATHS:
            return _service_error("not_found", "Internal Engine route not found.", status_code=404)
        if (method or "").upper() != "POST":
            return _service_error("method_not_allowed", "Method not allowed.", status_code=405)
        if (
            not isinstance(content_type, str)
            or content_type.split(";", 1)[0].strip().lower() != "application/json"
        ):
            return _service_error(
                "unsupported_media_type", "Content-Type must be application/json.", status_code=415
            )
        if not isinstance(body, (bytes, bytearray, memoryview)):
            return _service_error("invalid_request", "Request body is invalid.", status_code=400)
        raw = bytes(body)
        if len(raw) > MAX_REQUEST_BODY_BYTES:
            return _service_error(
                "request_too_large", "Request body exceeds the internal limit.", status_code=413
            )
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _service_error(
                "invalid_json", "Request body must contain valid UTF-8 JSON.", status_code=400
            )
        if not isinstance(payload, Mapping):
            return _service_error("invalid_request", "Request body must be an object.", status_code=400)

        try:
            return await self._dispatch(path, dict(payload))
        except DriveCaseFolderEngineError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except DriveCaseFolderBindingError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)
        except DriveContractError:
            return _service_error(
                "drive_provider_contract_failed",
                "Drive provider metadata did not match the reviewed contract.",
                status_code=502,
            )
        except Exception:
            return _service_error(
                "drive_case_folder_failed", "Drive case folder operation failed.", status_code=500
            )

    async def _dispatch(self, path: str, payload: dict[str, Any]) -> ServiceResponse:
        if path == STATUS_PATH:
            workspace_ref, project_id = self._scope_fields(payload, _STATUS_FIELDS)
            grant = await self._current_grant()
            authority = self._require_authority()
            status = await authority.status(
                workspace_ref=workspace_ref, project_id=project_id, drive_grant=grant
            )
            return ServiceResponse(
                status_code=200, body={"ok": True, "status": status, "contract_version": DRIVE_CASE_FOLDER_SERVICE_VERSION}
            )

        if path == FOLDERS_PATH:
            workspace_ref, project_id = self._scope_fields(payload, _FOLDERS_FIELDS, required=("workspace_ref", "project_id"))
            query = payload.get("query")
            if query is not None and _bounded_text(query, MAX_FOLDER_QUERY_CHARS) is None:
                raise DriveCaseFolderEngineError("invalid_query", "Folder search query is invalid.")
            grant = await self._current_grant()
            candidates = await self._folder_candidates(grant, query=query)
            return ServiceResponse(
                status_code=200,
                body={
                    "ok": True,
                    "folders": candidates["folders"],
                    "more": candidates["more"],
                    "exhaustive": False,
                    "contract_version": DRIVE_CASE_FOLDER_SERVICE_VERSION,
                },
            )

        if path == SELECT_PATH:
            workspace_ref, project_id = self._scope_fields(payload, _SELECT_FIELDS, required=("workspace_ref", "project_id", "folder_id"))
            folder_id = _bounded_text(payload.get("folder_id"), 200)
            if folder_id is None:
                raise DriveCaseFolderEngineError("invalid_folder_id", "Folder selection intent is invalid.")
            grant = await self._current_grant()
            resource = await self._authorized_folder_resource(grant, folder_id)
            authority = self._require_authority()
            binding, outcome = await authority.bind_selected_folder(
                workspace_ref=workspace_ref,
                project_id=project_id,
                drive_grant=grant,
                selected_resource=resource,
            )
            return ServiceResponse(
                status_code=200,
                body={
                    "ok": True,
                    "outcome": outcome,
                    "status": {
                        "configured": True,
                        "space_kind": binding.space_kind,
                        "updated_at": binding.updated_at.isoformat(),
                    },
                    "contract_version": DRIVE_CASE_FOLDER_SERVICE_VERSION,
                },
            )

        workspace_ref, project_id = self._scope_fields(payload, _CLEAR_FIELDS)
        grant = await self._current_grant()
        authority = self._require_authority()
        cleared = await authority.clear(
            workspace_ref=workspace_ref, project_id=project_id, drive_grant=grant
        )
        return ServiceResponse(status_code=200, body={"ok": True, "cleared": bool(cleared)})

    # --- authority helpers ------------------------------------------------

    def _scope_fields(
        self, payload: Mapping[str, Any], allowed: frozenset[str], *, required: tuple[str, ...] = ("workspace_ref", "project_id")
    ) -> tuple[str, str]:
        unknown = set(payload) - allowed
        if unknown:
            raise DriveCaseFolderEngineError(
                "invalid_request", "Request contains unsupported fields.", status_code=400
            )
        if set(required) - set(payload):
            raise DriveCaseFolderEngineError(
                "invalid_request", "Request is missing required fields.", status_code=400
            )
        workspace_ref = _bounded_text(payload.get("workspace_ref"), 200)
        project_id = _bounded_text(payload.get("project_id"), 200)
        if workspace_ref is None or project_id is None:
            raise DriveCaseFolderEngineError("invalid_request", "Request fields are invalid.", status_code=400)
        return workspace_ref, project_id

    async def _current_grant(self) -> DriveGrant:
        if self._grant_provider is None:
            raise DriveCaseFolderEngineError(
                "drive_authority_unavailable", "Drive authority is unavailable.", status_code=503
            )
        grant = await self._grant_provider.current_drive_grant()
        if not isinstance(grant, DriveGrant):
            raise DriveCaseFolderEngineError(
                "drive_not_connected", "No canonical Drive grant is available for this workspace.", status_code=409
            )
        return grant

    def _require_authority(self) -> DriveCaseFolderBindingAuthority:
        if self._binding_authority is None:
            raise DriveCaseFolderEngineError(
                "binding_authority_unavailable", "Selected-folder authority is unavailable.", status_code=503
            )
        return self._binding_authority

    def _handlers(self, grant: DriveGrant) -> dict[str, Any]:
        if self._drive_port is None:
            raise DriveCaseFolderEngineError(
                "drive_port_unavailable", "Trusted Drive read port is unavailable.", status_code=503
            )
        return build_drive_read_handlers(
            self._drive_port,  # type: ignore[arg-type]
            binding_ref=grant.binding_ref,
            actor_ref=grant.actor_ref,
        )

    async def _authorized_folder_resource(self, grant: DriveGrant, folder_id: str) -> DriveCaseResource:
        """Re-fetch canonical metadata for the intent id and require a real folder.

        The browser id is never turned into a resource directly: the canonical
        Drive ``get_file_metadata`` handler resolves it under the current grant.
        """

        handlers = self._handlers(grant)
        try:
            envelope = await handlers[DRIVE_GET_FILE_METADATA_TOOL_ID]({"fileId": folder_id})
        except DriveContractError:
            raise DriveCaseFolderEngineError(
                "folder_not_selectable",
                "The Drive resource cannot be selected as a case folder.",
                status_code=422,
            ) from None
        except ToolHandlerError:
            raise DriveCaseFolderEngineError(
                "folder_lookup_failed", "Drive folder could not be verified.", status_code=422
            ) from None
        if not isinstance(envelope, Mapping) or envelope.get("result_status") != "OK":
            raise DriveCaseFolderEngineError(
                "folder_lookup_failed", "Drive folder could not be verified.", status_code=422
            )
        projection = envelope.get("projection")
        if not isinstance(projection, Mapping):
            raise DriveCaseFolderEngineError(
                "folder_lookup_failed", "Drive folder could not be verified.", status_code=422
            )
        return self._resource_from_projection(grant, projection)

    def _resource_from_projection(self, grant: DriveGrant, projection: Mapping[str, Any]) -> DriveCaseResource:
        if projection.get("shortcut_target_id") is not None:
            raise DriveCaseFolderEngineError(
                "shortcut_selection", "A Drive shortcut cannot be selected.", status_code=422
            )
        mime_type = projection.get("mime_type")
        if not isinstance(mime_type, str) or mime_type.split(";", 1)[0].strip().lower() != GOOGLE_FOLDER_MIME:
            raise DriveCaseFolderEngineError(
                "non_folder_selection", "The selected Drive resource is not a folder.", status_code=422
            )
        return DriveCaseResource.from_provider(
            binding_ref=grant.binding_ref,
            metadata={
                "id": projection.get("file_id"),
                "name": projection.get("name"),
                "mimeType": mime_type,
                "parents": [],
                "driveId": projection.get("shared_drive_id"),
                "trashed": projection.get("trashed", False),
                "modifiedTime": (projection.get("version_evidence") or {}).get("modified_time")
                if isinstance(projection.get("version_evidence"), Mapping)
                else None,
            },
        )

    async def _folder_candidates(self, grant: DriveGrant, *, query: object) -> dict[str, Any]:
        handlers = self._handlers(grant)
        arguments: dict[str, Any] = {}
        if isinstance(query, str) and query.strip():
            handler = handlers[DRIVE_SEARCH_FILES_TOOL_ID]
            arguments = {"query": query.strip()}
        else:
            handler = handlers[DRIVE_LIST_RECENT_FILES_TOOL_ID]
        try:
            envelope = await handler(arguments)
        except DriveContractError:
            raise DriveCaseFolderEngineError(
                "folder_listing_failed", "Drive folder listing is unavailable.", status_code=422
            ) from None
        except ToolHandlerError:
            raise DriveCaseFolderEngineError(
                "folder_listing_failed", "Drive folder listing is unavailable.", status_code=502
            ) from None
        if not isinstance(envelope, Mapping):
            raise DriveCaseFolderEngineError(
                "folder_listing_failed", "Drive folder listing is unavailable.", status_code=502
            )
        raw_files = envelope.get("files")
        files = raw_files if isinstance(raw_files, list) else []
        folders: list[dict[str, Any]] = []
        for item in files:
            if not isinstance(item, Mapping):
                continue
            mime_type = item.get("mime_type")
            if not isinstance(mime_type, str) or mime_type.split(";", 1)[0].strip().lower() != GOOGLE_FOLDER_MIME:
                continue
            if item.get("shortcut_target_id") is not None:
                continue
            if item.get("trashed") is True:
                continue
            folder_id = item.get("file_id")
            name = _bounded_text(item.get("name"), MAX_CANDIDATE_NAME_CHARS)
            if not isinstance(folder_id, str) or not folder_id.strip() or name is None:
                continue
            version = item.get("version_evidence")
            modified = version.get("modified_time") if isinstance(version, Mapping) else None
            folders.append(
                {
                    "folder_id": folder_id.strip(),
                    "name": name,
                    "space_kind": item.get("space_kind") if item.get("space_kind") in ("my_drive", "shared_drive") else "my_drive",
                    "modified_time": modified if isinstance(modified, str) else None,
                }
            )
            if len(folders) >= MAX_CANDIDATE_FOLDERS:
                break
        more = bool(envelope.get("more_results_available")) or len(folders) >= MAX_CANDIDATE_FOLDERS
        return {"folders": folders, "more": more}


def drive_case_folder_service_snapshot() -> dict[str, Any]:
    """Deterministic, network-free snapshot of this service's posture."""

    return {
        "service_version": DRIVE_CASE_FOLDER_SERVICE_VERSION,
        "paths": list(DRIVE_CASE_FOLDER_PATHS),
        "folder_id_is_selection_intent": True,
        "engine_refetches_metadata": True,
        "requires_current_drive_grant": True,
        "reuses_canonical_drive_handlers": True,
        "browser_authority_fields": sorted(_UNSAFE_AUTHORITY_FIELDS),
        "candidate_limit": MAX_CANDIDATE_FOLDERS,
        "claims_exhaustive_listing": False,
        "second_drive_client": False,
        "second_tool_runtime": False,
        "second_oauth_authority": False,
        "live_provider_calls_in_source": 0,
    }


__all__ = [
    "DRIVE_CASE_FOLDER_SERVICE_VERSION",
    "STATUS_PATH",
    "FOLDERS_PATH",
    "SELECT_PATH",
    "CLEAR_PATH",
    "DRIVE_CASE_FOLDER_PATHS",
    "MAX_CANDIDATE_FOLDERS",
    "DriveCaseFolderEngineService",
    "DriveCaseFolderEngineError",
    "drive_case_folder_service_snapshot",
]
