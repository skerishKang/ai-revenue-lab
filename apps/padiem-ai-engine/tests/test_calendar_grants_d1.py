"""D1 Calendar grant store tests (#2358).

Reuses the existing ``padiem_engine_connector_grants`` table and the
``granted_capabilities_json`` column — no schema migration is introduced.
Network-free: a fake D1 binding records SQL and returns canned rows.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from pathlib import Path

import pytest

from padiem_ai_core.calendar_capability import CALENDAR_CONNECTOR_ID, CalendarCapability
from app.connector_bindings import CALENDAR_AGENT_ID, CALENDAR_REFERENCE_APP_ID
from app.connector_grants_d1 import (
    _ACTIVATION_REFUSED_CODE,
    CloudflareD1ConnectorGrantStore,
)
from app.service import ServiceContractError

BINDING_REF = "bind:calendar_engine"
ACTOR_REF = "actor_1"

MIGRATIONS = Path(__file__).parents[1] / "migrations"
GRANT_MIGRATIONS = (
    "0003_engine_connector_grants.sql",
    "0005_engine_connector_drive_capabilities.sql",
)

WS_ALPHA_BINDING = "bind:google-calendar-alpha"
WS_ALPHA_ACTOR = "actor:alpha-owner"
WS_BETA_BINDING = "bind:google-calendar-beta"
WS_BETA_ACTOR = "actor:beta-owner"


def run(coro):
    return asyncio.run(coro)


class FakeD1Binding:
    """Mimics a Cloudflare D1 binding: ``prepare(...).bind(...).all()``."""

    def __init__(self, rows=None, *, fail=False):
        self._rows = rows or []
        self._fail = fail
        self.sqls: list[str] = []
        self.params: list[tuple] = []

    def prepare(self, sql):
        self.sqls.append(sql)
        return self

    def bind(self, *params):
        self.params.append(params)
        return self

    def all(self):
        if self._fail:
            raise RuntimeError("d1 transport failure")
        return [dict(r) for r in self._rows if r.get("active", 1) == 1]


def calendar_row(**overrides):
    row = {
        "app_id": CALENDAR_REFERENCE_APP_ID,
        "canonical_agent_id": CALENDAR_AGENT_ID,
        "connector_id": CALENDAR_CONNECTOR_ID,
        "binding_ref": BINDING_REF,
        "actor_ref": ACTOR_REF,
        "granted_capabilities_json": json.dumps(["read"]),
        "active": 1,
    }
    row.update(overrides)
    return row


def test_load_calendar_grants_returns_grants_on_hit() -> None:
    binding = FakeD1Binding(rows=[calendar_row()])
    store = CloudflareD1ConnectorGrantStore(binding)
    grants = run(store.load_calendar_grants())
    assert list(grants) == [CALENDAR_REFERENCE_APP_ID]
    grant = grants[CALENDAR_REFERENCE_APP_ID]
    assert grant.granted_capabilities == (CalendarCapability.READ,)
    assert grant.binding_ref == BINDING_REF
    # Reuses the existing table/columns: no new schema surface.
    assert "padiem_engine_connector_grants" in binding.sqls[0]
    assert "granted_capabilities_json" in binding.sqls[0]
    assert binding.params[0] == (CALENDAR_CONNECTOR_ID,)


def test_load_calendar_grants_returns_empty_on_miss() -> None:
    store = CloudflareD1ConnectorGrantStore(FakeD1Binding(rows=[]))
    assert run(store.load_calendar_grants()) == {}


def test_load_calendar_grants_ignores_inactive_rows() -> None:
    store = CloudflareD1ConnectorGrantStore(FakeD1Binding(rows=[calendar_row(active=0)]))
    assert run(store.load_calendar_grants()) == {}


def test_load_calendar_grants_rejects_write_capabilities() -> None:
    for capabilities in (
        ["create_event"],
        ["read", "create_event"],
        ["write"],
        [],
    ):
        store = CloudflareD1ConnectorGrantStore(
            FakeD1Binding(rows=[calendar_row(granted_capabilities_json=json.dumps(capabilities))])
        )
        with pytest.raises(ServiceContractError) as exc_info:
            run(store.load_calendar_grants())
        assert exc_info.value.code == "connector_grants_unavailable"


def test_load_calendar_grants_raises_on_malformed_json() -> None:
    store = CloudflareD1ConnectorGrantStore(
        FakeD1Binding(rows=[calendar_row(granted_capabilities_json="{oops")])
    )
    with pytest.raises(ServiceContractError):
        run(store.load_calendar_grants())


def test_load_calendar_grants_raises_on_binding_exception() -> None:
    store = CloudflareD1ConnectorGrantStore(FakeD1Binding(fail=True))
    with pytest.raises(ServiceContractError) as exc_info:
        run(store.load_calendar_grants())
    assert exc_info.value.code == "connector_grants_unavailable"


class MutableFakeD1Binding(FakeD1Binding):
    def run(self):
        if self._fail:
            raise RuntimeError("d1 transport failure")
        params = self.params[-1]
        if len(params) == 9:
            app_id, agent_id, connector_id, binding_ref, actor_ref, scopes, capabilities, now, _ = params
            row = {
                "app_id": app_id,
                "canonical_agent_id": agent_id,
                "connector_id": connector_id,
                "binding_ref": binding_ref,
                "actor_ref": actor_ref,
                "granted_scopes_json": scopes,
                "granted_capabilities_json": capabilities,
                "active": 1,
                "created_at": now,
                "updated_at": now,
            }
            self._rows = [
                existing
                for existing in self._rows
                if not (
                    existing.get("app_id") == app_id
                    and existing.get("connector_id") == connector_id
                )
            ]
            self._rows.append(row)
        return {"success": True}


def test_activate_calendar_read_grant_upserts_exact_reviewed_grant() -> None:
    binding = MutableFakeD1Binding()
    store = CloudflareD1ConnectorGrantStore(binding)

    grant = run(
        store.activate_calendar_read_grant(
            binding_ref=BINDING_REF,
            actor_ref=ACTOR_REF,
        )
    )

    assert grant.app_id == CALENDAR_REFERENCE_APP_ID
    assert grant.canonical_agent_id == CALENDAR_AGENT_ID
    assert grant.binding_ref == BINDING_REF
    assert grant.actor_ref == ACTOR_REF
    assert grant.granted_capabilities == (CalendarCapability.READ,)
    assert "ON CONFLICT(app_id, connector_id) DO UPDATE" in binding.sqls[0]
    assert BINDING_REF not in binding.sqls[0]
    assert ACTOR_REF not in binding.sqls[0]


class SqliteD1Adapter:
    """Executes the store's real SQL on in-memory SQLite created by the real migrations.

    A hand-written double cannot prove that a conditional conflict clause behaves the way
    the storage engine will: only an actual SQL engine can. This adapter adds no behaviour
    of its own — it reports ``meta.changes`` the way a D1 ``run()`` does, and nothing else.
    """

    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:", check_same_thread=False)
        for migration in GRANT_MIGRATIONS:
            self.connection.executescript(
                (MIGRATIONS / migration).read_text(encoding="utf-8")
            )
        self.connection.commit()
        self.statements: list[str] = []
        self.gate = threading.Lock()

    def prepare(self, sql):
        # Like a real D1 prepared statement, each prepare() owns its own bound values, so
        # two concurrent activations cannot trample each other's parameters.
        return _SqliteStatement(self, sql)

    def snapshot(self):
        with self.gate:
            return self.connection.execute(
                "SELECT app_id, connector_id, binding_ref, actor_ref, active,"
                " created_at, updated_at FROM padiem_engine_connector_grants"
            ).fetchall()


class _SqliteStatement:
    def __init__(self, adapter: "SqliteD1Adapter", sql: str, params: tuple = ()) -> None:
        self._adapter = adapter
        self._sql = sql
        self._params = params

    def bind(self, *params):
        return _SqliteStatement(self._adapter, self._sql, params)

    def run(self):
        self._adapter.statements.append(self._sql)
        # A single database serialises its own write transactions. The gate models that so a
        # lost race is answered by the statement's own zero-change refusal instead of a
        # storage fault; it decides nothing, and the winner is still chosen inside the SQL.
        with self._adapter.gate:
            cursor = self._adapter.connection.execute(self._sql, self._params)
            self._adapter.connection.commit()
            return {"success": True, "meta": {"changes": cursor.rowcount}}

    def all(self):
        self._adapter.statements.append(self._sql)
        with self._adapter.gate:
            cursor = self._adapter.connection.execute(self._sql, self._params)
            columns = [column[0] for column in cursor.description]
            return {"results": [dict(zip(columns, row)) for row in cursor.fetchall()]}


def _activate(adapter, *, binding_ref: str, actor_ref: str):
    store = CloudflareD1ConnectorGrantStore(adapter)
    return run(store.activate_calendar_read_grant(
        binding_ref=binding_ref, actor_ref=actor_ref
    ))


def _activation_error(call, *, binding_ref: str, actor_ref: str):
    with pytest.raises(ServiceContractError) as exc_info:
        call(binding_ref=binding_ref, actor_ref=actor_ref)
    return exc_info.value


# --- the guard, against a real SQL engine ------------------------------------


def test_sqlite_first_activation_writes_the_canonical_grant() -> None:
    adapter = SqliteD1Adapter()
    grant = _activate(adapter, binding_ref=WS_ALPHA_BINDING, actor_ref=WS_ALPHA_ACTOR)

    assert grant.binding_ref == WS_ALPHA_BINDING
    assert grant.actor_ref == WS_ALPHA_ACTOR
    assert grant.granted_capabilities == (CalendarCapability.READ,)
    assert len(adapter.snapshot()) == 1


def test_sqlite_second_workspace_cannot_overwrite_the_first_holder() -> None:
    adapter = SqliteD1Adapter()
    _activate(adapter, binding_ref=WS_ALPHA_BINDING, actor_ref=WS_ALPHA_ACTOR)

    error = _activation_error(
        lambda **kwargs: _activate(adapter, **kwargs),
        binding_ref=WS_BETA_BINDING, actor_ref=WS_BETA_ACTOR,
    )
    assert error.code == _ACTIVATION_REFUSED_CODE
    assert error.status_code == 409

    rows = adapter.snapshot()
    assert len(rows) == 1, "a refusal must never add a second Calendar row"
    assert rows[0][2] == WS_ALPHA_BINDING and rows[0][3] == WS_ALPHA_ACTOR, (
        "the first holder's trusted references must survive a foreign activation"
    )
    grants = run(CloudflareD1ConnectorGrantStore(adapter).load_calendar_grants())
    assert grants[CALENDAR_REFERENCE_APP_ID].binding_ref == WS_ALPHA_BINDING


def test_sqlite_refusal_is_symmetric_for_either_arrival_order() -> None:
    for first, second in (
        ((WS_ALPHA_BINDING, WS_ALPHA_ACTOR), (WS_BETA_BINDING, WS_BETA_ACTOR)),
        ((WS_BETA_BINDING, WS_BETA_ACTOR), (WS_ALPHA_BINDING, WS_ALPHA_ACTOR)),
    ):
        adapter = SqliteD1Adapter()
        _activate(adapter, binding_ref=first[0], actor_ref=first[1])
        error = _activation_error(
            lambda **kwargs: _activate(adapter, **kwargs),
            binding_ref=second[0], actor_ref=second[1],
        )
        assert error.code == _ACTIVATION_REFUSED_CODE
        assert adapter.snapshot()[0][2] == first[0]


def test_sqlite_same_identity_reactivation_is_idempotent() -> None:
    adapter = SqliteD1Adapter()
    first = _activate(adapter, binding_ref=WS_ALPHA_BINDING, actor_ref=WS_ALPHA_ACTOR)
    first_row = adapter.snapshot()[0]

    second = _activate(adapter, binding_ref=WS_ALPHA_BINDING, actor_ref=WS_ALPHA_ACTOR)
    second_row = adapter.snapshot()[0]

    assert second == first
    assert len(adapter.snapshot()) == 1
    assert second_row[2] == WS_ALPHA_BINDING and second_row[3] == WS_ALPHA_ACTOR
    # created_at is the fifth-and-earlier columns: identity and creation time stay put.
    assert second_row[4] == 1
    assert second_row[5] == first_row[5], "a repeat activation must not rewind the slot"


def test_sqlite_two_first_writers_racing_leave_exactly_one_holder() -> None:
    """Simultaneous activation on an empty slot: the statement decides, not the ordering."""

    adapter = SqliteD1Adapter()
    barrier = threading.Barrier(2)
    outcomes: dict[str, object] = {}

    def compete(name: str, binding_ref: str, actor_ref: str) -> None:
        barrier.wait()
        try:
            grant = _activate(adapter, binding_ref=binding_ref, actor_ref=actor_ref)
            outcomes[name] = ("granted", grant.binding_ref)
        except ServiceContractError as exc:
            outcomes[name] = ("refused", exc.code)

    alpha = threading.Thread(target=compete, args=("alpha", WS_ALPHA_BINDING, WS_ALPHA_ACTOR))
    beta = threading.Thread(target=compete, args=("beta", WS_BETA_BINDING, WS_BETA_ACTOR))
    alpha.start()
    beta.start()
    alpha.join()
    beta.join()

    granted = [value for value in outcomes.values() if value[0] == "granted"]
    refused = [value for value in outcomes.values() if value[0] == "refused"]
    assert len(outcomes) == 2, "both activations must answer"
    assert len(granted) == 1, "exactly one first writer may take the slot"
    assert len(refused) == 1 and refused[0][1] == _ACTIVATION_REFUSED_CODE
    rows = adapter.snapshot()
    assert len(rows) == 1
    assert rows[0][2] == granted[0][1]


def test_guard_is_one_statement_and_never_reads_before_it_writes() -> None:
    adapter = SqliteD1Adapter()
    _activate(adapter, binding_ref=WS_ALPHA_BINDING, actor_ref=WS_ALPHA_ACTOR)

    write = adapter.statements[0]
    assert write.lstrip().startswith("INSERT INTO padiem_engine_connector_grants")
    assert write.count(";") == 0, "the decision must be one statement, not read-then-write"
    assert "ON CONFLICT(app_id, connector_id) DO UPDATE SET" in write
    assert "WHERE padiem_engine_connector_grants.binding_ref = excluded.binding_ref" in write
    assert "AND padiem_engine_connector_grants.actor_ref = excluded.actor_ref" in write
    assert WS_ALPHA_BINDING not in write, "identity travels only as a bound parameter"


def test_refusal_never_discloses_the_other_workspaces_identity() -> None:
    adapter = SqliteD1Adapter()
    _activate(adapter, binding_ref=WS_ALPHA_BINDING, actor_ref=WS_ALPHA_ACTOR)
    error = _activation_error(
        lambda **kwargs: _activate(adapter, **kwargs),
        binding_ref=WS_BETA_BINDING, actor_ref=WS_BETA_ACTOR,
    )
    projected = f"{error.code} {error} {getattr(error, 'message', '')}"
    for secret in (WS_ALPHA_BINDING, WS_ALPHA_ACTOR, WS_BETA_BINDING, WS_BETA_ACTOR):
        assert secret not in projected


# --- conservative fault handling --------------------------------------------


class LyingD1Binding(FakeD1Binding):
    """A double that reports success but never a row count.

    This is the case a hand-written fake can get wrong on purpose: with no ``changes``
    answer the store can only classify from the canonical read-back, so a double that also
    overwrites the row proves nothing about real conflict behaviour. The SQLite tests above
    are the storage-engine proof; this one only pins the conservative fallback.
    """

    def run(self):
        params = self.params[-1]
        app_id, agent_id, connector_id, binding_ref, actor_ref, scopes, caps, now, _ = params
        holder = next(
            (row for row in self._rows
             if row.get("app_id") == app_id and row.get("connector_id") == connector_id),
            None,
        )
        if holder is not None and (
            holder.get("binding_ref") != binding_ref or holder.get("actor_ref") != actor_ref
        ):
            # A real conditional conflict changes zero rows; a double that silently
            # clobbered would hide the very defect this guard exists to prevent.
            return {"success": True}
        self._rows = [
            row for row in self._rows
            if not (row.get("app_id") == app_id and row.get("connector_id") == connector_id)
        ]
        self._rows.append({
            "app_id": app_id,
            "canonical_agent_id": agent_id,
            "connector_id": connector_id,
            "binding_ref": binding_ref,
            "actor_ref": actor_ref,
            "granted_scopes_json": scopes,
            "granted_capabilities_json": caps,
            "active": 1,
            "created_at": now,
            "updated_at": now,
        })
        return {"success": True}


class ZeroChangeD1Binding(MutableFakeD1Binding):
    """Reports `meta.changes = 0` the way D1 does when the conflict clause refuses a write."""

    def run(self):
        params = self.params[-1]
        app_id, _agent, connector_id, binding_ref, actor_ref, _s, _c, _n, _u = params
        holder = next(
            (row for row in self._rows
             if row.get("app_id") == app_id and row.get("connector_id") == connector_id),
            None,
        )
        if holder is not None and (
            holder.get("binding_ref") != binding_ref or holder.get("actor_ref") != actor_ref
        ):
            return {"success": True, "meta": {"changes": 0}}
        return super().run()


def test_reported_zero_changes_refuses_without_touching_the_row() -> None:
    binding = ZeroChangeD1Binding(rows=[calendar_row()])
    with pytest.raises(ServiceContractError) as exc_info:
        run(CloudflareD1ConnectorGrantStore(binding).activate_calendar_read_grant(
            binding_ref=WS_BETA_BINDING, actor_ref=WS_BETA_ACTOR
        ))
    assert exc_info.value.code == _ACTIVATION_REFUSED_CODE
    assert binding._rows[0]["binding_ref"] == BINDING_REF


def test_unknown_row_count_falls_back_to_the_canonical_readback() -> None:
    """No row count is not permission: a foreign holder is refused, ours still succeeds."""

    foreign = LyingD1Binding(rows=[calendar_row()])
    with pytest.raises(ServiceContractError) as exc_info:
        run(CloudflareD1ConnectorGrantStore(foreign).activate_calendar_read_grant(
            binding_ref=WS_BETA_BINDING, actor_ref=WS_BETA_ACTOR
        ))
    assert exc_info.value.code == _ACTIVATION_REFUSED_CODE

    ours = LyingD1Binding(rows=[calendar_row()])
    grant = run(CloudflareD1ConnectorGrantStore(ours).activate_calendar_read_grant(
        binding_ref=BINDING_REF, actor_ref=ACTOR_REF
    ))
    assert grant.binding_ref == BINDING_REF
    assert grant.actor_ref == ACTOR_REF


def test_genuine_storage_fault_stays_unavailable_not_refused() -> None:
    store = CloudflareD1ConnectorGrantStore(FakeD1Binding(fail=True))
    with pytest.raises(ServiceContractError) as exc_info:
        run(store.activate_calendar_read_grant(
            binding_ref=WS_BETA_BINDING, actor_ref=WS_BETA_ACTOR
        ))
    assert exc_info.value.code == "calendar_grant_activation_unavailable"
    assert exc_info.value.status_code == 503


# --- the fault path belongs to this route, not to whatever the adapter raised ----


class ForwardingFaultD1Binding(MutableFakeD1Binding):
    """A binding that raises a ServiceContractError of its own while writing.

    The adapter picks that code and message, so they may not be repeated to the caller:
    an exception that merely looks like a safe service error is still outside this contract.
    """

    def run(self):
        raise ServiceContractError(
            "adapter_internal_code",
            f"adapter detail {WS_ALPHA_BINDING} {WS_ALPHA_ACTOR}",
            status_code=400,
        )


def test_binding_service_contract_fault_is_normalised_and_never_forwarded() -> None:
    binding = ForwardingFaultD1Binding(rows=[calendar_row()])
    with pytest.raises(ServiceContractError) as exc_info:
        run(CloudflareD1ConnectorGrantStore(binding).activate_calendar_read_grant(
            binding_ref=WS_BETA_BINDING, actor_ref=WS_BETA_ACTOR
        ))
    error = exc_info.value
    assert error.code == "calendar_grant_activation_unavailable"
    assert error.status_code == 503
    projected = f"{error.code} {error} {error.safe_message}"
    for foreign in (
        "adapter_internal_code",
        "adapter detail",
        WS_ALPHA_BINDING,
        WS_ALPHA_ACTOR,
        WS_BETA_BINDING,
        WS_BETA_ACTOR,
    ):
        assert foreign not in projected, "an adapter's own error must not reach the caller"
    assert binding._rows[0]["binding_ref"] == BINDING_REF


class FailedWriteD1Binding(MutableFakeD1Binding):
    """Reports the statement failed while still claiming it changed a row."""

    def run(self):
        return {"success": False, "meta": {"changes": 1}}


def test_failed_write_on_the_same_identity_is_never_a_success() -> None:
    # The stored row already matches the caller, so a store that only reads the row count
    # would call this a completed activation.
    binding = FailedWriteD1Binding(rows=[calendar_row()])
    with pytest.raises(ServiceContractError) as exc_info:
        run(CloudflareD1ConnectorGrantStore(binding).activate_calendar_read_grant(
            binding_ref=BINDING_REF, actor_ref=ACTOR_REF
        ))
    assert exc_info.value.code == "calendar_grant_activation_unavailable"
    assert exc_info.value.status_code == 503
    assert len(binding._rows) == 1
    assert binding._rows[0]["binding_ref"] == BINDING_REF


class FlaglessD1Binding(MutableFakeD1Binding):
    """A result shape that carries no success flag at all."""

    def run(self):
        super().run()
        return {"meta": {"changes": 1}}


def test_absent_success_flag_is_not_read_as_a_failure() -> None:
    binding = FlaglessD1Binding()
    grant = run(CloudflareD1ConnectorGrantStore(binding).activate_calendar_read_grant(
        binding_ref=BINDING_REF, actor_ref=ACTOR_REF
    ))
    assert grant.binding_ref == BINDING_REF
    assert grant.actor_ref == ACTOR_REF


# --- the guard is Calendar-only; unrelated connector behaviour is intact -----


def test_other_connector_loads_are_unaffected_by_the_calendar_guard() -> None:
    for rows, code in (
        ([calendar_row()], "padiem_engine_connector_grants"),
        ([], "padiem_engine_connector_grants"),
    ):
        binding = FakeD1Binding(rows=rows)
        grants = run(CloudflareD1ConnectorGrantStore(binding).load_calendar_grants())
        assert code in binding.sqls[0]
        assert list(grants) == ([CALENDAR_REFERENCE_APP_ID] if rows else [])


def test_gmail_grant_loading_still_uses_its_own_column_and_filter() -> None:
    from app.connector_bindings import GMAIL_CONNECTOR_ID

    binding = FakeD1Binding(rows=[])
    run(CloudflareD1ConnectorGrantStore(binding).load_gmail_grants())
    assert "granted_scopes_json" in binding.sqls[0]
    assert binding.params[0] == (GMAIL_CONNECTOR_ID,)
