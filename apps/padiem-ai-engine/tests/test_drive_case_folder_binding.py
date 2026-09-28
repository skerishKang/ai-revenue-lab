"""Drive project case-folder binding authority tests (#3188, parent #3138).

Network-free and credential-free. Proves the durable selected-folder authority:
trusted typed writes, explicit replacement, cross-scope denial, Drive-binding
drift fail-closed, and server-state scope reconstruction only (no caller folder
id, no caller ancestry).
"""

from __future__ import annotations

import asyncio
import inspect
import pathlib

import pytest

from padiem_ai_core.drive_capability import DRIVE_CONNECTOR_ID, DriveCapability
from padiem_ai_core.drive_case_folder_scope import (
    DriveCaseFolderScope,
    DriveCaseResource,
)

import app.drive_case_folder_binding as binding_module
from app.connector_bindings import DriveGrant
from app.drive_case_folder_binding import (
    BINDING_TABLE_NAME,
    OUTCOME_CREATED,
    OUTCOME_IDEMPOTENT,
    OUTCOME_REPLACED,
    DriveCaseFolderBindingAuthority,
    DriveCaseFolderBindingError,
    InMemoryDriveCaseFolderBindingStore,
    drive_case_folder_binding_snapshot,
)

WORKSPACE_A = "ws_alpha_001"
WORKSPACE_B = "ws_beta_002"
PROJECT_A = "proj_" + "a" * 32
PROJECT_B = "proj_" + "b" * 32
BINDING_A = "bind:drive_alpha"
BINDING_B = "bind:drive_beta"
FOLDER_1 = "folder_case_001"
FOLDER_2 = "folder_case_002"
SHARED_DRIVE = "shared_drive_009"
GOOGLE_FOLDER_MIME = "application/vnd.google-apps.folder"
GOOGLE_SHORTCUT_MIME = "application/vnd.google-apps.shortcut"

MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "migrations"
    / "0008_engine_drive_case_folder_bindings.sql"
)


def run(coro):
    return asyncio.run(coro)


def drive_grant(binding_ref: str = BINDING_A, *capabilities: DriveCapability) -> DriveGrant:
    return DriveGrant(
        app_id="app_legal",
        canonical_agent_id="agent:padiem:claw_drive@1",
        binding_ref=binding_ref,
        actor_ref="actor_1",
        granted_capabilities=capabilities or (DriveCapability.READ,),
    )


def folder_resource(
    folder_id: str = FOLDER_1,
    *,
    binding_ref: str = BINDING_A,
    shared_drive_id: str | None = None,
    trashed: bool = False,
    mime_type: str = GOOGLE_FOLDER_MIME,
    shortcut_target_id: str | None = None,
) -> DriveCaseResource:
    return DriveCaseResource(
        binding_ref=binding_ref,
        resource_id=folder_id,
        mime_type=mime_type,
        shared_drive_id=shared_drive_id,
        trashed=trashed,
        shortcut_target_id=shortcut_target_id,
    )


def authority(store=None, clock=None) -> DriveCaseFolderBindingAuthority:
    return DriveCaseFolderBindingAuthority(
        store=store or InMemoryDriveCaseFolderBindingStore(), clock=clock
    )


class StubBindingStore:
    """Returns a preset row so malformed storage can be exercised."""

    def __init__(self, row) -> None:
        self.row = row
        self.upserts = 0
        self.deactivations = 0

    async def load_active(self, *, workspace_ref: str, project_id: str, connector_id: str):
        return self.row

    async def upsert_active(self, row) -> None:
        self.upserts += 1

    async def deactivate(self, *, workspace_ref: str, project_id: str, connector_id: str) -> bool:
        self.deactivations += 1
        return False


# --- 1. trusted bind + server-state scope reconstruction -------------------


def test_trusted_project_folder_bind_is_persisted() -> None:
    held = authority()
    binding, outcome = run(
        held.bind_selected_folder(
            workspace_ref=WORKSPACE_A,
            project_id=PROJECT_A,
            drive_grant=drive_grant(),
            selected_resource=folder_resource(),
        )
    )
    assert outcome == OUTCOME_CREATED
    assert binding.workspace_ref == WORKSPACE_A
    assert binding.project_id == PROJECT_A
    assert binding.connector_id == DRIVE_CONNECTOR_ID
    assert binding.drive_binding_ref == BINDING_A
    assert binding.selected_folder_id == FOLDER_1
    assert binding.shared_drive_id is None
    assert binding.space_kind == "my_drive"
    assert binding.active is True


