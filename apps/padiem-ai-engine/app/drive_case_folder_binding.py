"""Trusted durable Project -> selected Drive case-folder authority (#3188).

Closes the authority gap left by #3173/#3178: a project (the B67 Legal matter
identity, reused from the existing Padiem Chat ``proj_*`` Project) is bound,
inside one canonical connector workspace, to exactly one selected Google Drive
case folder. A product route can then reconstruct a canonical
``DriveCaseFolderScope`` from *server state* instead of trusting a caller
folder id.

Authority rules:

* no new Legal matter store: ``project_id`` is the existing Padiem Chat
  ``proj_<32 hex>`` identity; project ownership stays with Padiem Chat's
  existing HistoryStore authority (``PROJECT_OWNERSHIP_AUTHORITY``);
* no new workspace authority: the key is ``workspace_ref`` + ``project_id`` +
  the canonical Drive connector, so a different workspace can never read
  another workspace's binding;
* write requires server-side typed facts: a trusted workspace ref, a validated
  project ref, the **current** canonical ``DriveGrant`` (the trusted
  ``DRIVE_REFERENCE_APP_ID`` / ``DRIVE_AGENT_ID`` Engine slot carrying exactly
  the reviewed READ capability) and a canonical ``DriveCaseResource`` that is a
  non-trashed, non-shortcut FOLDER matching that grant's binding;
* read requires the current canonical ``DriveGrant`` again and fails closed
  when the stored ``drive_binding_ref`` no longer equals the live grant (a
  reconnect must not silently inherit an old folder scope);
* no credentials, owner/actor email, Drive content, folder names or unrelated
  metadata are stored;
* no live provider call and no live ancestry resolver: caller-supplied ancestry
  is never authority here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import re
from typing import Any, Protocol

from padiem_ai_core.drive_capability import DRIVE_CONNECTOR_ID, DriveCapability
from padiem_ai_core.drive_case_folder_scope import (
    DriveCaseFolderScope,
    DriveCaseResource,
    DriveCaseResourceKind,
)

from app.connector_bindings import DRIVE_AGENT_ID, DRIVE_REFERENCE_APP_ID, DriveGrant

DRIVE_CASE_FOLDER_BINDING_VERSION = "engine-drive-case-folder-binding.v1"

BINDING_TABLE_NAME = "padiem_engine_drive_case_folder_bindings"

PROJECT_ID_PREFIX = "proj_"
PROJECT_ID_HEX_CHARS = 32

# Declared review state for this slice.
ONE_PROJECT_ONE_ACTIVE_SELECTED_FOLDER = True
LIVE_PROVIDER_LOOKUP = False
LIVE_ANCESTRY_RESOLVER = False
PUBLIC_ROUTE = False
STORES_RAW_CREDENTIALS = False
CREATES_LEGAL_MATTER_STORE = False

OUTCOME_CREATED = "created"
OUTCOME_IDEMPOTENT = "idempotent"
OUTCOME_REPLACED = "replaced"

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_PROJECT_HEX_RE = re.compile(r"^[0-9a-f]{32}$")
_MAX_ERROR_CODE_CHARS = 64

_BINDING_COLUMNS = (
    "workspace_ref",
    "project_id",
    "connector_id",
    "drive_binding_ref",
    "selected_folder_id",
    "shared_drive_id",
    "active",
    "created_at",
    "updated_at",
)


class DriveCaseFolderBindingError(ValueError):
    """Fail-closed binding authority error safe for first-party products.

    Messages are static per code and never echo stored ids, refs, scope values
    or storage state.
    """

    def __init__(self, code: str, safe_message: str, *, status_code: int = 400) -> None:
        super().__init__(safe_message)
        if (
            not isinstance(code, str)
            or not code
            or len(code) > _MAX_ERROR_CODE_CHARS
            or not code[0].islower()
        ):
            raise ValueError("binding error code must be a bounded lowercase token")
        self.code = code
        self.safe_message = safe_message
        self.status_code = status_code


@dataclass(frozen=True, slots=True, repr=False)
class DriveCaseFolderBinding:
    """One durable selected-folder binding for workspace + project + Drive.

    The repr redacts every identifier: logs must not leak the workspace ref,
    the project id, the Drive binding ref or the selected folder id.
    """

    workspace_ref: str
    project_id: str
    connector_id: str
    drive_binding_ref: str
    selected_folder_id: str
    shared_drive_id: str | None
    created_at: datetime
    updated_at: datetime
    active: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_ref", _require_safe_ref(self.workspace_ref, "workspace_ref"))
        object.__setattr__(self, "project_id", _require_project_id(self.project_id))
        if self.connector_id != DRIVE_CONNECTOR_ID:
            raise DriveCaseFolderBindingError(
                "unsupported_connector", "Binding connector is not the canonical Drive connector."
            )
        object.__setattr__(
            self, "drive_binding_ref", _require_safe_ref(self.drive_binding_ref, "drive_binding_ref")
        )
        object.__setattr__(
            self, "selected_folder_id", _require_safe_ref(self.selected_folder_id, "selected_folder_id")
        )
        object.__setattr__(
            self,
            "shared_drive_id",
            None if self.shared_drive_id is None else _require_safe_ref(self.shared_drive_id, "shared_drive_id"),
        )
        if not isinstance(self.active, bool):
            raise DriveCaseFolderBindingError("invalid_binding", "Binding active flag is invalid.")
        for label, value in (("created_at", self.created_at), ("updated_at", self.updated_at)):
            if not isinstance(value, datetime) or value.tzinfo is None:
                raise DriveCaseFolderBindingError("invalid_binding", "Binding timestamps are invalid.")
        if self.updated_at < self.created_at:
            raise DriveCaseFolderBindingError("invalid_binding", "Binding timestamps are invalid.")

    @property
    def space_kind(self) -> str:
        return "shared_drive" if self.shared_drive_id else "my_drive"

    def __repr__(self) -> str:
        return (
            "DriveCaseFolderBinding("
            f"space_kind={self.space_kind}, active={self.active}, "
            f"updated_at={self.updated_at.isoformat()}, "
            "workspace_ref=redacted, project_id=redacted, drive_binding_ref=redacted, "
            "selected_folder_id=redacted)"
        )

    def to_row(self) -> dict[str, Any]:
        return {
            "workspace_ref": self.workspace_ref,
            "project_id": self.project_id,
            "connector_id": self.connector_id,
            "drive_binding_ref": self.drive_binding_ref,
            "selected_folder_id": self.selected_folder_id,
            "shared_drive_id": self.shared_drive_id,
            "active": 1 if self.active else 0,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


# --- bounded validation helpers -------------------------------------------


def _require_safe_ref(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise DriveCaseFolderBindingError("invalid_binding", f"{field_name} must be a string.")
    normalized = value.strip()
    if not _SAFE_REF_RE.fullmatch(normalized):
        raise DriveCaseFolderBindingError("invalid_binding", f"{field_name} is not a bounded safe reference.")
    return normalized


def _require_project_id(value: object) -> str:
    if not isinstance(value, str):
        raise DriveCaseFolderBindingError("invalid_project_id", "Project id must be a string.")
    normalized = value.strip()
    if not normalized.startswith(PROJECT_ID_PREFIX):
        raise DriveCaseFolderBindingError(
            "invalid_project_id", "Project id must reuse the existing proj_* identity."
        )
    hex_part = normalized[len(PROJECT_ID_PREFIX):]
    if len(hex_part) != PROJECT_ID_HEX_CHARS or not _PROJECT_HEX_RE.fullmatch(hex_part):
        raise DriveCaseFolderBindingError("invalid_project_id", "Project id is not a bounded proj_* id.")
    return normalized


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        candidate = value.strip()
        try:
            parsed = datetime.fromisoformat(candidate[:-1] + "+00:00" if candidate.endswith("Z") else candidate)
        except ValueError as exc:
            raise DriveCaseFolderBindingError(
                "malformed_stored_binding", "Stored binding row is malformed."
            ) from exc
    else:
        raise DriveCaseFolderBindingError("malformed_stored_binding", "Stored binding row is malformed.")
    if parsed.tzinfo is None:
        raise DriveCaseFolderBindingError("malformed_stored_binding", "Stored binding row is malformed.")
    return parsed


def _parse_row(row: Mapping[str, Any], *, workspace_ref: str, project_id: str) -> DriveCaseFolderBinding:
    """Parse a stored row fail closed; never repair or infer a broken row."""

    if not isinstance(row, Mapping):
        raise DriveCaseFolderBindingError("malformed_stored_binding", "Stored binding row is malformed.")
    for column in _BINDING_COLUMNS:
        if column not in row:
            raise DriveCaseFolderBindingError("malformed_stored_binding", "Stored binding row is malformed.")
    try:
        active_value = row.get("active")
        active = active_value in (1, True, "1") if not isinstance(active_value, bool) else active_value
        binding = DriveCaseFolderBinding(
            workspace_ref=row.get("workspace_ref"),
            project_id=row.get("project_id"),
            connector_id=row.get("connector_id"),
            drive_binding_ref=row.get("drive_binding_ref"),
            selected_folder_id=row.get("selected_folder_id"),
            shared_drive_id=row.get("shared_drive_id"),
            created_at=_parse_time(row.get("created_at")),
            updated_at=_parse_time(row.get("updated_at")),
            active=bool(active),
        )
    except DriveCaseFolderBindingError as exc:
        if exc.code == "malformed_stored_binding":
            raise
        raise DriveCaseFolderBindingError(
            "malformed_stored_binding", "Stored binding row is malformed."
        ) from None
    if binding.workspace_ref != workspace_ref or binding.project_id != project_id:
        # A row from another workspace/project is never readable here.
        raise DriveCaseFolderBindingError("binding_scope_mismatch", "Stored binding does not match the request.")
    if not binding.active:
        raise DriveCaseFolderBindingError("binding_inactive", "Stored binding is not active.")
    return binding


def _require_grant(drive_grant: object) -> DriveGrant:
    """Require the canonical Drive Engine slot, not merely a typed DriveGrant.

    ``DriveGrant`` itself accepts arbitrary app/agent ids, so the type alone is
    not grant authority: the canonical slot constants and the exact reviewed
    read-only capability set are enforced here (parity with the D1 grant
    loader).
    """

    if not isinstance(drive_grant, DriveGrant):
        raise DriveCaseFolderBindingError(
            "invalid_drive_grant", "A canonical DriveGrant is required.", status_code=503
        )
    if drive_grant.app_id != DRIVE_REFERENCE_APP_ID:
        raise DriveCaseFolderBindingError(
            "noncanonical_drive_grant",
            "Drive grant is not the canonical Drive Engine application slot.",
            status_code=403,
        )
    if drive_grant.canonical_agent_id != DRIVE_AGENT_ID:
        raise DriveCaseFolderBindingError(
            "noncanonical_drive_grant",
            "Drive grant is not the canonical Drive Engine agent slot.",
            status_code=403,
        )
    if tuple(drive_grant.granted_capabilities) != (DriveCapability.READ,):
        raise DriveCaseFolderBindingError(
            "invalid_drive_grant",
            "Drive grant must carry exactly the reviewed READ capability.",
            status_code=403,
        )
    if not drive_grant.binding_ref:
        raise DriveCaseFolderBindingError("invalid_drive_grant", "Drive grant binding is missing.")
    return drive_grant


def _require_selected_folder(resource: object, grant: DriveGrant) -> DriveCaseResource:
    """Validate the selected resource: a non-trashed, non-shortcut folder.

    Caller-supplied ancestry is never consulted: the selected folder is stored
    by its own identity, not by a claimed parent chain.
    """

    if not isinstance(resource, DriveCaseResource):
        raise DriveCaseFolderBindingError("invalid_selection", "A canonical DriveCaseResource is required.")
    if resource.kind is DriveCaseResourceKind.SHORTCUT or resource.shortcut_target_id is not None:
        raise DriveCaseFolderBindingError("shortcut_selection", "A Drive shortcut cannot be selected.")
    if resource.kind is not DriveCaseResourceKind.FOLDER:
        raise DriveCaseFolderBindingError("non_folder_selection", "The selected Drive resource is not a folder.")
    if resource.trashed:
        raise DriveCaseFolderBindingError("trashed_selection", "A trashed Drive folder cannot be selected.")
    if resource.binding_ref != grant.binding_ref:
        raise DriveCaseFolderBindingError(
            "drive_binding_mismatch", "Selected resource does not belong to the current Drive binding."
        )
    if resource.shared_drive_id is not None:
        _require_safe_ref(resource.shared_drive_id, "shared_drive_id")
    return resource


def _public_scope_token(binding: DriveCaseFolderBinding) -> str:
    """Stable opaque token for product display; never the raw folder id."""

    material = "\x00".join(
        (
            binding.workspace_ref,
            binding.project_id,
            binding.connector_id,
            binding.selected_folder_id,
            binding.shared_drive_id or "",
        )
    )
    return "drive_scope_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


# --- store ports ----------------------------------------------------------


class DriveCaseFolderBindingPort(Protocol):
    """Durable selected-folder binding storage keyed by the exact triple."""

    async def load_active(
        self, *, workspace_ref: str, project_id: str, connector_id: str
    ) -> Mapping[str, Any] | None: ...

    async def upsert_active(self, row: Mapping[str, Any]) -> None: ...

    async def deactivate(self, *, workspace_ref: str, project_id: str, connector_id: str) -> bool: ...


class InMemoryDriveCaseFolderBindingStore:
    """Deterministic in-memory port for tests and local composition."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str, str], dict[str, Any]] = {}

    def __repr__(self) -> str:
        return f"InMemoryDriveCaseFolderBindingStore(rows={len(self._rows)})"

    async def load_active(
        self, *, workspace_ref: str, project_id: str, connector_id: str
    ) -> Mapping[str, Any] | None:
        row = self._rows.get((workspace_ref, project_id, connector_id))
        if row is None or not row.get("active"):
            return None
        return dict(row)

    async def upsert_active(self, row: Mapping[str, Any]) -> None:
        key = (str(row["workspace_ref"]), str(row["project_id"]), str(row["connector_id"]))
        self._rows[key] = dict(row)

    async def deactivate(self, *, workspace_ref: str, project_id: str, connector_id: str) -> bool:
        key = (workspace_ref, project_id, connector_id)
        row = self._rows.get(key)
        if row is None or not row.get("active"):
            return False
        updated = dict(row)
        updated["active"] = 0
        self._rows[key] = updated
        return True


