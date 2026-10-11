"""Engine Calendar trusted binding entry tests (#2358).

Network-free. Stubs the Core ``CalendarReadPort`` boundary with a recording
fake. Proves the promoted Calendar connector rides the existing shared
resolver framework (no new connector framework) and that Gmail/Drive/
Telegram/Slack binding behavior is unchanged.
"""

from __future__ import annotations

import asyncio

import pytest

from padiem_ai_core.calendar_capability import (
    CALENDAR_CANONICAL_TOOL_IDS,
    CALENDAR_LIST_CALENDARS_TOOL_ID,
    CALENDAR_READONLY_AUTH_SCOPE,
    CALENDAR_READ_TOOL_IDS,
    CalendarCapability,
    CalendarContractError,
)
from padiem_ai_core.drive_capability import DriveCapability
from app.connector_bindings import (
    CALENDAR_AGENT_ID,
    CALENDAR_REFERENCE_APP_ID,
    DRIVE_REFERENCE_APP_ID,
    GMAIL_REFERENCE_APP_ID,
    SLACK_AGENT_ID,
    SLACK_REFERENCE_APP_ID,
    TELEGRAM_AGENT_ID,
    TELEGRAM_REFERENCE_APP_ID,
    CalendarGrant,
    DriveGrant,
    GmailGrant,
    SlackGrant,
    TelegramGrant,
    build_tool_binding_resolver,
    calendar_tool_binding,
)
from app.tool_projection import EngineToolBinding, EngineToolProjectionError
from padiem_ai_core.slack_capability import SlackCapability
from padiem_ai_core.telegram_capability import TelegramCapability

BINDING_REF = "bind:calendar_engine"
ACTOR_REF = "actor_1"


def run(coro):
    return asyncio.run(coro)