def test_scope_is_reconstructed_from_server_state() -> None:
    store = InMemoryDriveCaseFolderBindingStore()
    held = authority(store)
    run(
        held.bind_selected_folder(
            workspace_ref=WORKSPACE_A,
            project_id=PROJECT_A,
            drive_grant=drive_grant(),
            selected_resource=folder_resource(),
        )
    )
    scope = run(
        held.load_case_folder_scope(
            workspace_ref=WORKSPACE_A, project_id=PROJECT_A, drive_grant=drive_grant()
        )
    )
    assert isinstance(scope, DriveCaseFolderScope)
    # the binding ref comes from the *current* grant, the rest from stored state
    assert scope.binding_ref == BINDING_A
    assert scope.selected_folder_id == FOLDER_1
    assert scope.shared_drive_id is None

    # a stored change is what a later load reflects - no caller value is used
    row = run(store.load_active(workspace_ref=WORKSPACE_A, project_id=PROJECT_A, connector_id=DRIVE_CONNECTOR_ID))
    assert row is not None
    row["selected_folder_id"] = FOLDER_2
    run(store.upsert_active(row))
    reloaded = run(
        held.load_case_folder_scope(
            workspace_ref=WORKSPACE_A, project_id=PROJECT_A, drive_grant=drive_grant()
        )
    )
    assert reloaded.selected_folder_id == FOLDER_2


def test_shared_drive_identity_is_preserved() -> None:
    held = authority()
    run(
        held.bind_selected_folder(
            workspace_ref=WORKSPACE_A,
            project_id=PROJECT_A,
            drive_grant=drive_grant(),
            selected_resource=folder_resource(shared_drive_id=SHARED_DRIVE),
        )
    )
    scope = run(
        held.load_case_folder_scope(
            workspace_ref=WORKSPACE_A, project_id=PROJECT_A, drive_grant=drive_grant()
        )
    )
    assert scope.shared_drive_id == SHARED_DRIVE


# --- 2. idempotent replay + explicit replacement ---------------------------


def test_same_bind_replay_is_idempotent() -> None:
    store = InMemoryDriveCaseFolderBindingStore()
    held = authority(store)
    first, first_outcome = run(
        held.bind_selected_folder(
            workspace_ref=WORKSPACE_A,
            project_id=PROJECT_A,
            drive_grant=drive_grant(),
            selected_resource=folder_resource(),
        )
    )
    second, second_outcome = run(
        held.bind_selected_folder(
            workspace_ref=WORKSPACE_A,
            project_id=PROJECT_A,
            drive_grant=drive_grant(),
            selected_resource=folder_resource(),
        )
    )
    assert first_outcome == OUTCOME_CREATED
    assert second_outcome == OUTCOME_IDEMPOTENT
    assert second.created_at == first.created_at


def test_explicit_folder_replace_is_recorded() -> None:
    held = authority()
    run(
        held.bind_selected_folder(
            workspace_ref=WORKSPACE_A,
            project_id=PROJECT_A,
            drive_grant=drive_grant(),
            selected_resource=folder_resource(),
        )
    )
    replaced, outcome = run(
        held.bind_selected_folder(
            workspace_ref=WORKSPACE_A,
            project_id=PROJECT_A,
            drive_grant=drive_grant(),
            selected_resource=folder_resource(FOLDER_2),
        )
    )
    assert outcome == OUTCOME_REPLACED
    assert replaced.selected_folder_id == FOLDER_2
    scope = run(
        held.load_case_folder_scope(
            workspace_ref=WORKSPACE_A, project_id=PROJECT_A, drive_grant=drive_grant()
        )
    )
    assert scope.selected_folder_id == FOLDER_2


# --- 3. write contract denials --------------------------------------------


