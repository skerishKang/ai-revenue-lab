"""Engine Slack trusted binding entry tests (#2356).

Network-free. Stubs the Core ``SlackReadPort`` boundary with a recording
fake. Proves the promoted Slack connector rides the existing shared resolver
framework (no new connector framework) and that Gmail/Drive/Telegram binding
behavior is unchanged.
"""

from __future__ import annotations

import asyncio

import pytest

from padiem_ai_core.drive_capability import DriveCapability
from padiem_ai_core.slack_capability import (
    SLACK_CANONICAL_TOOL_IDS,
    SLACK_LIST_CHANNELS_TOOL_ID,
    SLACK_READONLY_AUTH_SCOPE,
    SLACK_READ_TOOL_IDS,
    SlackCapability,
    SlackContractError,
)
from app.connector_bindings import (
    DRIVE_REFERENCE_APP_ID,
    GMAIL_REFERENCE_APP_ID,
    SLACK_AGENT_ID,
    SLACK_REFERENCE_APP_ID,
    DriveGrant,
    GmailGrant,
    SlackGrant,
    build_tool_binding_resolver,
    slack_tool_binding,
)
from app.tool_projection import EngineToolBinding, EngineToolProjectionError

BINDING_REF = "bind:slack_engine"
ACTOR_REF = "actor_1"


def run(coro):
    return asyncio.run(coro)


