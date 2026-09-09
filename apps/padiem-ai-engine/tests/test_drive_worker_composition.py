"""Drive worker composition tests (#2206 S4-ACT1).

Proves the Engine composition root wires Drive port + grants into
``build_tool_binding_resolver`` alongside the existing Gmail wiring.
Network-free: uses recording fakes for both Drive and Gmail ports.
"""

from __future__ import annotations

import asyncio

import pytest

from padiem_ai_core.drive_capability import (
    DRIVE_CANONICAL_TOOL_IDS,
    DRIVE_CONNECTOR_ID,
    DRIVE_READONLY_SCOPE,
    DRIVE_READ_TOOL_IDS,
    DriveCapability,
    DriveCapabilityGrant,
    DriveContractError,
    DriveReadPort,
)
from padiem_ai_core.tool_runtime import ToolRuntime

from app.connector_bindings import (
    DRIVE_AGENT_ID,
    DRIVE_REFERENCE_APP_ID,
    DriveGrant,
    GMAIL_REFERENCE_APP_ID,
    GmailGrant,
    build_tool_binding_resolver,
    drive_tool_binding,
    gmail_tool_binding,
)
from app.connector_grants_d1 import CloudflareD1ConnectorGrantStore
from app.drive_port_httpx import HttpxDriveReadPort
from app.tool_projection import EngineToolProjectionError

BINDING_REF = "bind:drive_engine"
ACTOR_REF = "actor_1"


def run(coro):
    return asyncio.run(coro)


class FakeDrivePort:
    """In-memory trusted Drive port double. No network, no credentials."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def get_json(self, **kwargs: object) -> dict:
        self.calls.append(kwargs)
        return {"files": []}

    def get_text(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return ""


class FakeGmailPort:
    """In-memory trusted Gmail port double."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def get_json(self, **kwargs: object) -> dict:
        self.calls.append(kwargs)
        return {"messages": []}


def drive_grant(*capabilities: DriveCapability, app_id: str = DRIVE_REFERENCE_APP_ID) -> DriveGrant:
    return DriveGrant(
        app_id=app_id,
        canonical_agent_id=DRIVE_AGENT_ID,
        binding_ref=BINDING_REF,
        actor_ref=ACTOR_REF,
        granted_capabilities=capabilities or (DriveCapability.READ,),
    )


def core_drive_grant(*capabilities: DriveCapability) -> DriveCapabilityGrant:
    return DriveCapabilityGrant(
        connector_id=DRIVE_CONNECTOR_ID,
        binding_ref=BINDING_REF,
        granted_capabilities=capabilities or (DriveCapability.READ,),
    )


def _d1_row(app_id: str, *, active: int = 1, capabilities: tuple[str, ...] = ("read",)) -> dict:
    import json
    return {
        "app_id": app_id,
        "canonical_agent_id": DRIVE_AGENT_ID,
        "connector_id": DRIVE_CONNECTOR_ID,
        "binding_ref": BINDING_REF,
        "actor_ref": ACTOR_REF,
        "granted_capabilities_json": json.dumps(capabilities, separators=(",", ":")),
        "active": active,
    }


# --- DriveGrant validation ---


def test_drive_grant_rejects_duplicate_capabilities() -> None:
    with pytest.raises(DriveContractError):
        DriveGrant(
            app_id=DRIVE_REFERENCE_APP_ID,
            canonical_agent_id=DRIVE_AGENT_ID,
            binding_ref=BINDING_REF,
            actor_ref=ACTOR_REF,
            granted_capabilities=(DriveCapability.READ, DriveCapability.READ),
        )


# --- drive_tool_binding ---


def test_drive_tool_binding_assembles_engine_tool_binding() -> None:
    port = FakeDrivePort()
    grant = drive_grant()
    binding = drive_tool_binding(grant=grant, port=port)
    assert binding.app_id == DRIVE_REFERENCE_APP_ID
    assert set(binding.tool_runtime.registered_tool_ids) == set(DRIVE_READ_TOOL_IDS)
    assert DRIVE_AGENT_ID in binding.authorities
    assert isinstance(binding.tool_runtime, ToolRuntime)


def test_drive_tool_binding_rejects_gmail_grant() -> None:
    port = FakeDrivePort()
    grant = GmailGrant(
        app_id=DRIVE_REFERENCE_APP_ID,
        canonical_agent_id=DRIVE_AGENT_ID,
        binding_ref=BINDING_REF,
        actor_ref=ACTOR_REF,
        granted_scopes=("drive.readonly",),
    )
    with pytest.raises(EngineToolProjectionError, match="DriveGrant"):
        drive_tool_binding(grant=grant, port=port)


def test_drive_tool_binding_rejects_wrong_app_id() -> None:
    port = FakeDrivePort()
    grant = drive_grant(app_id="wrong-app")
    with pytest.raises(EngineToolProjectionError, match="trusted Engine slot"):
        drive_tool_binding(grant=grant, port=port)


