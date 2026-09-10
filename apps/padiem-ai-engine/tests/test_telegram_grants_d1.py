"""D1 Telegram grant store tests (#2353).

Reuses the existing ``padiem_engine_connector_grants`` table and the
``granted_capabilities_json`` column — no schema migration is introduced.
Network-free: a fake D1 binding records SQL and returns canned rows.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from padiem_ai_core.telegram_capability import TELEGRAM_CONNECTOR_ID, TelegramCapability
from app.connector_bindings import TELEGRAM_AGENT_ID, TELEGRAM_REFERENCE_APP_ID
from app.connector_grants_d1 import CloudflareD1ConnectorGrantStore
from app.service import ServiceContractError

BINDING_REF = "bind:telegram_engine"
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


def telegram_row(**overrides):
    row = {
        "app_id": TELEGRAM_REFERENCE_APP_ID,
        "canonical_agent_id": TELEGRAM_AGENT_ID,
        "connector_id": TELEGRAM_CONNECTOR_ID,
        "binding_ref": BINDING_REF,
        "actor_ref": ACTOR_REF,
        "granted_capabilities_json": json.dumps(["read"]),
        "active": 1,
    }
    row.update(overrides)
    return row


def test_load_telegram_grants_returns_grants_on_hit() -> None:
    binding = FakeD1Binding(rows=[telegram_row()])
    store = CloudflareD1ConnectorGrantStore(binding)
    grants = run(store.load_telegram_grants())
    assert list(grants) == [TELEGRAM_REFERENCE_APP_ID]
    grant = grants[TELEGRAM_REFERENCE_APP_ID]
    assert grant.granted_capabilities == (TelegramCapability.READ,)
    assert grant.binding_ref == BINDING_REF
    # Reuses the existing table/columns: no new schema surface.
    assert "padiem_engine_connector_grants" in binding.sqls[0]
    assert "granted_capabilities_json" in binding.sqls[0]
    assert binding.params[0] == (TELEGRAM_CONNECTOR_ID,)


def test_load_telegram_grants_returns_empty_on_miss() -> None:
    store = CloudflareD1ConnectorGrantStore(FakeD1Binding(rows=[]))
    assert run(store.load_telegram_grants()) == {}


def test_load_telegram_grants_ignores_inactive_rows() -> None:
    store = CloudflareD1ConnectorGrantStore(FakeD1Binding(rows=[telegram_row(active=0)]))
    assert run(store.load_telegram_grants()) == {}


def test_load_telegram_grants_rejects_write_capabilities() -> None:
    for capabilities in (["send_message"], ["read", "send_message"], ["send"]):
        store = CloudflareD1ConnectorGrantStore(
            FakeD1Binding(rows=[telegram_row(granted_capabilities_json=json.dumps(capabilities))])
        )
        with pytest.raises(ServiceContractError) as exc_info:
            run(store.load_telegram_grants())
        assert exc_info.value.code == "connector_grants_unavailable"


def test_load_telegram_grants_raises_on_malformed_json() -> None:
    store = CloudflareD1ConnectorGrantStore(
        FakeD1Binding(rows=[telegram_row(granted_capabilities_json="{oops")])
    )
    with pytest.raises(ServiceContractError):
        run(store.load_telegram_grants())


def test_load_telegram_grants_raises_on_binding_exception() -> None:
    store = CloudflareD1ConnectorGrantStore(FakeD1Binding(fail=True))
    with pytest.raises(ServiceContractError) as exc_info:
        run(store.load_telegram_grants())
    assert exc_info.value.code == "connector_grants_unavailable"