class FakeSlackPort:
    """In-memory trusted Slack port double. No network, no bot token."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def get_json(self, **kwargs: object) -> dict:
        self.calls.append(kwargs)
        return {
            "ok": True,
            "url": "https://acme.slack.com/",
            "team": "Acme",
            "team_id": "T0TEAM123",
            "user_id": "U0BOT1234",
            "channels": [
                {"id": "C0AAAAAAA", "name": "ops", "is_private": False, "num_members": 4},
            ],
            "messages": [
                {"ts": "1700000000.000100", "text": "hello", "user": "U0USER1"},
            ],
            "file": {"id": "F0FILE123", "name": "brief.pdf", "size": "1024", "mimetype": "application/pdf"},
        }


def slack_grant(**overrides) -> SlackGrant:
    values = {
        "app_id": SLACK_REFERENCE_APP_ID,
        "canonical_agent_id": SLACK_AGENT_ID,
        "binding_ref": BINDING_REF,
        "actor_ref": ACTOR_REF,
        "granted_capabilities": (SlackCapability.READ,),
    }
    values.update(overrides)
    return SlackGrant(**values)


# --- grant shape ---


def test_slack_grant_rejects_duplicate_capabilities() -> None:
    with pytest.raises(SlackContractError):
        slack_grant(
            granted_capabilities=(SlackCapability.READ, SlackCapability.READ)
        )


def test_slack_grant_rejects_non_capability_values() -> None:
    with pytest.raises(SlackContractError):
        slack_grant(granted_capabilities=("slack.readonly",))  # type: ignore[arg-type]


def test_slack_grant_rejects_write_capabilities() -> None:
    for capability in (
        SlackCapability.POST_MESSAGE,
        SlackCapability.REPLY_THREAD,
        SlackCapability.UPDATE_MESSAGE,
        SlackCapability.UPLOAD_FILE,
    ):
        with pytest.raises(SlackContractError):
            slack_grant(granted_capabilities=(SlackCapability.READ, capability))


# --- binding assembly ---


def test_slack_tool_binding_assembles_engine_tool_binding() -> None:
    port = FakeSlackPort()
    binding = slack_tool_binding(grant=slack_grant(), port=port)
    assert isinstance(binding, EngineToolBinding)
    assert binding.app_id == SLACK_REFERENCE_APP_ID
    assert set(binding.registry.canonical_tool_ids) == set(SLACK_CANONICAL_TOOL_IDS)
    assert set(binding.authorities) == {SLACK_AGENT_ID}


def test_slack_tool_binding_registers_read_tools_only() -> None:
    port = FakeSlackPort()
    binding = slack_tool_binding(grant=slack_grant(), port=port)
    assert set(binding.tool_runtime.registered_tool_ids) == set(SLACK_READ_TOOL_IDS)
    assert all(not tool_id.startswith("slack.send") for tool_id in binding.tool_runtime.registered_tool_ids)
    assert SLACK_LIST_CHANNELS_TOOL_ID in binding.tool_runtime.registered_tool_ids


def test_slack_tool_binding_rejects_drive_grant() -> None:
    port = FakeSlackPort()
    with pytest.raises(EngineToolProjectionError):
        slack_tool_binding(
            grant=DriveGrant(  # type: ignore[arg-type]
                app_id=DRIVE_REFERENCE_APP_ID,
                canonical_agent_id="agent:padiem:claw_drive_reader@1",
                binding_ref=BINDING_REF,
                actor_ref=ACTOR_REF,
                granted_capabilities=(),
            ),
            port=port,
        )


def test_slack_tool_binding_rejects_wrong_app_id() -> None:
    port = FakeSlackPort()
    with pytest.raises(EngineToolProjectionError) as exc_info:
        slack_tool_binding(grant=slack_grant(app_id="other-app"), port=port)
    assert exc_info.value.status_code == 403


def test_slack_tool_binding_rejects_wrong_agent_id() -> None:
    port = FakeSlackPort()
    with pytest.raises(EngineToolProjectionError) as exc_info:
        slack_tool_binding(grant=slack_grant(canonical_agent_id="agent:other@1"), port=port)
    assert exc_info.value.status_code == 403


def test_slack_tool_binding_rejects_incomplete_port() -> None:
    class EmptyPort:
        pass

    with pytest.raises(EngineToolProjectionError) as exc_info:
        slack_tool_binding(grant=slack_grant(), port=EmptyPort())  # type: ignore[arg-type]
    assert exc_info.value.status_code == 503


# --- shared resolver coexistence (framework reuse, not a new framework) ---


def test_resolver_slack_only() -> None:
    port = FakeSlackPort()
    resolver = build_tool_binding_resolver(
        gmail_port=None,
        slack_port=port,
        slack_grants={SLACK_REFERENCE_APP_ID: slack_grant()},
    )
    assert resolver is not None
    binding = resolver(SLACK_REFERENCE_APP_ID)
    assert binding is not None
    assert binding.app_id == SLACK_REFERENCE_APP_ID
    assert resolver(GMAIL_REFERENCE_APP_ID) is None


def test_resolver_no_ports_returns_none() -> None:
    resolver = build_tool_binding_resolver(gmail_port=None, slack_port=None)
    assert resolver is None


def test_resolver_empty_slack_grants_returns_none_for_slack() -> None:
    port = FakeSlackPort()
    resolver = build_tool_binding_resolver(
        gmail_port=None,
        slack_port=port,
        slack_grants={},
    )
    assert resolver is None


def test_four_connectors_coexist_via_one_shared_resolver() -> None:
    gmail_port = FakeSlackPort()
    drive_port = FakeSlackPort()
    drive_port.get_text = lambda **kwargs: ""  # type: ignore[method-assign]
    telegram_port = FakeSlackPort()
    slack_port = FakeSlackPort()
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
    from padiem_ai_core.telegram_capability import TelegramCapability
    from app.connector_bindings import TELEGRAM_AGENT_ID, TELEGRAM_REFERENCE_APP_ID, TelegramGrant

    telegram_grant = TelegramGrant(
        app_id=TELEGRAM_REFERENCE_APP_ID,
        canonical_agent_id=TELEGRAM_AGENT_ID,
        binding_ref="bind:telegram",
        actor_ref=ACTOR_REF,
        granted_capabilities=(TelegramCapability.READ,),
    )
    resolver = build_tool_binding_resolver(
        gmail_port=gmail_port,
        grants={GMAIL_REFERENCE_APP_ID: gmail_grant},
        drive_port=drive_port,
        drive_grants={DRIVE_REFERENCE_APP_ID: drive_grant},
        telegram_port=telegram_port,
        telegram_grants={TELEGRAM_REFERENCE_APP_ID: telegram_grant},
        slack_port=slack_port,
        slack_grants={SLACK_REFERENCE_APP_ID: slack_grant()},
    )
    assert resolver is not None
    assert resolver(GMAIL_REFERENCE_APP_ID) is not None
    assert resolver(DRIVE_REFERENCE_APP_ID) is not None
    telegram_binding = resolver(TELEGRAM_REFERENCE_APP_ID)
    assert telegram_binding is not None
    assert telegram_binding.app_id == TELEGRAM_REFERENCE_APP_ID
    slack_binding = resolver(SLACK_REFERENCE_APP_ID)
    assert slack_binding is not None
    assert slack_binding.app_id == SLACK_REFERENCE_APP_ID
    # Gmail and Drive slots keep resolving to their own runtimes unchanged.
    gmail_binding = resolver(GMAIL_REFERENCE_APP_ID)
    assert gmail_binding is not None
    assert gmail_binding.app_id == GMAIL_REFERENCE_APP_ID


def test_resolver_caches_slack_binding() -> None:
    port = FakeSlackPort()
    resolver = build_tool_binding_resolver(
        gmail_port=None,
        slack_port=port,
        slack_grants={SLACK_REFERENCE_APP_ID: slack_grant()},
    )
    assert resolver is not None
    first = resolver(SLACK_REFERENCE_APP_ID)
    second = resolver(SLACK_REFERENCE_APP_ID)
    assert first is second


def test_binding_authority_carries_readonly_scope_only() -> None:
    port = FakeSlackPort()
    binding = slack_tool_binding(grant=slack_grant(), port=port)
    authority = binding.authorities[SLACK_AGENT_ID]
    scopes = tuple(authority.authorization.granted_auth_scopes)
    assert scopes == (SlackCapability.READ,)
    assert all(str(scope) != SLACK_READONLY_AUTH_SCOPE + ".send" for scope in scopes)