class CloudflareD1DriveCaseFolderBindingStore:
    """Durable selected-folder binding store backed by a trusted D1-like binding.

    One row per ``(workspace_ref, project_id, connector_id)``; replacement is an
    explicit upsert, so there is exactly one active binding per project+Drive in
    a workspace.
    """

    def __init__(self, binding: Any) -> None:
        if binding is None or not callable(getattr(binding, "prepare", None)):
            raise ValueError("drive case folder binding store requires prepare(sql)")
        self._binding = binding

    def __repr__(self) -> str:
        return "CloudflareD1DriveCaseFolderBindingStore(configured)"

    async def _all(self, sql: str, *params: Any) -> list[Mapping[str, Any]]:
        from app.continuation_d1 import _maybe_await

        result = await _maybe_await(self._binding.prepare(sql).bind(*params).all())
        if isinstance(result, Mapping):
            rows: Any = result.get("results")
        elif isinstance(result, (list, tuple)):
            rows = result
        else:
            rows = getattr(result, "results", None)
        to_py = getattr(rows, "to_py", None)
        if callable(to_py):
            rows = to_py()
        if rows is None:
            raise DriveCaseFolderBindingError(
                "binding_store_unavailable", "Drive case folder binding storage is unavailable.", status_code=503
            )
        if not isinstance(rows, (list, tuple)):
            raise DriveCaseFolderBindingError(
                "binding_store_unavailable", "Drive case folder binding storage is unavailable.", status_code=503
            )
        normalized: list[Mapping[str, Any]] = []
        for row in rows:
            row_to_py = getattr(row, "to_py", None)
            if callable(row_to_py):
                row = row_to_py()
            if not isinstance(row, Mapping):
                raise DriveCaseFolderBindingError(
                    "malformed_stored_binding", "Stored binding row is malformed.", status_code=503
                )
            normalized.append(dict(row))
        return normalized

    async def _run(self, sql: str, *params: Any) -> None:
        from app.continuation_d1 import _maybe_await

        await _maybe_await(self._binding.prepare(sql).bind(*params).run())

    async def load_active(
        self, *, workspace_ref: str, project_id: str, connector_id: str
    ) -> Mapping[str, Any] | None:
        sql = (
            f"SELECT {', '.join(_BINDING_COLUMNS)} FROM {BINDING_TABLE_NAME} "
            f"WHERE workspace_ref = ? AND project_id = ? AND connector_id = ? AND active = 1"
        )
        rows = await self._all(sql, workspace_ref, project_id, connector_id)
        if not rows:
            return None
        if len(rows) > 1:
            raise DriveCaseFolderBindingError(
                "malformed_stored_binding", "Stored binding row is malformed.", status_code=503
            )
        return rows[0]

    async def upsert_active(self, row: Mapping[str, Any]) -> None:
        columns = ", ".join(_BINDING_COLUMNS)
        placeholders = ", ".join("?" for _ in _BINDING_COLUMNS)
        sql = (
            f"INSERT INTO {BINDING_TABLE_NAME} ({columns}) VALUES ({placeholders}) "
            f"ON CONFLICT(workspace_ref, project_id, connector_id) DO UPDATE SET "
            f"drive_binding_ref = excluded.drive_binding_ref, "
            f"selected_folder_id = excluded.selected_folder_id, "
            f"shared_drive_id = excluded.shared_drive_id, "
            f"active = 1, updated_at = excluded.updated_at"
        )
        await self._run(sql, *(row[column] for column in _BINDING_COLUMNS))

    async def deactivate(self, *, workspace_ref: str, project_id: str, connector_id: str) -> bool:
        existing = await self.load_active(
            workspace_ref=workspace_ref, project_id=project_id, connector_id=connector_id
        )
        if existing is None:
            return False
        sql = (
            f"UPDATE {BINDING_TABLE_NAME} SET active = 0, updated_at = ? "
            f"WHERE workspace_ref = ? AND project_id = ? AND connector_id = ? AND active = 1"
        )
        await self._run(sql, _utcnow().isoformat(), workspace_ref, project_id, connector_id)
        return True


