"""WO-10 PR-C2 commit 2: CloudflareD1ConnectorGrantStore contract tests (D28).

All tests use a hand-rolled mock that mirrors the D1 ``prepare(...).bind(...)
.first() / .all() / .run()`` call chain so no real D1 database is touched.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any

import pytest

from app.connector_grants_d1 import CloudflareD1ConnectorGrantStore
from app.service import ServiceContractError


class FakeD1Binding:
    """Mimics a Cloudflare D1 binding: ``prepare(sql).bind(...).all()``."""

    def __init__(self, rows: list[Mapping[str, Any]] | None = None, *, fail: bool = False) -> None:
        self._rows = rows
        self._fail = fail

    def prepare(self, sql: str) -> FakeD1Statement:
        return FakeD1Statement(self._rows, fail=self._fail)


class FakeD1Statement:
    def __init__(self, rows: list[Mapping[str, Any]] | None, *, fail: bool) -> None:
        self._rows = rows
        self._fail = fail

    def bind(self, *params: Any) -> FakeD1Statement:
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


def _row(app_id: str, *, active: int = 1, scopes: tuple[str, ...] = ("gmail.readonly",)) -> dict[str, Any]:
    return {
        "app_id": app_id,
        "canonical_agent_id": "agent:padiem:claw_mail_reader@1",
        "connector_id": "connector:google:gmail@1",
        "binding_ref": f"bind:{app_id}:claw_mail_reader",
        "actor_ref": f"actor:{app_id}:claw_mail_reader",
        "granted_scopes_json": json.dumps(scopes, separators=(",", ":")),
        "active": active,
    }


def test_load_gmail_grants_returns_grants_on_hit() -> None:
    store = CloudflareD1ConnectorGrantStore(
        FakeD1Binding([_row("app_1"), _row("app_2")])
    )
    grants = asyncio.run(store.load_gmail_grants())
    assert set(grants) == {"app_1", "app_2"}
    assert grants["app_1"].binding_ref == "bind:app_1:claw_mail_reader"
    assert grants["app_1"].granted_scopes == ("gmail.readonly",)


def test_load_gmail_grants_returns_empty_on_miss() -> None:
    store = CloudflareD1ConnectorGrantStore(FakeD1Binding([]))
    grants = asyncio.run(store.load_gmail_grants())
    assert grants == {}


def test_load_gmail_grants_ignores_inactive_rows() -> None:
    store = CloudflareD1ConnectorGrantStore(
        FakeD1Binding([_row("app_1", active=0), _row("app_2", active=1)])
    )
    grants = asyncio.run(store.load_gmail_grants())
    assert set(grants) == {"app_2"}


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


def test_init_rejects_none_binding() -> None:
    with pytest.raises(ValueError, match="connector grant binding must provide prepare"):
        CloudflareD1ConnectorGrantStore(None)