def test_non_folder_selection_is_denied() -> None:
    held = authority()
    with pytest.raises(DriveCaseFolderBindingError) as excinfo:
        run(
            held.bind_selected_folder(
                workspace_ref=WORKSPACE_A,
                project_id=PROJECT_A,
                drive_grant=drive_grant(),
                selected_resource=folder_resource(mime_type="text/plain"),
            )
        )
    assert excinfo.value.code == "non_folder_selection"


def test_shortcut_selection_is_denied() -> None:
    held = authority()
    with pytest.raises(DriveCaseFolderBindingError) as excinfo:
        run(
            held.bind_selected_folder(
                workspace_ref=WORKSPACE_A,
                project_id=PROJECT_A,
                drive_grant=drive_grant(),
                selected_resource=folder_resource(
                    mime_type=GOOGLE_SHORTCUT_MIME, shortcut_target_id=FOLDER_2
                ),
            )
        )
    assert excinfo.value.code == "shortcut_selection"


def test_trashed_folder_selection_is_denied() -> None:
    held = authority()
    with pytest.raises(DriveCaseFolderBindingError) as excinfo:
        run(
            held.bind_selected_folder(
                workspace_ref=WORKSPACE_A,
                project_id=PROJECT_A,
                drive_grant=drive_grant(),
                selected_resource=folder_resource(trashed=True),
            )
        )
    assert excinfo.value.code == "trashed_selection"


def test_drive_binding_mismatch_on_write_is_denied() -> None:
    held = authority()
    with pytest.raises(DriveCaseFolderBindingError) as excinfo:
        run(
            held.bind_selected_folder(
                workspace_ref=WORKSPACE_A,
                project_id=PROJECT_A,
                drive_grant=drive_grant(BINDING_A),
                selected_resource=folder_resource(binding_ref=BINDING_B),
            )
        )
    assert excinfo.value.code == "drive_binding_mismatch"


def test_project_id_must_reuse_existing_proj_identity() -> None:
    held = authority()
    for bad in ("matter_123", "case_" + "a" * 32, "proj_XYZ", "proj_" + "a" * 31):
        with pytest.raises(DriveCaseFolderBindingError) as excinfo:
            run(
                held.bind_selected_folder(
                    workspace_ref=WORKSPACE_A,
                    project_id=bad,
                    drive_grant=drive_grant(),
                    selected_resource=folder_resource(),
                )
            )
        assert excinfo.value.code == "invalid_project_id"


def test_write_grant_is_required_and_read_only() -> None:
    held = authority()
    with pytest.raises(DriveCaseFolderBindingError) as excinfo:
        run(
            held.bind_selected_folder(
                workspace_ref=WORKSPACE_A,
                project_id=PROJECT_A,
                drive_grant=drive_grant(BINDING_A, DriveCapability.READ, DriveCapability.MUTATION),
                selected_resource=folder_resource(),
            )
        )
    assert excinfo.value.code == "invalid_drive_grant"
    with pytest.raises(DriveCaseFolderBindingError):
        run(
            held.bind_selected_folder(
                workspace_ref=WORKSPACE_A,
                project_id=PROJECT_A,
                drive_grant=object(),  # type: ignore[arg-type]
                selected_resource=folder_resource(),
            )
        )


# --- 4. cross-scope + drift + malformed rows ------------------------------


def test_cross_workspace_read_is_denied() -> None:
    held = authority()
    run(
        held.bind_selected_folder(
            workspace_ref=WORKSPACE_A,
            project_id=PROJECT_A,
            drive_grant=drive_grant(),
            selected_resource=folder_resource(),
        )
    )
    with pytest.raises(DriveCaseFolderBindingError) as excinfo:
        run(
            held.load_case_folder_scope(
                workspace_ref=WORKSPACE_B, project_id=PROJECT_A, drive_grant=drive_grant()
            )
        )
    assert excinfo.value.code == "no_binding"


def test_cross_project_read_is_denied() -> None:
    held = authority()
    run(
        held.bind_selected_folder(
            workspace_ref=WORKSPACE_A,
            project_id=PROJECT_A,
            drive_grant=drive_grant(),
            selected_resource=folder_resource(),
        )
    )
    with pytest.raises(DriveCaseFolderBindingError) as excinfo:
        run(
            held.load_case_folder_scope(
                workspace_ref=WORKSPACE_A, project_id=PROJECT_B, drive_grant=drive_grant()
            )
        )
    assert excinfo.value.code == "no_binding"