# --- authority ------------------------------------------------------------


class DriveCaseFolderBindingAuthority:
    """Trusted durable authority for one project's selected Drive case folder."""

    def __init__(
        self, *, store: DriveCaseFolderBindingPort, clock: Callable[[], datetime] | None = None
    ) -> None:
        if store is None or not callable(getattr(store, "load_active", None)):
            raise ValueError("binding store must expose async load_active")
        if not callable(getattr(store, "upsert_active", None)):
            raise ValueError("binding store must expose async upsert_active")
        self._store = store
        self._clock = clock if clock is not None else _utcnow

    def __repr__(self) -> str:
        return "DriveCaseFolderBindingAuthority(configured)"

    async def bind_selected_folder(
        self,
        *,
        workspace_ref: str,
        project_id: str,
        drive_grant: DriveGrant,
        selected_resource: DriveCaseResource,
    ) -> tuple[DriveCaseFolderBinding, str]:
        """Bind (or explicitly replace) the project's selected case folder.

        Returns the stored binding and one of ``created`` / ``idempotent`` /
        ``replaced``. An exact replay of the same binding + folder is
        idempotent; a different folder is an explicit replacement.
        """

        workspace = _require_safe_ref(workspace_ref, "workspace_ref")
        project = _require_project_id(project_id)
        grant = _require_grant(drive_grant)
        resource = _require_selected_folder(selected_resource, grant)

        existing_row = await self._load_row(workspace_ref=workspace, project_id=project)
        now = self._clock()
        existing = None
        if existing_row is not None:
            # A persisted authority that cannot be parsed is an integrity
            # failure, not "no binding": never overwrite it with a new one.
            existing = _parse_row(existing_row, workspace_ref=workspace, project_id=project)

        if (
            existing is not None
            and existing.drive_binding_ref == grant.binding_ref
            and existing.selected_folder_id == resource.resource_id
            and existing.shared_drive_id == resource.shared_drive_id
        ):
            return existing, OUTCOME_IDEMPOTENT

        created_at = existing.created_at if existing is not None else now
        if created_at > now:
            created_at = now
        binding = DriveCaseFolderBinding(
            workspace_ref=workspace,
            project_id=project,
            connector_id=DRIVE_CONNECTOR_ID,
            drive_binding_ref=grant.binding_ref,
            selected_folder_id=resource.resource_id,
            shared_drive_id=resource.shared_drive_id,
            created_at=created_at,
            updated_at=now,
            active=True,
        )
        await self._store.upsert_active(binding.to_row())
        return binding, (OUTCOME_REPLACED if existing is not None else OUTCOME_CREATED)

    async def load_case_folder_scope(
        self,
        *,
        workspace_ref: str,
        project_id: str,
        drive_grant: DriveGrant,
    ) -> DriveCaseFolderScope:
        """Reconstruct the canonical scope from server state, never from input.

        No ``DriveCaseFolderScope`` is constructed until the stored binding has
        been parsed and its ``drive_binding_ref`` has been verified equal to the
        current grant's binding.
        """

        workspace = _require_safe_ref(workspace_ref, "workspace_ref")
        project = _require_project_id(project_id)
        grant = _require_grant(drive_grant)

        row = await self._load_row(workspace_ref=workspace, project_id=project)
        if row is None:
            raise DriveCaseFolderBindingError(
                "no_binding", "No selected Drive case folder is configured for this project.", status_code=404
            )
        binding = _parse_row(row, workspace_ref=workspace, project_id=project)
        if binding.drive_binding_ref != grant.binding_ref:
            raise DriveCaseFolderBindingError(
                "drive_binding_drift",
                "The selected Drive folder was bound to a different Drive connection.",
                status_code=409,
            )
        # Only now may a canonical scope be reconstructed, from stored facts.
        return DriveCaseFolderScope(
            binding_ref=grant.binding_ref,
            selected_folder_id=binding.selected_folder_id,
            shared_drive_id=binding.shared_drive_id,
        )

    async def status(
        self, *, workspace_ref: str, project_id: str, drive_grant: DriveGrant
    ) -> dict[str, Any]:
        """Bounded product-safe status: no raw folder id, ref or scope ids."""

        workspace = _require_safe_ref(workspace_ref, "workspace_ref")
        project = _require_project_id(project_id)
        grant = _require_grant(drive_grant)
        row = await self._load_row(workspace_ref=workspace, project_id=project)
        if row is None:
            return {"configured": False, "space_kind": None, "scope_token": None, "updated_at": None}
        binding = _parse_row(row, workspace_ref=workspace, project_id=project)
        if binding.drive_binding_ref != grant.binding_ref:
            return {"configured": False, "space_kind": None, "scope_token": None, "updated_at": None}
        return {
            "configured": True,
            "space_kind": binding.space_kind,
            "scope_token": _public_scope_token(binding),
            "updated_at": binding.updated_at.isoformat(),
        }

    async def clear(
        self, *, workspace_ref: str, project_id: str, drive_grant: DriveGrant
    ) -> bool:
        """Deactivate the exact workspace+project Drive binding."""

        workspace = _require_safe_ref(workspace_ref, "workspace_ref")
        project = _require_project_id(project_id)
        _require_grant(drive_grant)
        return await self._store.deactivate(
            workspace_ref=workspace, project_id=project, connector_id=DRIVE_CONNECTOR_ID
        )

    async def _load_row(self, *, workspace_ref: str, project_id: str) -> Mapping[str, Any] | None:
        return await self._store.load_active(
            workspace_ref=workspace_ref,
            project_id=project_id,
            connector_id=DRIVE_CONNECTOR_ID,
        )


