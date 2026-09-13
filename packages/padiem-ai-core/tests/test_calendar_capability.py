"""Core Google Calendar capability contract tests (#2358).

Network-free. Stubs the trusted ``CalendarReadPort`` boundary with a recording
fake; zero provider calls, zero tokens, zero writes.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from padiem_ai_core.calendar_capability import (
    CALENDAR_CANONICAL_TOOL_IDS,
    CALENDAR_CONNECTOR_ID,
    CALENDAR_DESCRIPTOR,
    CALENDAR_GET_CALENDAR_TOOL_ID,
    CALENDAR_GET_EVENT_TOOL_ID,
    CALENDAR_LIST_CALENDARS_TOOL_ID,
    CALENDAR_LIST_EVENTS_TOOL_ID,
    CALENDAR_LIVE_PROVIDER_CALLS,
    CALENDAR_RAW_OAUTH_TOKEN_IN_CORE,
    CALENDAR_READONLY_AUTH_SCOPE,
    CALENDAR_READ_TOOL_IDS,
    CALENDAR_SECOND_GOOGLE_OAUTH_STACK,
    CALENDAR_WRITE_AUTH_SCOPE,
    CALENDAR_WRITE_TOOLS_PRESENT,
    GOOGLE_CALENDAR_API_HOST,
    GOOGLE_CALENDAR_BASE_URL,
    GOOGLE_CALENDAR_READONLY_OAUTH_SCOPE,
    MAX_CALENDARS,
    MAX_CALENDAR_EVENT_SUMMARY_CHARS,
    MAX_CALENDAR_PROJECTION_ITEMS,
    CalendarCapability,
    CalendarCapabilityClassification,
    CalendarCapabilityGrant,
    CalendarContractError,
    CalendarEventInfo,
    CalendarInfo,
    CalendarScope,
    build_calendar_read_handlers,
    calendar_capability_snapshot,
    calendar_read_tool_specs,
    capability_requires_write_approval,
    classify_calendar_tool_id,
    core_auth_scopes_for_capability,
    register_calendar_read_tools,
)
from padiem_ai_core.connector_registry import validate_connector_tools
from padiem_ai_core.contracts import ApprovalPolicy, ToolSideEffect
from padiem_ai_core.tool_registry import RegisteredTool, ToolRegistrySnapshot
from padiem_ai_core.tool_runtime import ToolRuntime

BINDING_REF = "binding_calendar_1"
ACTOR_REF = "actor_1"
CALENDAR_ID = "primary"
WORK_CALENDAR_ID = "work@example.com"
OTHER_CALENDAR_ID = "other@example.com"
EVENT_ID = "0ppg4tqic1lkk84m33o8rpktk1"
SERIES_ID = "series5f0h1t2q0c4k8m6o4s6u8w0a"


def run(coro):
    return asyncio.run(coro)


class FakeCalendarPort:
    """In-memory trusted port double. No network, no token."""

    def __init__(self, *, json_responses: list[dict] | None = None) -> None:
        self.json_responses: list[dict] = list(json_responses or [])
        self.calls: list[dict] = []

    def get_json(self, **kwargs):
        self.calls.append(kwargs)
        if not self.json_responses:
            raise AssertionError("unexpected provider JSON call")
        return self.json_responses.pop(0)


def calendar_handlers(port: FakeCalendarPort, **kwargs) -> dict:
    return build_calendar_read_handlers(
        port, binding_ref=BINDING_REF, actor_ref=ACTOR_REF, **kwargs
    )


def calendar_list(*entries: dict) -> dict:
    return {"kind": "calendar#calendarList", "items": list(entries)}


def calendar_entry(calendar_id: str = CALENDAR_ID, *, summary: str = "Primary") -> dict:
    return {
        "kind": "calendar#calendarListEntry",
        "id": calendar_id,
        "summary": summary,
        "timeZone": "Asia/Seoul",
        "colorId": "7",
        "htmlLink": "https://calendar.google.com/calendar/r?token=secret-token",
    }


def timed_event(**overrides) -> dict:
    base = {
        "kind": "calendar#event",
        "id": EVENT_ID,
        "status": "confirmed",
        "summary": "Standup",
        "htmlLink": "https://calendar.google.com/calendar/event?eid=secret",
        "description": "private agenda body",
        "start": {"dateTime": "2026-09-14T09:00:00+09:00", "timeZone": "Asia/Seoul"},
        "end": {"dateTime": "2026-09-14T09:15:00+09:00", "timeZone": "Asia/Seoul"},
        "attendees": [{"email": "person@example.com", "responseStatus": "accepted"}],
        "organizer": {"email": "organizer@example.com"},
        "updated": "2026-09-12T00:00:00.000Z",
    }
    base.update(overrides)
    return base


def all_day_event(**overrides) -> dict:
    base = {
        "kind": "calendar#event",
        "id": "allday01eventid",
        "status": "confirmed",
        "summary": "Holiday",
        "start": {"date": "2026-09-15"},
        "end": {"date": "2026-09-16"},
    }
    base.update(overrides)
    return base


def events_list(*items: dict) -> dict:
    return {"kind": "calendar#events", "items": list(items)}


def test_specs_are_read_only_and_bounded() -> None:
    specs = calendar_read_tool_specs()
    assert tuple(spec.id for spec in specs) == CALENDAR_READ_TOOL_IDS
    for spec in specs:
        assert spec.side_effect is ToolSideEffect.READ
        assert spec.approval_policy is ApprovalPolicy.NOT_REQUIRED
        assert spec.auth_scope == (CALENDAR_READONLY_AUTH_SCOPE,)


def test_canonical_tool_ids_and_descriptor_conform_to_core_registries() -> None:
    specs = calendar_read_tool_specs()
    entries = tuple(
        RegisteredTool.from_spec(canonical_tool_id=canonical_id, runtime_spec=spec)
        for canonical_id, spec in zip(CALENDAR_CANONICAL_TOOL_IDS, specs)
    )
    tool_registry = ToolRegistrySnapshot.from_entries(entries)
    validated = validate_connector_tools(CALENDAR_DESCRIPTOR, tool_registry)
    assert validated.connector_id == CALENDAR_CONNECTOR_ID
    assert validated.canonical_tool_ids == CALENDAR_CANONICAL_TOOL_IDS


def test_bounds_mirror_reviewed_contract() -> None:
    assert MAX_CALENDARS == 128
    assert MAX_CALENDAR_EVENT_SUMMARY_CHARS == 2_000
    assert MAX_CALENDAR_PROJECTION_ITEMS == 100


def test_classify_calendar_tool_id_is_fail_closed() -> None:
    for tool_id in CALENDAR_READ_TOOL_IDS + CALENDAR_CANONICAL_TOOL_IDS:
        assert classify_calendar_tool_id(tool_id) is CalendarCapabilityClassification.READ
    for tool_id in (
        "calendar.create_event",
        "calendar.update_event",
        "calendar.delete_event",
        "calendar.cancel_event",
        "events.insert",
        "events.update",
        "events.patch",
        "events.delete",
        "events.move",
        "events.import",
        "events.watch",
        "calendars.insert",
        "acl.insert",
        "tool:google:calendar.event_create@1",
    ):
        assert (
            classify_calendar_tool_id(tool_id)
            is CalendarCapabilityClassification.WRITE_OR_MATERIAL
        ), tool_id
    for tool_id in ("calendar.do_something", "tool:google:calendar.mystery@1"):
        assert classify_calendar_tool_id(tool_id) is CalendarCapabilityClassification.UNKNOWN
    for bad in ("", "   ", "cal endar", "x" * 200):
        with pytest.raises(CalendarContractError):
            classify_calendar_tool_id(bad)


def test_capability_scopes_and_approval_semantics() -> None:
    assert core_auth_scopes_for_capability(CalendarCapability.READ) == (
        CALENDAR_READONLY_AUTH_SCOPE,
    )
    assert core_auth_scopes_for_capability(CalendarCapability.CREATE_EVENT) == (
        CALENDAR_WRITE_AUTH_SCOPE,
    )
    assert capability_requires_write_approval(CalendarCapability.READ) is False
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
        assert capability_requires_write_approval(capability) is True


def test_grant_never_mints_write_or_token_authority() -> None:
    grant = CalendarCapabilityGrant(
        connector_id=CALENDAR_CONNECTOR_ID,
        binding_ref=BINDING_REF,
        granted_capabilities=(CalendarCapability.READ,),
    )
    assert grant.allows(CalendarCapability.READ) is True
    assert grant.write_authority() is False
    safe = grant.safe_dict()
    assert safe["mints_approval_authority"] is False
    assert safe["oauth_token_present"] is False
    assert safe["raw_credentials_present"] is False
    write_grant = CalendarCapabilityGrant(
        connector_id=CALENDAR_CONNECTOR_ID,
        binding_ref=BINDING_REF,
        granted_capabilities=(CalendarCapability.READ, CalendarCapability.CREATE_EVENT),
    )
    assert write_grant.write_authority() is True
    with pytest.raises(CalendarContractError):
        CalendarCapabilityGrant(
            connector_id=CALENDAR_CONNECTOR_ID,
            binding_ref=BINDING_REF,
            granted_capabilities=(CalendarCapability.READ, CalendarCapability.READ),
        )


def test_snapshot_is_deterministic_and_fail_closed() -> None:
    first = calendar_capability_snapshot()
    assert first == calendar_capability_snapshot()
    encoded = json.dumps(first, sort_keys=True)
    assert "token" not in encoded.replace("_token", "")
    assert first["read_tool_ids"] == list(CALENDAR_READ_TOOL_IDS)
    assert first["registered_write_tools"] == []
    assert first["write_tools_present"] is False
    assert first["create_tools_present"] is False
    assert first["update_tools_present"] is False
    assert first["delete_tools_present"] is False
    assert first["cancel_tools_present"] is False
    assert first["invitation_response_tools_present"] is False
    assert first["attendee_mutation_tools_present"] is False
    assert first["reminder_mutation_tools_present"] is False
    assert first["conference_mutation_tools_present"] is False
    assert first["live_provider_calls"] == CALENDAR_LIVE_PROVIDER_CALLS
    assert first["raw_oauth_token_in_core"] is CALENDAR_RAW_OAUTH_TOKEN_IN_CORE
    assert first["second_google_oauth_stack"] is CALENDAR_SECOND_GOOGLE_OAUTH_STACK
    assert first["production_activation"] is False
    assert first["mints_approval_authority"] is False
    assert first["account_connection_implies_all_calendars"] is False


def test_calendar_scope_requires_explicit_allowlist() -> None:
    with pytest.raises(CalendarContractError):
        CalendarScope(binding_ref=BINDING_REF, account_ref=WORK_CALENDAR_ID, allowed_calendar_ids=())
    scope = CalendarScope(
        binding_ref=BINDING_REF,
        account_ref=WORK_CALENDAR_ID,
        allowed_calendar_ids=(CALENDAR_ID, WORK_CALENDAR_ID),
    )
    assert scope.authorizes(calendar_id=CALENDAR_ID) is True
    assert scope.authorizes(calendar_id=OTHER_CALENDAR_ID) is False
    safe = scope.safe_dict()
    assert safe["account_connection_implies_all_calendars"] is False
    assert safe["oauth_token_present"] is False


def test_calendar_scope_rejects_malformed_bounds() -> None:
    with pytest.raises(CalendarContractError):
        CalendarScope(
            binding_ref=BINDING_REF,
            account_ref=WORK_CALENDAR_ID,
            allowed_calendar_ids=(CALENDAR_ID, CALENDAR_ID),
        )
    with pytest.raises(CalendarContractError):
        CalendarScope(
            binding_ref=BINDING_REF,
            account_ref=WORK_CALENDAR_ID,
            allowed_calendar_ids=("path/escape",),
        )
    with pytest.raises(CalendarContractError):
        CalendarScope(
            binding_ref=BINDING_REF,
            account_ref=WORK_CALENDAR_ID,
            allowed_calendar_ids=(CALENDAR_ID,),
            default_timezone="Not A Zone!!",
        )
    with pytest.raises(CalendarContractError):
        CalendarScope(
            binding_ref=BINDING_REF,
            account_ref=WORK_CALENDAR_ID,
            allowed_calendar_ids=tuple(f"cal{i}" for i in range(MAX_CALENDARS + 1)),
        )


def test_calendar_info_projection_has_no_event_content() -> None:
    info = CalendarInfo(calendar_id=WORK_CALENDAR_ID, name="Work", time_zone="Asia/Seoul")
    safe = info.safe_dict()
    assert safe["event_content_present"] is False
    assert safe["oauth_token_present"] is False
    with pytest.raises(CalendarContractError):
        CalendarInfo(calendar_id="bad calendar/id", name="Work")


def test_timed_event_projection_is_bounded_and_untrusted() -> None:
    event = CalendarEventInfo(
        calendar_id=CALENDAR_ID,
        event_id=EVENT_ID,
        series_id=EVENT_ID,
        instance_of_series=False,
        status="confirmed",
        summary="Standup",
        all_day=False,
        start="2026-09-14T09:00:00+09:00",
        end="2026-09-14T09:15:00+09:00",
        start_time_zone="Asia/Seoul",
        end_time_zone="Asia/Seoul",
        attendee_count=1,
        organizer_present=True,
    )
    safe = event.safe_dict()
    assert safe["event_kind"] == "timed"
    assert safe["attendee_emails_present"] is False
    assert safe["description_present"] is False
    assert safe["attachment_or_link_present"] is False
    assert safe["event_content_trusted"] is False
    assert "person@example.com" not in json.dumps(safe)
    with pytest.raises(CalendarContractError):
        CalendarEventInfo(
            calendar_id=CALENDAR_ID,
            event_id=EVENT_ID,
            series_id=EVENT_ID,
            instance_of_series=False,
            status="needsAction",
            summary="Standup",
            all_day=False,
            start="2026-09-14T09:00:00+09:00",
            end="2026-09-14T09:15:00+09:00",
        )


def test_all_day_event_projection_has_no_timezone() -> None:
    event = CalendarEventInfo(
        calendar_id=CALENDAR_ID,
        event_id="allday01eventid",
        series_id="allday01eventid",
        instance_of_series=False,
        status="confirmed",
        summary="Holiday",
        all_day=True,
        start="2026-09-15",
        end="2026-09-16",
    )
    safe = event.safe_dict()
    assert safe["event_kind"] == "all_day"
    assert safe["start_time_zone"] is None
    with pytest.raises(CalendarContractError):
        CalendarEventInfo(
            calendar_id=CALENDAR_ID,
            event_id="allday01eventid",
            series_id="allday01eventid",
            instance_of_series=False,
            status="confirmed",
            summary="Holiday",
            all_day=True,
            start="2026-09-15",
            end="2026-09-16",
            start_time_zone="Asia/Seoul",
        )


def test_recurrence_identity_is_preserved_without_expansion() -> None:
    port = FakeCalendarPort(
        json_responses=[
            events_list(
                timed_event(
                    id="instance001",
                    recurringEventId=SERIES_ID,
                    recurrence=["RRULE:FREQ=WEEKLY"],
                )
            )
        ]
    )
    handlers = calendar_handlers(port)
    result = run(
        handlers[CALENDAR_LIST_EVENTS_TOOL_ID](
            {
                "calendarId": CALENDAR_ID,
                "timeMin": "2026-09-01T00:00:00Z",
                "timeMax": "2026-10-01T00:00:00Z",
            }
        )
    )
    event = result["events"][0]
    assert event["instance_of_series"] is True
    assert event["series_id"] == SERIES_ID
    assert event["event_id"] == "instance001"
    assert event["recurrence_rule_count"] == 1
    assert "RRULE" not in json.dumps(result)


def test_list_calendars_projects_allowlist_only() -> None:
    port = FakeCalendarPort(
        json_responses=[
            calendar_list(
                calendar_entry(CALENDAR_ID),
                calendar_entry(OTHER_CALENDAR_ID, summary="Other"),
            )
        ]
    )
    handlers = calendar_handlers(port, allowed_calendar_ids=(CALENDAR_ID,))
    result = run(handlers[CALENDAR_LIST_CALENDARS_TOOL_ID]({}))
    assert result["provider"] == "google_calendar"
    assert result["result_status"] == "OK"
    assert [item["calendar_id"] for item in result["calendars"]] == [CALENDAR_ID]
    assert result["whole_account_dump"] is False
    assert "htmlLink" not in json.dumps(result)
    assert "secret-token" not in json.dumps(result)
    call = port.calls[0]
    assert call["base_url"] == GOOGLE_CALENDAR_BASE_URL
    assert call["path"] == "/users/me/calendarList"
    assert call["required_scopes"] == (CALENDAR_READONLY_AUTH_SCOPE,)
    assert call["binding_ref"] == BINDING_REF
    assert call["actor_ref"] == ACTOR_REF


def test_get_calendar_enforces_server_allowlist() -> None:
    port = FakeCalendarPort(json_responses=[calendar_entry(CALENDAR_ID)])
    handlers = calendar_handlers(port, allowed_calendar_ids=(CALENDAR_ID,))
    result = run(handlers[CALENDAR_GET_CALENDAR_TOOL_ID]({"calendarId": CALENDAR_ID}))
    assert result["calendar"]["calendar_id"] == CALENDAR_ID
    assert result["write_capability_granted"] is False
    with pytest.raises(CalendarContractError):
        run(handlers[CALENDAR_GET_CALENDAR_TOOL_ID]({"calendarId": OTHER_CALENDAR_ID}))
    assert len(port.calls) == 1


def test_get_calendar_rejects_identity_mismatch() -> None:
    port = FakeCalendarPort(json_responses=[calendar_entry(OTHER_CALENDAR_ID)])
    handlers = calendar_handlers(port)
    with pytest.raises(CalendarContractError):
        run(handlers[CALENDAR_GET_CALENDAR_TOOL_ID]({"calendarId": CALENDAR_ID}))


def test_list_events_requires_valid_ordered_window() -> None:
    handlers = calendar_handlers(FakeCalendarPort())
    for arguments in (
        {"calendarId": CALENDAR_ID, "timeMin": "2026-09-01T00:00:00Z"},
        {"calendarId": CALENDAR_ID, "timeMin": "2026-09-01 00:00", "timeMax": "2026-10-01T00:00:00Z"},
        {"calendarId": CALENDAR_ID, "timeMin": "2026-10-01T00:00:00Z", "timeMax": "2026-09-01T00:00:00Z"},
        {"calendarId": CALENDAR_ID, "timeMin": "2026-09-01T00:00:00Z", "timeMax": "2026-09-01T00:00:00Z"},
        {"calendarId": CALENDAR_ID, "timeMin": "2026-09-01T00:00:00Z", "timeMax": "2026-10-01T00:00:00Z", "extra": 1},
    ):
        with pytest.raises(CalendarContractError):
            run(handlers[CALENDAR_LIST_EVENTS_TOOL_ID](arguments))


def test_list_events_bounds_page_and_query() -> None:
    port = FakeCalendarPort(
        json_responses=[events_list(timed_event(), all_day_event())]
    )
    handlers = calendar_handlers(port, allowed_calendar_ids=(CALENDAR_ID,))
    result = run(
        handlers[CALENDAR_LIST_EVENTS_TOOL_ID](
            {
                "calendarId": CALENDAR_ID,
                "timeMin": "2026-09-01T00:00:00Z",
                "timeMax": "2026-10-01T00:00:00Z",
                "limit": 2,
            }
        )
    )
    kinds = [event["event_kind"] for event in result["events"]]
    assert kinds == ["timed", "all_day"]
    assert result["event_count"] == 2
    assert "private agenda body" not in json.dumps(result)
    assert "person@example.com" not in json.dumps(result)
    assert all(event["description_present"] is False for event in result["events"])
    call = port.calls[0]
    assert call["path"] == f"/calendars/{CALENDAR_ID}/events"
    assert call["query"]["singleEvents"] == "true"
    assert call["query"]["maxResults"] == "2"
    with pytest.raises(CalendarContractError):
        run(
            handlers[CALENDAR_LIST_EVENTS_TOOL_ID](
                {
                    "calendarId": CALENDAR_ID,
                    "timeMin": "2026-09-01T00:00:00Z",
                    "timeMax": "2026-10-01T00:00:00Z",
                    "limit": 101,
                }
            )
        )


def test_get_event_rejects_identity_mismatch_and_malformed_ids() -> None:
    port = FakeCalendarPort(
        json_responses=[timed_event(id=EVENT_ID), timed_event(id=EVENT_ID)]
    )
    handlers = calendar_handlers(port)
    result = run(
        handlers[CALENDAR_GET_EVENT_TOOL_ID]({"calendarId": CALENDAR_ID, "eventId": EVENT_ID})
    )
    assert result["event"]["event_id"] == EVENT_ID
    assert result["event"]["oauth_token_present"] is False
    with pytest.raises(CalendarContractError):
        run(handlers[CALENDAR_GET_EVENT_TOOL_ID]({"calendarId": CALENDAR_ID, "eventId": "other01id"}))
    with pytest.raises(CalendarContractError):
        run(
            handlers[CALENDAR_GET_EVENT_TOOL_ID](
                {"calendarId": CALENDAR_ID, "eventId": "../../escape"}
            )
        )


def test_malformed_provider_events_fail_closed() -> None:
    for broken in (
        timed_event(start={"date": "2026-09-14", "dateTime": "2026-09-14T09:00:00+09:00"}),
        timed_event(start={"date": "2026-09-14"}, end={"dateTime": "2026-09-14T09:15:00+09:00"}),
        timed_event(status="unknownFutureValue"),
        timed_event(start={"dateTime": "2026-09-14 09:00"}),
        timed_event(summary="x" * (MAX_CALENDAR_EVENT_SUMMARY_CHARS + 1)),
        timed_event(attendees="not-a-list"),
    ):
        port = FakeCalendarPort(json_responses=[events_list(broken)])
        handlers = calendar_handlers(port)
        with pytest.raises(CalendarContractError):
            run(
                handlers[CALENDAR_LIST_EVENTS_TOOL_ID](
                    {
                        "calendarId": CALENDAR_ID,
                        "timeMin": "2026-09-01T00:00:00Z",
                        "timeMax": "2026-10-01T00:00:00Z",
                    }
                )
            )


def test_port_exception_is_sanitized_never_leaks_token() -> None:
    class ExplodingPort:
        def get_json(self, **kwargs):
            raise RuntimeError("token ya29.secret-value leaked here")

    handlers = calendar_handlers(ExplodingPort())
    with pytest.raises(CalendarContractError) as exc_info:
        run(handlers[CALENDAR_LIST_CALENDARS_TOOL_ID]({}))
    assert "secret-value" not in str(exc_info.value)
    assert "ya29" not in str(exc_info.value)


def test_provider_error_body_is_rejected_without_echo() -> None:
    port = FakeCalendarPort(
        json_responses=[{"error": {"code": 403, "message": "insufficient for token ya29-secret"}}]
    )
    handlers = calendar_handlers(port)
    with pytest.raises(CalendarContractError) as exc_info:
        run(handlers[CALENDAR_LIST_CALENDARS_TOOL_ID]({}))
    assert "secret" not in str(exc_info.value)


def test_registration_is_read_only_on_shared_runtime() -> None:
    runtime = ToolRuntime()
    port = FakeCalendarPort()
    registered = register_calendar_read_tools(
        runtime, port, binding_ref=BINDING_REF, actor_ref=ACTOR_REF
    )
    assert registered == CALENDAR_READ_TOOL_IDS
    assert set(runtime.registered_tool_ids) == set(CALENDAR_READ_TOOL_IDS)
    assert len(runtime.registered_tool_ids) == len(CALENDAR_READ_TOOL_IDS)
    assert all("create" not in spec.id and "update" not in spec.id for spec in calendar_read_tool_specs())


def test_host_constant_is_official_api_only() -> None:
    assert GOOGLE_CALENDAR_API_HOST == "www.googleapis.com"
    assert GOOGLE_CALENDAR_BASE_URL == "https://www.googleapis.com/calendar/v3"
    assert GOOGLE_CALENDAR_READONLY_OAUTH_SCOPE == "https://www.googleapis.com/auth/calendar.readonly"
    assert CALENDAR_CONNECTOR_ID == "connector:google:calendar@1"
    assert CALENDAR_WRITE_TOOLS_PRESENT is False
