"""Engine Telegram trusted binding entry tests (#2353).

Network-free. Stubs the Core ``TelegramReadPort`` boundary with a recording
fake. Proves the promoted Telegram connector rides the existing shared
resolver framework (no new connector framework) and that Gmail/Drive binding
behavior is unchanged.
"""

from __future__ import annotations

import asyncio

import pytest

from padiem_ai_core.drive_capability import DriveCapability
from padiem_ai_core.telegram_capability import (
    TELEGRAM_CANONICAL_TOOL_IDS,
    TELEGRAM_CONNECTOR_ID,
    TELEGRAM_GET_BOT_INFO_TOOL_ID,
    TELEGRAM_GET_CHAT_INFO_TOOL_ID,
    TELEGRAM_READONLY_AUTH_SCOPE,
    TELEGRAM_SEND_AUTH_SCOPE,
    TelegramCapability,
    TelegramContractError,
)
from app.connector_bindings import (
    DRIVE_REFERENCE_APP_ID,
    GMAIL_REFERENCE_APP_ID,
    TELEGRAM_AGENT_ID,
    TELEGRAM_REFERENCE_APP_ID,
    DriveGrant,
    GmailGrant,
    TelegramGrant,
    build_tool_binding_resolver,
    drive_tool_binding,
    gmail_tool_binding,
    telegram_tool_binding,
)
from app.tool_projection import (
    EngineToolBinding,
    EngineToolProjectionError,
    project_redacted_tool_output,
)

BINDING_REF = "bind:telegram_engine"
ACTOR_REF = "actor_1"


def run(coro):
    return asyncio.run(coro)


