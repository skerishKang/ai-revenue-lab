"""D1 Calendar grant store tests (#2358).

Reuses the existing ``padiem_engine_connector_grants`` table and the
``granted_capabilities_json`` column — no schema migration is introduced.
Network-free: a fake D1 binding records SQL and returns canned rows.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from padiem_ai_core.calendar_capability import CALENDAR_CONNECTOR_ID, CalendarCapability
from app.connector_bindings import CALENDAR_AGENT_ID, CALENDAR_REFERENCE_APP_ID
from app.connector_grants_d1 import CloudflareD1ConnectorGrantStore
from app.service import ServiceContractError

BINDING_REF = "bind:calendar_engine"
ACTOR_REF = "actor_1"


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