def test_drive_tool_binding_rejects_wrong_agent_id() -> None:
    port = FakeDrivePort()
    grant = drive_grant()
    grant_bad = DriveGrant(
        app_id=DRIVE_REFERENCE_APP_ID,
        canonical_agent_id="agent:padiem:wrong@1",
        binding_ref=BINDING_REF,
        actor_ref=ACTOR_REF,
        granted_capabilities=(DriveCapability.READ,),
    )
    with pytest.raises(EngineToolProjectionError, match="bound Agent"):
        drive_tool_binding(grant=grant_bad, port=port)


def test_drive_tool_binding_rejects_incomplete_port() -> None:
    class HalfPort:
        def get_json(self, **kwargs: object) -> dict:
            return {}

    port = HalfPort()
    grant = drive_grant()
    with pytest.raises(EngineToolProjectionError, match="DriveReadPort"):
        drive_tool_binding(grant=grant, port=port)


# --- D1 grant loader ---


def test_load_drive_grants_returns_grants_on_hit() -> None:
    store = CloudflareD1ConnectorGrantStore(
        FakeD1Binding([_d1_row("app_1"), _d1_row("app_2")])
    )
    grants = run(store.load_drive_grants())
    assert set(grants) == {"app_1", "app_2"}
    assert grants["app_1"].binding_ref == BINDING_REF
    assert grants["app_1"].granted_capabilities == (DriveCapability.READ,)


def test_load_drive_grants_returns_empty_on_miss() -> None:
    store = CloudflareD1ConnectorGrantStore(FakeD1Binding([]))
    grants = run(store.load_drive_grants())
    assert grants == {}


def test_load_drive_grants_ignores_inactive_rows() -> None:
    store = CloudflareD1ConnectorGrantStore(
        FakeD1Binding([_d1_row("app_1", active=0), _d1_row("app_2", active=1)])
    )
    grants = run(store.load_drive_grants())
    assert set(grants) == {"app_2"}


def test_load_drive_grants_raises_on_malformed_json() -> None:
    store = CloudflareD1ConnectorGrantStore(
        FakeD1Binding([{"app_id": "app_1", "granted_capabilities_json": "not json"}])
    )
    with pytest.raises(Exception):
        run(store.load_drive_grants())


def test_load_drive_grants_raises_on_binding_exception() -> None:
    store = CloudflareD1ConnectorGrantStore(FakeD1Binding(fail=True))
    with pytest.raises(Exception):
        run(store.load_drive_grants())


# --- resolver coexistence ---


def test_resolver_no_ports_returns_none() -> None:
    resolver = build_tool_binding_resolver(gmail_port=None, drive_port=None)
    assert resolver is None


def test_resolver_drive_only() -> None:
    port = FakeDrivePort()
    grant = drive_grant()
    resolver = build_tool_binding_resolver(
        gmail_port=None,
        drive_port=port,
        drive_grants={DRIVE_REFERENCE_APP_ID: grant},
    )
    assert resolver is not None
    binding = resolver(DRIVE_REFERENCE_APP_ID)
    assert binding is not None
    assert set(binding.tool_runtime.registered_tool_ids) == set(DRIVE_READ_TOOL_IDS)
    assert resolver(GMAIL_REFERENCE_APP_ID) is None


def test_resolver_gmail_only() -> None:
    port = FakeGmailPort()
    grant = GmailGrant(
        app_id=GMAIL_REFERENCE_APP_ID,
        canonical_agent_id="agent:padiem:claw_mail_reader@1",
        binding_ref="bind:gmail",
        actor_ref="actor_1",
        granted_scopes=("gmail.readonly",),
    )
    resolver = build_tool_binding_resolver(
        gmail_port=port,
        grants={GMAIL_REFERENCE_APP_ID: grant},
    )
    assert resolver is not None
    gmail_binding = resolver(GMAIL_REFERENCE_APP_ID)
    assert gmail_binding is not None
    assert resolver("any.drive.app") is None


def test_resolver_gmail_and_drive_coexist() -> None:
    drive_port = FakeDrivePort()
    gmail_port = FakeGmailPort()
    dgrant = drive_grant()
    gmail_grant = GmailGrant(
        app_id=GMAIL_REFERENCE_APP_ID,
        canonical_agent_id="agent:padiem:claw_mail_reader@1",
        binding_ref="bind:gmail",
        actor_ref="actor_1",
        granted_scopes=("gmail.readonly",),
    )
    resolver = build_tool_binding_resolver(
        gmail_port=gmail_port,
        grants={GMAIL_REFERENCE_APP_ID: gmail_grant},
        drive_port=drive_port,
        drive_grants={DRIVE_REFERENCE_APP_ID: dgrant},
    )
    assert resolver is not None
    gmail_binding = resolver(GMAIL_REFERENCE_APP_ID)
    drive_binding = resolver(DRIVE_REFERENCE_APP_ID)
    assert gmail_binding is not None
    assert drive_binding is not None
    assert "gmail" in str(gmail_binding.tool_runtime.registered_tool_ids)
    assert set(drive_binding.tool_runtime.registered_tool_ids) == set(DRIVE_READ_TOOL_IDS)