def drive_case_folder_binding_snapshot() -> dict[str, Any]:
    """Deterministic, network-free snapshot of this authority's posture."""

    return {
        "binding_version": DRIVE_CASE_FOLDER_BINDING_VERSION,
        "table": BINDING_TABLE_NAME,
        "connector_id": DRIVE_CONNECTOR_ID,
        "reuses_existing_project_identity": True,
        "creates_new_legal_identity_store": CREATES_LEGAL_MATTER_STORE,
        "one_project_one_active_selected_folder": ONE_PROJECT_ONE_ACTIVE_SELECTED_FOLDER,
        "scope_reconstructed_from_server_state": True,
        "requires_current_drive_grant": True,
        "drive_binding_drift_fail_closed": True,
        "caller_folder_authority": False,
        "live_provider_lookup": LIVE_PROVIDER_LOOKUP,
        "live_ancestry_resolver": LIVE_ANCESTRY_RESOLVER,
        "public_route": PUBLIC_ROUTE,
        "stores_raw_credentials": STORES_RAW_CREDENTIALS,
        "second_drive_connector": False,
        "second_oauth_authority": False,
        "production_mutation": False,
    }


__all__ = [
    "DRIVE_CASE_FOLDER_BINDING_VERSION",
    "BINDING_TABLE_NAME",
    "PROJECT_ID_PREFIX",
    "OUTCOME_CREATED",
    "OUTCOME_IDEMPOTENT",
    "OUTCOME_REPLACED",
    "ONE_PROJECT_ONE_ACTIVE_SELECTED_FOLDER",
    "DriveCaseFolderBindingError",
    "DriveCaseFolderBinding",
    "DriveCaseFolderBindingPort",
    "InMemoryDriveCaseFolderBindingStore",
    "CloudflareD1DriveCaseFolderBindingStore",
    "DriveCaseFolderBindingAuthority",
    "drive_case_folder_binding_snapshot",
]