class FakeCalendarPort:
    """In-memory trusted Calendar port double. No network, no OAuth secrets."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def get_json(self, **kwargs: object) -> dict:
        self.calls.append(kwargs)
        path = str(kwargs["path"])
        if path == "/users/me/calendarList":
            return {
                "kind": "calendar#calendarList",
                "etag": "E1",
                "items": [
                    {"id": "primary", "summary": "Primary", "timeZone": "Asia/Seoul"},
                ],
            }
        if path.endswith("/events"):
            return {
                "items": [
                    {
                        "id": "evt1",
                        "summary": "Standup",
                        "status": "confirmed",
                        "start": {"dateTime": "2026-09-14T09:00:00+09:00"},
                        "end": {"dateTime": "2026-09-14T09:30:00+09:00"},
                    }
                ]
            }
        if "/events/" in path:
            return {
                "id": "evt1",
                "summary": "Standup",
                "status": "confirmed",
                "start": {"dateTime": "2026-09-14T09:00:00+09:00"},
                "end": {"dateTime": "2026-09-14T09:30:00+09:00"},
            }
        return {"id": "primary", "summary": "Primary", "timeZone": "Asia/Seoul", "etag": "E2"}


def calendar_grant(**overrides) -> CalendarGrant:
    values = {
        "app_id": CALENDAR_REFERENCE_APP_ID,
        "canonical_agent_id": CALENDAR_AGENT_ID,
        "binding_ref": BINDING_REF,
        "actor_ref": ACTOR_REF,
        "granted_capabilities": (CalendarCapability.READ,),
    }
    values.update(overrides)
    return CalendarGrant(**values)


# --- grant shape ---


def test_calendar_grant_rejects_duplicate_capabilities() -> None:
    with pytest.raises(CalendarContractError):
        calendar_grant(
            granted_capabilities=(CalendarCapability.READ, CalendarCapability.READ)
        )


def test_calendar_grant_rejects_non_capability_values() -> None:
    with pytest.raises(CalendarContractError):
        calendar_grant(granted_capabilities=("calendar.readonly",))  # type: ignore[arg-type]


def test_calendar_grant_rejects_write_capabilities() -> None:
    for capability in (
        CalendarCapability.CREATE_EVENT,
        CalendarCapability.UPDATE_EVENT,
        CalendarCapability.DELETE_EVENT,
        CalendarCapability.CANCEL_EVENT,
        CalendarCapability.RESPOND_TO_EVENT,
        CalendarCapability.ATTENDEE_MUTATION,
        CalendarCapability.REMINDER_MUTATION,
        CalendarCapability.CONFERENCE_MUTATION,
    ):
        with pytest.raises(CalendarContractError):
            calendar_grant(granted_capabilities=(CalendarCapability.READ, capability))


# --- binding assembly ---


def test_calendar_tool_binding_assembles_engine_tool_binding() -> None:
    port = FakeCalendarPort()
    binding = calendar_tool_binding(grant=calendar_grant(), port=port)
    assert isinstance(binding, EngineToolBinding)
    assert binding.app_id == CALENDAR_REFERENCE_APP_ID
    assert set(binding.registry.canonical_tool_ids) == set(CALENDAR_CANONICAL_TOOL_IDS)
    assert set(binding.authorities) == {CALENDAR_AGENT_ID}


def test_calendar_tool_binding_registers_read_tools_only() -> None:
    port = FakeCalendarPort()
    binding = calendar_tool_binding(grant=calendar_grant(), port=port)
    assert set(binding.tool_runtime.registered_tool_ids) == set(CALENDAR_READ_TOOL_IDS)
    assert all(
        not tool_id.startswith(("calendar.create", "calendar.update", "calendar.delete"))
        for tool_id in binding.tool_runtime.registered_tool_ids
    )
    assert CALENDAR_LIST_CALENDARS_TOOL_ID in binding.tool_runtime.registered_tool_ids


def test_calendar_tool_binding_rejects_drive_grant() -> None:
    port = FakeCalendarPort()
    with pytest.raises(EngineToolProjectionError):
        calendar_tool_binding(
            grant=DriveGrant(  # type: ignore[arg-type]
                app_id=DRIVE_REFERENCE_APP_ID,
                canonical_agent_id="agent:padiem:claw_drive_reader@1",
                binding_ref=BINDING_REF,
                actor_ref=ACTOR_REF,
                granted_capabilities=(),
            ),
            port=port,
        )


def test_calendar_tool_binding_rejects_wrong_app_id() -> None:
    port = FakeCalendarPort()
    with pytest.raises(EngineToolProjectionError) as exc_info:
        calendar_tool_binding(grant=calendar_grant(app_id="other-app"), port=port)
    assert exc_info.value.status_code == 403


def test_calendar_tool_binding_rejects_wrong_agent_id() -> None:
    port = FakeCalendarPort()
    with pytest.raises(EngineToolProjectionError) as exc_info:
        calendar_tool_binding(grant=calendar_grant(canonical_agent_id="agent:other@1"), port=port)
    assert exc_info.value.status_code == 403


def test_calendar_tool_binding_rejects_incomplete_port() -> None:
    class EmptyPort:
        pass

    with pytest.raises(EngineToolProjectionError) as exc_info:
        calendar_tool_binding(grant=calendar_grant(), port=EmptyPort())  # type: ignore[arg-type]
    assert exc_info.value.status_code == 503


# --- shared resolver coexistence (framework reuse, not a new framework) ---


def test_resolver_calendar_only() -> None:
    port = FakeCalendarPort()
    resolver = build_tool_binding_resolver(
        gmail_port=None,
        calendar_port=port,
        calendar_grants={CALENDAR_REFERENCE_APP_ID: calendar_grant()},
    )
    assert resolver is not None
    binding = resolver(CALENDAR_REFERENCE_APP_ID)
    assert binding is not None
    assert binding.app_id == CALENDAR_REFERENCE_APP_ID
    assert resolver(GMAIL_REFERENCE_APP_ID) is None


def test_resolver_no_ports_returns_none() -> None:
    resolver = build_tool_binding_resolver(gmail_port=None, calendar_port=None)
    assert resolver is None


def test_resolver_empty_calendar_grants_returns_none_for_calendar() -> None:
    port = FakeCalendarPort()
    resolver = build_tool_binding_resolver(
        gmail_port=None,
        calendar_port=port,
        calendar_grants={},
    )
    assert resolver is None


def test_five_connectors_coexist_via_one_shared_resolver() -> None:
    gmail_port = FakeCalendarPort()
    drive_port = FakeCalendarPort()
    drive_port.get_text = lambda **kwargs: ""  # type: ignore[method-assign]
    telegram_port = FakeCalendarPort()
    slack_port = FakeCalendarPort()
    calendar_port = FakeCalendarPort()
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
    telegram_grant = TelegramGrant(
        app_id=TELEGRAM_REFERENCE_APP_ID,
        canonical_agent_id=TELEGRAM_AGENT_ID,
        binding_ref="bind:telegram",
        actor_ref=ACTOR_REF,
        granted_capabilities=(TelegramCapability.READ,),
    )
    slack_grant = SlackGrant(
        app_id=SLACK_REFERENCE_APP_ID,
        canonical_agent_id=SLACK_AGENT_ID,
        binding_ref="bind:slack",
        actor_ref=ACTOR_REF,
        granted_capabilities=(SlackCapability.READ,),
    )
    resolver = build_tool_binding_resolver(
        gmail_port=gmail_port,
        grants={GMAIL_REFERENCE_APP_ID: gmail_grant},
        drive_port=drive_port,
        drive_grants={DRIVE_REFERENCE_APP_ID: drive_grant},
        telegram_port=telegram_port,
        telegram_grants={TELEGRAM_REFERENCE_APP_ID: telegram_grant},
        slack_port=slack_port,
        slack_grants={SLACK_REFERENCE_APP_ID: slack_grant},
        calendar_port=calendar_port,
        calendar_grants={CALENDAR_REFERENCE_APP_ID: calendar_grant()},
    )
    assert resolver is not None
    assert resolver(GMAIL_REFERENCE_APP_ID) is not None
    assert resolver(DRIVE_REFERENCE_APP_ID) is not None
    assert resolver(TELEGRAM_REFERENCE_APP_ID) is not None
    assert resolver(SLACK_REFERENCE_APP_ID) is not None
    calendar_binding = resolver(CALENDAR_REFERENCE_APP_ID)
    assert calendar_binding is not None
    assert calendar_binding.app_id == CALENDAR_REFERENCE_APP_ID
    # Gmail and Drive slots keep resolving to their own runtimes unchanged.
    gmail_binding = resolver(GMAIL_REFERENCE_APP_ID)
    assert gmail_binding is not None
    assert gmail_binding.app_id == GMAIL_REFERENCE_APP_ID


def test_resolver_caches_calendar_binding() -> None:
    port = FakeCalendarPort()
    resolver = build_tool_binding_resolver(
        gmail_port=None,
        calendar_port=port,
        calendar_grants={CALENDAR_REFERENCE_APP_ID: calendar_grant()},
    )
    assert resolver is not None
    first = resolver(CALENDAR_REFERENCE_APP_ID)
    second = resolver(CALENDAR_REFERENCE_APP_ID)
    assert first is second


def test_binding_authority_carries_readonly_scope_only() -> None:
    port = FakeCalendarPort()
    binding = calendar_tool_binding(grant=calendar_grant(), port=port)
    authority = binding.authorities[CALENDAR_AGENT_ID]
    scopes = tuple(authority.authorization.granted_auth_scopes)
    assert scopes == (CalendarCapability.READ,)
    assert all(str(scope) != CALENDAR_READONLY_AUTH_SCOPE + ".write" for scope in scopes)