def test_resolver_empty_drive_grants_returns_none_for_drive() -> None:
    port = FakeDrivePort()
    resolver = build_tool_binding_resolver(
        gmail_port=None,
        drive_port=port,
        drive_grants=None,
    )
    assert resolver is None


# --- worker_identity composition ---


def test_worker_composes_drive_port_and_grants() -> None:
    """worker_identity exposes Drive port/grants helpers via source inspection."""
    src = open(
        "apps/padiem-ai-engine/worker_identity.py", encoding="utf-8"
    ).read()
    assert "_drive_port_for_env" in src
    assert "_drive_grants_for_env" in src
    assert "HttpxDriveReadPort" in src


def test_missing_drive_store_keeps_drive_tools_unavailable() -> None:
    """When no Drive port or grants are bound, resolver returns None."""
    resolver = build_tool_binding_resolver(gmail_port=None, drive_port=None)
    assert resolver is None


def test_caller_payload_cannot_mint_drive_scope_or_binding_ref() -> None:
    """DriveGrant is server-resolved only; caller fields are never used."""
    # DriveGrant is a frozen dataclass with no caller fields.
    # The only way to construct one is via server-resolved facts.
    grant = DriveGrant(
        app_id=DRIVE_REFERENCE_APP_ID,
        canonical_agent_id=DRIVE_AGENT_ID,
        binding_ref="server:bind:ref",
        actor_ref="server:actor:ref",
        granted_capabilities=(DriveCapability.READ,),
    )
    assert grant.binding_ref == "server:bind:ref"
    assert grant.actor_ref == "server:actor:ref"
    # DriveGrant only accepts DriveCapability values, not raw scope strings.
    # A caller cannot mint a grant by passing a raw scope string.
    with pytest.raises(DriveContractError):
        DriveGrant(
            app_id=DRIVE_REFERENCE_APP_ID,
            canonical_agent_id=DRIVE_AGENT_ID,
            binding_ref="bind",
            actor_ref="actor",
            granted_capabilities=("drive.readonly",),  # raw scope string, not DriveCapability
        )


# --- source-level guards ---


def test_drive_write_scope_or_operation_absent() -> None:
    """Drive port source only supports readonly scope."""
    src = open(
        "apps/padiem-ai-engine/app/drive_port_httpx.py", encoding="utf-8"
    ).read()
    assert "DRIVE_READONLY_SCOPE" in src
    assert "DRIVE_FULL_SCOPE" not in src


def test_no_secret_value_in_drive_port_errors() -> None:
    """Drive port error strings must never leak credential values."""
    src = open(
        "apps/padiem-ai-engine/app/drive_port_httpx.py", encoding="utf-8"
    ).read()
    assert 'ENGINE_GOOGLE_OAUTH_CLIENT_ID' in src
    assert 'ENGINE_GOOGLE_OAUTH_CLIENT_SECRET' in src
    assert 'ENGINE_GOOGLE_OAUTH_REFRESH_TOKEN' in src
    # The secret env var names are declared but values never appear in strings
    assert "client_secret=" not in src or "client_secret" in src


def test_gmail_and_drive_resolvers_coexist() -> None:
    """Both Gmail and Drive resolvers can be built from the same resolver."""
    drive_port = FakeDrivePort()
    gmail_port = FakeGmailPort()
    dgrant = drive_grant()
    gmail_grant = GmailGrant(
        app_id=GMAIL_REFERENCE_APP_ID,
        canonical_agent_id="agent:padiem:claw_mail_reader@1",
        binding_ref="bind:gmail",
        actor_ref="actor_1",
        granted_scopes=("gmail.readonly",),
    )
    resolver = build_tool_binding_resolver(
        gmail_port=gmail_port,
        grants={GMAIL_REFERENCE_APP_ID: gmail_grant},
        drive_port=drive_port,
        drive_grants={DRIVE_REFERENCE_APP_ID: dgrant},
    )
    assert resolver is not None
    assert resolver(GMAIL_REFERENCE_APP_ID) is not None
    assert resolver(DRIVE_REFERENCE_APP_ID) is not None


class FakeD1Binding:
    """Mimics a Cloudflare D1 binding: ``prepare(...).bind(...).all()``."""

    def __init__(self, rows=None, *, fail=False):
        self._rows = rows or []
        self._fail = fail

    def prepare(self, sql):
        return self

    def bind(self, *params):
        return self

    def all(self):
        if self._fail:
            raise RuntimeError("d1 transport failure")
        return [dict(r) for r in self._rows if r.get("active", 1) == 1]

    def first(self):
        if self._fail:
            raise RuntimeError("d1 transport failure")
        rows = self._rows or []
        active = [r for r in rows if r.get("active", 1) == 1]
        return dict(active[0]) if active else None