def test_no_binding_fails_closed() -> None:
    held = authority()
    with pytest.raises(DriveCaseFolderBindingError) as excinfo:
        run(
            held.load_case_folder_scope(
                workspace_ref=WORKSPACE_A, project_id=PROJECT_A, drive_grant=drive_grant()
            )
        )
    assert excinfo.value.code == "no_binding"
    assert excinfo.value.status_code == 404


def test_current_drive_binding_drift_is_denied_and_builds_no_scope(monkeypatch) -> None:
    constructions: list[object] = []
    real_scope = binding_module.DriveCaseFolderScope

    def counting_scope(*args, **kwargs):  # type: ignore[no-untyped-def]
        constructions.append(1)
        return real_scope(*args, **kwargs)

    monkeypatch.setattr(binding_module, "DriveCaseFolderScope", counting_scope)

    held = authority()
    run(
        held.bind_selected_folder(
            workspace_ref=WORKSPACE_A,
            project_id=PROJECT_A,
            drive_grant=drive_grant(BINDING_A),
            selected_resource=folder_resource(),
        )
    )
    # the Drive connection changed after the folder was bound
    with pytest.raises(DriveCaseFolderBindingError) as excinfo:
        run(
            held.load_case_folder_scope(
                workspace_ref=WORKSPACE_A, project_id=PROJECT_A, drive_grant=drive_grant(BINDING_B)
            )
        )
    assert excinfo.value.code == "drive_binding_drift"
    assert constructions == [], "no DriveCaseFolderScope may be built on drift"


def test_malformed_stored_rows_are_denied() -> None:
    good = {
        "workspace_ref": WORKSPACE_A,
        "project_id": PROJECT_A,
        "connector_id": DRIVE_CONNECTOR_ID,
        "drive_binding_ref": BINDING_A,
        "selected_folder_id": FOLDER_1,
        "shared_drive_id": None,
        "active": 1,
        "created_at": "2026-09-28T00:00:00+00:00",
        "updated_at": "2026-09-28T00:00:00+00:00",
    }

    malformed_variants = [
        {**good, "drive_binding_ref": ""},
        {**good, "selected_folder_id": "  "},
        {**good, "project_id": "not_a_project"},
        {**good, "connector_id": "connector:google:gmail@1"},
        {**good, "active": 0},
        {**good, "created_at": "not-a-timestamp"},
        {key: value for key, value in good.items() if key != "selected_folder_id"},
    ]
    for variant in malformed_variants:
        held = authority(StubBindingStore(variant))
        with pytest.raises(DriveCaseFolderBindingError):
            run(
                held.load_case_folder_scope(
                    workspace_ref=WORKSPACE_A, project_id=PROJECT_A, drive_grant=drive_grant()
                )
            )


def test_row_from_another_scope_is_denied() -> None:
    row = {
        "workspace_ref": WORKSPACE_B,
        "project_id": PROJECT_A,
        "connector_id": DRIVE_CONNECTOR_ID,
        "drive_binding_ref": BINDING_A,
        "selected_folder_id": FOLDER_1,
        "shared_drive_id": None,
        "active": 1,
        "created_at": "2026-09-28T00:00:00+00:00",
        "updated_at": "2026-09-28T00:00:00+00:00",
    }
    held = authority(StubBindingStore(row))
    with pytest.raises(DriveCaseFolderBindingError) as excinfo:
        run(
            held.load_case_folder_scope(
                workspace_ref=WORKSPACE_A, project_id=PROJECT_A, drive_grant=drive_grant()
            )
        )
    assert excinfo.value.code == "binding_scope_mismatch"


def test_clear_deactivates_the_exact_scope() -> None:
    held = authority()
    run(
        held.bind_selected_folder(
            workspace_ref=WORKSPACE_A,
            project_id=PROJECT_A,
            drive_grant=drive_grant(),
            selected_resource=folder_resource(),
        )
    )
    assert run(
        held.clear(workspace_ref=WORKSPACE_A, project_id=PROJECT_A, drive_grant=drive_grant())
    ) is True
    with pytest.raises(DriveCaseFolderBindingError) as excinfo:
        run(
            held.load_case_folder_scope(
                workspace_ref=WORKSPACE_A, project_id=PROJECT_A, drive_grant=drive_grant()
            )
        )
    assert excinfo.value.code == "no_binding"


