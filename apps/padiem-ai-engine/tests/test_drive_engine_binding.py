"""Engine Drive trusted port + tool_runtime binding projection tests (#2186 S3).

Network-free. Stubs the Core ``DriveReadPort`` boundary with a recording
fake so the Engine binding seam is exercised end-to-end without a real
Google OAuth client or HTTP client. Gmail and Drive resolvers coexist.
"""

from __future__ import annotations

import asyncio

import pytest

from padiem_ai_core.drive_capability import (
    DRIVE_CANONICAL_TOOL_IDS,
    DRIVE_CONNECTOR_ID,
    DRIVE_READ_TOOL_IDS,
    DriveCapability,
    DriveCapabilityClassification,
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
    build_tool_binding_resolver,
    drive_tool_binding,
    gmail_tool_binding,
)
from app.drive_capability_projection import (
    DRIVE_ENGINE_CAPABILITY_PROJECTION_VERSION,
    classify_drive_tool_for_binding,
    project_drive_capability_facts,
)
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


def drive_grant(*capabilities: DriveCapability, app_id: str = DRIVE_REFERENCE_APP_ID) -> DriveGrant:
    return DriveGrant(
        app_id=app_id,
        canonical_agent_id=DRIVE_AGENT_ID,
        binding_ref=BINDING_REF,
        actor_ref=ACTOR_REF,
        granted_capabilities=capabilities or (DriveCapability.READ,),
    )


def core_drive_grant(*capabilities: DriveCapability) -> DriveCapabilityGrant:
    """Core-side grant for the projection seam (carries connector_id)."""

    return DriveCapabilityGrant(
        connector_id=DRIVE_CONNECTOR_ID,
        binding_ref=BINDING_REF,
        granted_capabilities=capabilities or (DriveCapability.READ,),
    )


# --- classification seam ---


def test_only_promoted_drive_read_tools_are_bindable() -> None:
    for tool_id in DRIVE_READ_TOOL_IDS:
        assert classify_drive_tool_for_binding(tool_id) is DriveCapabilityClassification.READ
    with pytest.raises(ValueError, match="write_or_material"):
        classify_drive_tool_for_binding("drive.upload_file")
    with pytest.raises(ValueError, match="write_or_material"):
        classify_drive_tool_for_binding("drive.create_folder")
    with pytest.raises(ValueError, match="unknown"):
        classify_drive_tool_for_binding("drive.future_tool")
    with pytest.raises(ValueError):
        classify_drive_tool_for_binding("not-a-tool-id!")


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
    from app.connector_bindings import GmailGrant

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


# --- resolver coexistence ---


def test_resolver_no_ports_returns_none() -> None:
    resolver = build_tool_binding_resolver(gmail_port=None, drive_port=None)
    assert resolver is None


def test_resolver_gmail_only() -> None:
    from app.connector_bindings import GmailGrant, gmail_tool_binding

    class FakeGmailPort:
        def get_json(self, **kwargs: object) -> dict:
            return {"messages": []}

    gmail_port = FakeGmailPort()
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
    )
    assert resolver is not None
    gmail_binding = resolver(GMAIL_REFERENCE_APP_ID)
    assert gmail_binding is not None
    assert resolver("any.drive.app") is None


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


def test_resolver_gmail_and_drive_coexist() -> None:
    from app.connector_bindings import GmailGrant

    class FakeGmailPort:
        def get_json(self, **kwargs: object) -> dict:
            return {"messages": []}

    gmail_port = FakeGmailPort()
    gmail_grant = GmailGrant(
        app_id=GMAIL_REFERENCE_APP_ID,
        canonical_agent_id="agent:padiem:claw_mail_reader@1",
        binding_ref="bind:gmail",
        actor_ref="actor_1",
        granted_scopes=("gmail.readonly",),
    )
    drive_port = FakeDrivePort()
    dgrant = drive_grant()
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


def test_resolver_empty_grants_returns_none() -> None:
    port = FakeDrivePort()
    resolver = build_tool_binding_resolver(
        gmail_port=None,
        drive_port=port,
        drive_grants=None,
    )
    assert resolver is None


# --- projection ---


def test_project_drive_capability_facts_is_bounded_and_credential_free() -> None:
    grant = core_drive_grant(DriveCapability.READ)
    projection = project_drive_capability_facts(grant)
    assert projection["projection_version"] == DRIVE_ENGINE_CAPABILITY_PROJECTION_VERSION
    assert projection["connector_id"] == DRIVE_CONNECTOR_ID
    assert projection["granted_capabilities"] == ["read"]
    assert projection["bindable_tool_ids"] == sorted(DRIVE_READ_TOOL_IDS)
    assert projection["draft_implies_send"] is False
    assert projection["mints_approval_authority"] is False
    assert projection["raw_credentials_present"] is False
    assert projection["oauth_token_present"] is False
    assert projection["live_provider_calls"] == 0
    assert projection["production_activation"] is False


def test_projection_rejects_non_read_tool_ids() -> None:
    grant = core_drive_grant(DriveCapability.READ)
    with pytest.raises(ValueError, match="drive_tool_not_bindable"):
        project_drive_capability_facts(grant, tool_ids=("drive.upload_file",))


def test_projection_rejects_non_drive_grant() -> None:
    from app.connector_bindings import GmailGrant

    grant = GmailGrant(
        app_id=GMAIL_REFERENCE_APP_ID,
        canonical_agent_id="agent:padiem:claw_mail_reader@1",
        binding_ref="bind:gmail",
        actor_ref="actor_1",
        granted_scopes=("gmail.readonly",),
    )
    with pytest.raises(ValueError, match="DriveCapabilityGrant"):
        project_drive_capability_facts(grant)  # type: ignore[arg-type]


def test_no_oauth_or_live_call_in_engine_source() -> None:
    import os as _os
    base = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    for rel in (
        "app/connector_bindings.py",
        "app/drive_capability_projection.py",
    ):
        src = open(f"{base}/{rel}", encoding="utf-8").read()
        for bad in (
            "import httpx",
            "import requests",
            "import socket",
            "urllib.request",
            "webbrowser",
            "refresh_token",
            "client_secret",
        ):
            assert bad not in src, f"{rel} contains forbidden: {bad}"