class FakeTelegramPort:
    """In-memory trusted Telegram port double. No network, no bot token."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def get_json(self, **kwargs: object) -> dict:
        self.calls.append(kwargs)
        return {"ok": True, "result": {"id": 123456, "username": "padiem_beta_bot", "first_name": "P", "is_bot": True}}


def telegram_grant(**overrides) -> TelegramGrant:
    values = {
        "app_id": TELEGRAM_REFERENCE_APP_ID,
        "canonical_agent_id": TELEGRAM_AGENT_ID,
        "binding_ref": BINDING_REF,
        "actor_ref": ACTOR_REF,
        "granted_capabilities": (TelegramCapability.READ,),
    }
    values.update(overrides)
    return TelegramGrant(**values)


# --- grant shape ---


def test_telegram_grant_rejects_duplicate_capabilities() -> None:
    with pytest.raises(TelegramContractError):
        telegram_grant(
            granted_capabilities=(TelegramCapability.READ, TelegramCapability.READ)
        )


def test_telegram_grant_rejects_non_capability_values() -> None:
    with pytest.raises(TelegramContractError):
        telegram_grant(granted_capabilities=("telegram.readonly",))  # type: ignore[arg-type]


def test_telegram_grant_rejects_write_capabilities() -> None:
    for capability in (
        TelegramCapability.SEND_MESSAGE,
        TelegramCapability.SEND_DOCUMENT,
        TelegramCapability.EDIT_MESSAGE,
        TelegramCapability.ANSWER_CALLBACK,
    ):
        with pytest.raises(TelegramContractError):
            telegram_grant(granted_capabilities=(TelegramCapability.READ, capability))


# --- binding assembly ---


def test_telegram_tool_binding_assembles_engine_tool_binding() -> None:
    port = FakeTelegramPort()
    binding = telegram_tool_binding(grant=telegram_grant(), port=port)
    assert isinstance(binding, EngineToolBinding)
    assert binding.app_id == TELEGRAM_REFERENCE_APP_ID
    assert binding.registry.canonical_tool_ids == TELEGRAM_CANONICAL_TOOL_IDS
    assert set(binding.authorities) == {TELEGRAM_AGENT_ID}


def test_telegram_tool_binding_registers_read_tools_only() -> None:
    port = FakeTelegramPort()
    binding = telegram_tool_binding(grant=telegram_grant(), port=port)
    assert binding.tool_runtime.registered_tool_ids == (
        TELEGRAM_GET_BOT_INFO_TOOL_ID,
        TELEGRAM_GET_CHAT_INFO_TOOL_ID,
    )
    assert all(not tool_id.startswith("telegram.send") for tool_id in binding.tool_runtime.registered_tool_ids)


def test_telegram_tool_binding_rejects_drive_grant() -> None:
    port = FakeTelegramPort()
    with pytest.raises(EngineToolProjectionError):
        telegram_tool_binding(
            grant=DriveGrant(  # type: ignore[arg-type]
                app_id=DRIVE_REFERENCE_APP_ID,
                canonical_agent_id="agent:padiem:claw_drive_reader@1",
                binding_ref=BINDING_REF,
                actor_ref=ACTOR_REF,
                granted_capabilities=(),
            ),
            port=port,
        )


def test_telegram_tool_binding_rejects_wrong_app_id() -> None:
    port = FakeTelegramPort()
    with pytest.raises(EngineToolProjectionError) as exc_info:
        telegram_tool_binding(grant=telegram_grant(app_id="other-app"), port=port)
    assert exc_info.value.status_code == 403


def test_telegram_tool_binding_rejects_wrong_agent_id() -> None:
    port = FakeTelegramPort()
    with pytest.raises(EngineToolProjectionError) as exc_info:
        telegram_tool_binding(grant=telegram_grant(canonical_agent_id="agent:other@1"), port=port)
    assert exc_info.value.status_code == 403


def test_telegram_tool_binding_rejects_incomplete_port() -> None:
    class EmptyPort:
        pass

    with pytest.raises(EngineToolProjectionError) as exc_info:
        telegram_tool_binding(grant=telegram_grant(), port=EmptyPort())  # type: ignore[arg-type]
    assert exc_info.value.status_code == 503


# --- shared resolver coexistence (framework reuse, not a new framework) ---


def test_resolver_telegram_only() -> None:
    port = FakeTelegramPort()
    resolver = build_tool_binding_resolver(
        gmail_port=None,
        telegram_port=port,
        telegram_grants={TELEGRAM_REFERENCE_APP_ID: telegram_grant()},
    )
    assert resolver is not None
    binding = resolver(TELEGRAM_REFERENCE_APP_ID)
    assert binding is not None
    assert binding.app_id == TELEGRAM_REFERENCE_APP_ID
    assert resolver(GMAIL_REFERENCE_APP_ID) is None


def test_resolver_no_ports_returns_none() -> None:
    resolver = build_tool_binding_resolver(gmail_port=None, telegram_port=None)
    assert resolver is None


def test_resolver_empty_telegram_grants_returns_none_for_telegram() -> None:
    port = FakeTelegramPort()
    resolver = build_tool_binding_resolver(
        gmail_port=None,
        telegram_port=port,
        telegram_grants={},
    )
    assert resolver is None


def test_three_connectors_coexist_via_one_shared_resolver() -> None:
    gmail_port = FakeTelegramPort()
    drive_port = FakeTelegramPort()
    drive_port.get_text = lambda **kwargs: ""  # type: ignore[method-assign]
    telegram_port = FakeTelegramPort()
    gmail_grant = GmailGrant(
        app_id=GMAIL_REFERENCE_APP_ID,
        canonical_agent_id="agent:padiem:claw_mail_reader@1",
        binding_ref="bind:gmail",
        actor_ref=ACTOR_REF,
        granted_scopes=("gmail.readonly",),
    )
    drive_grant = DriveGrant(
        app_id=DRIVE_REFERENCE_APP_ID,
        canonical_agent_id="agent:padiem:claw_drive_reader@1",
        binding_ref="bind:drive",
        actor_ref=ACTOR_REF,
        granted_capabilities=(DriveCapability.READ,),
    )
    resolver = build_tool_binding_resolver(
        gmail_port=gmail_port,
        grants={GMAIL_REFERENCE_APP_ID: gmail_grant},
        drive_port=drive_port,
        drive_grants={DRIVE_REFERENCE_APP_ID: drive_grant},
        telegram_port=telegram_port,
        telegram_grants={TELEGRAM_REFERENCE_APP_ID: telegram_grant()},
    )
    assert resolver is not None
    assert resolver(GMAIL_REFERENCE_APP_ID) is not None
    assert resolver(DRIVE_REFERENCE_APP_ID) is not None
    telegram_binding = resolver(TELEGRAM_REFERENCE_APP_ID)
    assert telegram_binding is not None
    assert telegram_binding.app_id == TELEGRAM_REFERENCE_APP_ID
    # Gmail and Drive slots keep resolving to their own runtimes unchanged.
    gmail_binding = resolver(GMAIL_REFERENCE_APP_ID)
    assert gmail_binding is not None
    assert gmail_binding.app_id == GMAIL_REFERENCE_APP_ID


def test_resolver_caches_telegram_binding() -> None:
    port = FakeTelegramPort()
    resolver = build_tool_binding_resolver(
        gmail_port=None,
        telegram_port=port,
        telegram_grants={TELEGRAM_REFERENCE_APP_ID: telegram_grant()},
    )
    assert resolver is not None
    first = resolver(TELEGRAM_REFERENCE_APP_ID)
    second = resolver(TELEGRAM_REFERENCE_APP_ID)
    assert first is second


def test_binding_authority_carries_readonly_scope_only() -> None:
    port = FakeTelegramPort()
    binding = telegram_tool_binding(grant=telegram_grant(), port=port)
    authority = binding.authorities[TELEGRAM_AGENT_ID]
    scopes = tuple(authority.authorization.granted_auth_scopes)
    # The runtime compares spec.auth_scope tokens ("telegram.readonly"), not the
    # raw capability value ("read"); granting READ must project exactly the
    # readonly scope and never the send scope.
    assert scopes == (TELEGRAM_READONLY_AUTH_SCOPE,)
    assert TELEGRAM_SEND_AUTH_SCOPE not in scopes


def test_readonly_grant_executes_bot_info_tool_through_runtime() -> None:
    # Canary blocker regression (#2712): the runtime compares spec.auth_scope
    # tokens, so a READ grant must reach the trusted port instead of failing
    # with tool_auth_scope_missing at the scope gate.
    from padiem_ai_core.tool_runtime import ToolInvocation

    port = FakeTelegramPort()
    binding = telegram_tool_binding(grant=telegram_grant(), port=port)
    authority = binding.authorities[TELEGRAM_AGENT_ID]
    result = run(
        binding.tool_runtime.execute(
            ToolInvocation(tool_id=TELEGRAM_GET_BOT_INFO_TOOL_ID, arguments={}),
            authority.compiled.runtime_profile,
            authority.authorization,
        )
    )
    assert result.tool_id == TELEGRAM_GET_BOT_INFO_TOOL_ID
    assert result.output["result_status"] == "OK"
    assert len(port.calls) == 1
    assert port.calls[0]["path"] == "/getMe"
    assert port.calls[0]["required_scopes"] == (TELEGRAM_READONLY_AUTH_SCOPE,)


def test_real_getme_envelope_classifies_as_canary_canonical() -> None:
    # Cross-layer contract (#2712): the production read canary classifies the
    # EXACT Core envelope; the source round shipped them drifting (missing
    # raw_credentials_present) and every layer's own tests stayed green.
    import importlib.util
    from pathlib import Path

    from padiem_ai_core.tool_runtime import ToolInvocation

    script = Path(__file__).resolve().parents[1] / "scripts" / "a15_telegram_read_production_canary.py"
    spec = importlib.util.spec_from_file_location("a15_read_canary_contract", script)
    assert spec is not None and spec.loader is not None
    canary = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(canary)

    port = FakeTelegramPort()
    binding = telegram_tool_binding(grant=telegram_grant(), port=port)
    authority = binding.authorities[TELEGRAM_AGENT_ID]
    result = run(
        binding.tool_runtime.execute(
            ToolInvocation(tool_id=TELEGRAM_GET_BOT_INFO_TOOL_ID, arguments={}),
            authority.compiled.runtime_profile,
            authority.authorization,
        )
    )
    # Same public projection the production route applies: secret-shaped keys
    # such as bot_token_present come back as the canonical [redacted] marker,
    # which the canary classifier must accept.
    redacted, truncated = project_redacted_tool_output(result.output_copy())
    payload = {
        "ok": True,
        "tool": {
            "canonical_tool_id": canary.TOOL_ID,
            "status": "completed",
            "output": redacted,
            "output_truncated": truncated,
        },
    }
    bot_identity_present, truncated_fact = canary.classify_success(payload)
    assert bot_identity_present is True
    assert truncated_fact is False
    assert redacted["bot"]["bot_token_present"] == "[redacted]"
    assert redacted["raw_credentials_present"] == "[redacted]"