# --- 5. no caller folder authority, no leaks ------------------------------


def test_binding_api_exposes_no_caller_folder_authority() -> None:
    for method in (
        DriveCaseFolderBindingAuthority.bind_selected_folder,
        DriveCaseFolderBindingAuthority.load_case_folder_scope,
        DriveCaseFolderBindingAuthority.status,
    ):
        params = set(inspect.signature(method).parameters)
        assert "folder_id" not in params
        assert "selected_folder_id" not in params
        assert "drive_binding_ref" not in params
        assert "scope" not in params


def test_public_status_hides_raw_identifiers() -> None:
    held = authority()
    run(
        held.bind_selected_folder(
            workspace_ref=WORKSPACE_A,
            project_id=PROJECT_A,
            drive_grant=drive_grant(),
            selected_resource=folder_resource(),
        )
    )
    status = run(
        held.status(workspace_ref=WORKSPACE_A, project_id=PROJECT_A, drive_grant=drive_grant())
    )
    assert set(status) == {"configured", "space_kind", "scope_token", "updated_at"}
    assert status["configured"] is True
    assert status["space_kind"] == "my_drive"
    rendered = repr(status)
    for secret in (FOLDER_1, BINDING_A, WORKSPACE_A, PROJECT_A):
        assert secret not in rendered
    assert status["scope_token"].startswith("drive_scope_")


def test_status_without_binding_is_not_configured() -> None:
    held = authority()
    status = run(
        held.status(workspace_ref=WORKSPACE_A, project_id=PROJECT_A, drive_grant=drive_grant())
    )
    assert status == {"configured": False, "space_kind": None, "scope_token": None, "updated_at": None}


def test_stored_row_and_repr_carry_no_credentials() -> None:
    held = authority()
    binding, _ = run(
        held.bind_selected_folder(
            workspace_ref=WORKSPACE_A,
            project_id=PROJECT_A,
            drive_grant=drive_grant(),
            selected_resource=folder_resource(),
        )
    )
    row = binding.to_row()
    assert set(row) == {
        "workspace_ref",
        "project_id",
        "connector_id",
        "drive_binding_ref",
        "selected_folder_id",
        "shared_drive_id",
        "active",
        "created_at",
        "updated_at",
    }
    for key in row:
        assert "token" not in key and "secret" not in key and "email" not in key
    assert FOLDER_1 not in repr(binding)
    assert BINDING_A not in repr(binding)
    assert PROJECT_A not in repr(binding)


def test_module_source_has_no_credentials_or_second_authority() -> None:
    source = pathlib.Path(binding_module.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "refresh_token",
        "client_secret",
        "access_token",
        "import httpx",
        "import requests",
        "urllib.request",
        "socket",
        "matter_",
        "legalcase_",
        "FastAPI",
        "Starlette",
    ):
        assert forbidden not in source, f"binding module must not contain: {forbidden}"


# --- 6. D1 store + migration contracts ------------------------------------


class FakeStatement:
    def __init__(self, owner: "FakeD1Binding", sql: str) -> None:
        self._owner = owner
        self._sql = sql
        self.params: tuple = ()

    def bind(self, *params):
        self.params = params
        return self

    async def all(self):
        self._owner.calls.append((self._sql, self.params))
        return {"results": list(self._owner.rows)}

    async def run(self):
        self._owner.calls.append((self._sql, self.params))
        return {"success": True}


class FakeD1Binding:
    def __init__(self, rows=None) -> None:
        self.rows = rows or []
        self.calls: list[tuple[str, tuple]] = []

    def prepare(self, sql: str) -> FakeStatement:
        return FakeStatement(self, sql)


