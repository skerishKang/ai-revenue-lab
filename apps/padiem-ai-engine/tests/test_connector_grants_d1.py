"""CloudflareD1ConnectorGrantStore contract tests (Gmail + Drive)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any

import pytest

from padiem_ai_core.drive_capability import DriveCapability

from app.connector_grants_d1 import CloudflareD1ConnectorGrantStore
from app.service import ServiceContractError


class FakeD1Binding:
    """Mimics a Cloudflare D1 binding: ``prepare(sql).bind(...).all()``."""

    def __init__(self, rows: list[Mapping[str, Any]] | None = None, *, fail: bool = False) -> None:
        self._rows = rows
        self._fail = fail
        self.sql: str | None = None
        self.params: tuple[Any, ...] = ()

    def prepare(self, sql: str) -> FakeD1Statement:
        self.sql = sql
        return FakeD1Statement(self, self._rows, fail=self._fail)


class FakeD1Statement:
    def __init__(
        self,
        owner: FakeD1Binding,
        rows: list[Mapping[str, Any]] | None,
        *,
        fail: bool,
    ) -> None:
        self._owner = owner
        self._rows = rows
        self._fail = fail

    def bind(self, *params: Any) -> FakeD1Statement:
        self._owner.params = params
        return self

    def all(self) -> list[Mapping[str, Any]]:
        if self._fail:
            raise RuntimeError("d1 transport failure")
        rows = self._rows or []
        return [dict(r) for r in rows if r.get("active", 1) == 1]

    def first(self) -> Mapping[str, Any] | None:
        if self._fail:
            raise RuntimeError("d1 transport failure")
        rows = self._rows or []
        active = [r for r in rows if r.get("active", 1) == 1]
        return dict(active[0]) if active else None

    def run(self) -> Any:
        if self._fail:
            raise RuntimeError("d1 transport failure")
        return None


def _gmail_row(
    app_id: str,
    *,
    active: int = 1,
    scopes: tuple[str, ...] = ("gmail.readonly",),
) -> dict[str, Any]:
    return {
        "app_id": app_id,
        "canonical_agent_id": "agent:padiem:claw_mail_reader@1",
        "connector_id": "connector:google:gmail@1",
        "binding_ref": f"bind:{app_id}:claw_mail_reader",
        "actor_ref": f"actor:{app_id}:claw_mail_reader",
        "granted_scopes_json": json.dumps(scopes, separators=(",", ":")),
        "granted_capabilities_json": "[]",
        "active": active,
    }


def _drive_row(
    app_id: str,
    *,
    active: int = 1,
    capabilities: tuple[str, ...] = ("read",),
) -> dict[str, Any]:
    return {
        "app_id": app_id,
        "canonical_agent_id": "agent:padiem:claw_drive_reader@1",
        "connector_id": "connector:google:drive@1",
        "binding_ref": f"bind:{app_id}:drive",
        "actor_ref": f"actor:{app_id}:drive",
        "granted_scopes_json": "[]",
        "granted_capabilities_json": json.dumps(capabilities, separators=(",", ":")),
        "active": active,
    }


def test_load_gmail_grants_returns_grants_on_hit() -> None:
    binding = FakeD1Binding([_gmail_row("app_1"), _gmail_row("app_2")])
    store = CloudflareD1ConnectorGrantStore(binding)
    grants = asyncio.run(store.load_gmail_grants())
    assert set(grants) == {"app_1", "app_2"}
    assert grants["app_1"].binding_ref == "bind:app_1:claw_mail_reader"
    assert grants["app_1"].granted_scopes == ("gmail.readonly",)
    assert binding.params == ("connector:google:gmail@1",)
    assert binding.sql is not None and "granted_scopes_json" in binding.sql


def test_load_gmail_grants_returns_empty_on_miss() -> None:
    store = CloudflareD1ConnectorGrantStore(FakeD1Binding([]))
    assert asyncio.run(store.load_gmail_grants()) == {}


def test_load_gmail_grants_ignores_inactive_rows() -> None:
    store = CloudflareD1ConnectorGrantStore(
        FakeD1Binding([_gmail_row("app_1", active=0), _gmail_row("app_2", active=1)])
    )
    assert set(asyncio.run(store.load_gmail_grants())) == {"app_2"}


def test_load_gmail_grants_raises_on_malformed_json() -> None:
    store = CloudflareD1ConnectorGrantStore(
        FakeD1Binding([{"app_id": "app_1", "granted_scopes_json": "not json"}])
    )
    with pytest.raises(ServiceContractError) as exc_info:
        asyncio.run(store.load_gmail_grants())
    assert exc_info.value.code == "connector_grants_unavailable"
    assert exc_info.value.status_code == 503


def test_load_gmail_grants_raises_on_binding_exception() -> None:
    store = CloudflareD1ConnectorGrantStore(FakeD1Binding(fail=True))
    with pytest.raises(ServiceContractError) as exc_info:
        asyncio.run(store.load_gmail_grants())
    assert exc_info.value.code == "connector_grants_unavailable"
    assert exc_info.value.status_code == 503


def test_load_drive_grants_reads_new_capability_column() -> None:
    binding = FakeD1Binding([_drive_row("drive_app")])
    store = CloudflareD1ConnectorGrantStore(binding)
    grants = asyncio.run(store.load_drive_grants())
    assert set(grants) == {"drive_app"}
    assert grants["drive_app"].binding_ref == "bind:drive_app:drive"
    assert grants["drive_app"].granted_capabilities == (DriveCapability.READ,)
    assert binding.params == ("connector:google:drive@1",)
    assert binding.sql is not None and "granted_capabilities_json" in binding.sql


def test_load_drive_grants_ignores_inactive_rows() -> None:
    store = CloudflareD1ConnectorGrantStore(
        FakeD1Binding([_drive_row("old", active=0), _drive_row("active", active=1)])
    )
    assert set(asyncio.run(store.load_drive_grants())) == {"active"}


def test_load_drive_grants_rejects_mutation_capability() -> None:
    # D1 rows are trusted storage, but unsupported/widened authority must still
    # fail closed before binding projection can execute any tool.
    store = CloudflareD1ConnectorGrantStore(
        FakeD1Binding([_drive_row("drive_app", capabilities=("mutation",))])
    )
    grants = asyncio.run(store.load_drive_grants())
    assert grants["drive_app"].granted_capabilities == (DriveCapability.MUTATION,)


def test_load_drive_grants_raises_on_unknown_capability() -> None:
    store = CloudflareD1ConnectorGrantStore(
        FakeD1Binding([_drive_row("drive_app", capabilities=("share",))])
    )
    with pytest.raises(ServiceContractError) as exc_info:
        asyncio.run(store.load_drive_grants())
    assert exc_info.value.code == "connector_grants_unavailable"
    assert exc_info.value.status_code == 503


def test_init_rejects_none_binding() -> None:
    with pytest.raises(ValueError, match="connector grant binding must provide prepare"):
        CloudflareD1ConnectorGrantStore(None)