def test_d1_store_lookup_and_upsert_are_keyed_by_the_exact_triple() -> None:
    from app.drive_case_folder_binding import CloudflareD1DriveCaseFolderBindingStore

    row = {
        "workspace_ref": WORKSPACE_A,
        "project_id": PROJECT_A,
        "connector_id": DRIVE_CONNECTOR_ID,
        "drive_binding_ref": BINDING_A,
        "selected_folder_id": FOLDER_1,
        "shared_drive_id": None,
        "active": 1,
        "created_at": "2026-09-28T00:00:00+00:00",
        "updated_at": "2026-09-28T00:00:00+00:00",
    }
    binding = FakeD1Binding([row])
    store = CloudflareD1DriveCaseFolderBindingStore(binding)

    loaded = run(
        store.load_active(workspace_ref=WORKSPACE_A, project_id=PROJECT_A, connector_id=DRIVE_CONNECTOR_ID)
    )
    assert loaded == row
    select_sql, params = binding.calls[-1]
    assert BINDING_TABLE_NAME in select_sql
    assert "workspace_ref = ? AND project_id = ? AND connector_id = ? AND active = 1" in select_sql
    assert params == (WORKSPACE_A, PROJECT_A, DRIVE_CONNECTOR_ID)

    run(store.upsert_active(row))
    upsert_sql, _ = binding.calls[-1]
    assert "ON CONFLICT(workspace_ref, project_id, connector_id) DO UPDATE" in upsert_sql
    assert "INSERT INTO " + BINDING_TABLE_NAME in upsert_sql

    run(store.deactivate(workspace_ref=WORKSPACE_A, project_id=PROJECT_A, connector_id=DRIVE_CONNECTOR_ID))
    update_sql, _ = binding.calls[-1]
    assert update_sql.startswith(f"UPDATE {BINDING_TABLE_NAME} SET active = 0")
    assert "WHERE workspace_ref = ? AND project_id = ? AND connector_id = ? AND active = 1" in update_sql


def test_d1_store_multiple_active_rows_fail_closed() -> None:
    from app.drive_case_folder_binding import CloudflareD1DriveCaseFolderBindingStore

    row = {
        "workspace_ref": WORKSPACE_A,
        "project_id": PROJECT_A,
        "connector_id": DRIVE_CONNECTOR_ID,
        "drive_binding_ref": BINDING_A,
        "selected_folder_id": FOLDER_1,
        "shared_drive_id": None,
        "active": 1,
        "created_at": "2026-09-28T00:00:00+00:00",
        "updated_at": "2026-09-28T00:00:00+00:00",
    }
    store = CloudflareD1DriveCaseFolderBindingStore(FakeD1Binding([row, row]))
    with pytest.raises(DriveCaseFolderBindingError) as excinfo:
        run(
            store.load_active(
                workspace_ref=WORKSPACE_A, project_id=PROJECT_A, connector_id=DRIVE_CONNECTOR_ID
            )
        )
    assert excinfo.value.code == "malformed_stored_binding"


def test_migration_declares_the_bounded_binding_table() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert f"CREATE TABLE IF NOT EXISTS {BINDING_TABLE_NAME}" in sql
    assert (
        "CREATE INDEX IF NOT EXISTS idx_padiem_engine_drive_case_folder_bindings_active" in sql
    )
    assert "PRIMARY KEY (workspace_ref, project_id, connector_id)" in sql
    assert "project_id LIKE 'proj_%'" in sql
    assert "active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))" in sql
    assert "ALTER TABLE" not in sql
    import re

    assert re.search(r"^\s*(DROP|DELETE|UPDATE|INSERT)\b", sql, re.M) is None
    for secret in ("token", "secret", "email", "password"):
        assert secret not in sql.lower()


def test_snapshot_posture_is_source_only() -> None:
    snapshot = drive_case_folder_binding_snapshot()
    assert snapshot["reuses_existing_project_identity"] is True
    assert snapshot["creates_new_legal_identity_store"] is False
    assert snapshot["one_project_one_active_selected_folder"] is True
    assert snapshot["scope_reconstructed_from_server_state"] is True
    assert snapshot["requires_current_drive_grant"] is True
    assert snapshot["drive_binding_drift_fail_closed"] is True
    assert snapshot["caller_folder_authority"] is False
    assert snapshot["live_provider_lookup"] is False
    assert snapshot["live_ancestry_resolver"] is False
    assert snapshot["public_route"] is False
    assert snapshot["stores_raw_credentials"] is False
    assert snapshot["production_mutation"] is False
