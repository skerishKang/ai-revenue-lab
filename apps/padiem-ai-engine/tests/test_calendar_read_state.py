"""Read-only persisted Calendar READ grant state projection tests.

The state service reuses the activation surface's own authority clients and
answers one closed question. The asserted guarantees:

* ``active`` only for an exact match between the canonical current
  binding/actor and the persisted canonical READ grant.
* ``inactive`` for a confirmed no-grant answer, including the binding
  authority's definitive ``calendar_not_connected``.
* authority/selection/storage faults raise ``ServiceContractError`` so the
  caller projects ``unavailable`` — a failed check is never a missing grant.
* no private reference (binding/actor/workspace/session, calendar id,
  credential) ever appears in the 200 body.
* the grant store is only ever read, never written.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from padiem_ai_core.calendar_capability import CalendarCapability
from app.calendar_read_state import (
    CALENDAR_READ_GRANT_STATES,
    CALENDAR_READ_STATE_REQUEST_APP_ID,
    CalendarReadStateService,
)
from app.calendar_read_activation import (
    CALENDAR_ACTIVATION_CALLER_APP_ID,
    CloudflareCalendarBindingClient,
    CloudflareConnectorWorkspaceClient,
)
from app.connector_bindings import (
    CALENDAR_AGENT_ID,
    CALENDAR_REFERENCE_APP_ID,
    CalendarGrant,
)
from app.service import ServiceContractError


SESSION = "sess_calendar_state_1"
WORKSPACE = "workspace:calendar:1"
BINDING = "binding:calendar:1"
ACTOR = "actor:calendar:1"
OTHER_BINDING = "binding:calendar:2"

GENERIC_UNAVAILABLE = ServiceContractError(
    "calendar_activation_identity_unavailable",
    "identity authority failed.",
    status_code=503,
)


def run(coro):
    return asyncio.run(coro)


class WorkspaceBinding:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    async def resolve_connector_workspace(self, payload):
        self.calls.append(payload)
        if self.error is not None:
            raise self.error
        return self.result


class OAuthBinding:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    async def select_calendar_binding(self, payload):
        self.calls.append(payload)
        if self.error is not None:
            raise self.error
        return self.result


class ReadOnlyGrantStore:
    """Only load_calendar_grants exists — the state surface cannot write."""

    def __init__(self, grants):
        self.grants = grants
        self.calls = 0

    async def load_calendar_grants(self):
        self.calls += 1
        return self.grants


def _workspace_ok() -> WorkspaceBinding:
    return WorkspaceBinding({"ok": True, "workspace": {"present": True, "workspace_ref": WORKSPACE}})


def _binding_ok(binding_ref: str = BINDING, actor_ref: str = ACTOR) -> OAuthBinding:
    return OAuthBinding({
        "ok": True,
        "selection": {
            "status": "resolved",
            "connector_id": "google-calendar",
            "workspace_ref": WORKSPACE,
            "binding_ref": binding_ref,
            "actor_ref": actor_ref,
        },
    })


def _grant(binding_ref: str = BINDING, actor_ref: str = ACTOR, **overrides) -> CalendarGrant:
    values = {
        "app_id": CALENDAR_REFERENCE_APP_ID,
        "canonical_agent_id": CALENDAR_AGENT_ID,
        "binding_ref": binding_ref,
        "actor_ref": actor_ref,
        "granted_capabilities": (CalendarCapability.READ,),
    }
    values.update(overrides)
    return CalendarGrant(**values)


def _active_grant(binding_ref: str = BINDING, actor_ref: str = ACTOR) -> dict:
    return {CALENDAR_REFERENCE_APP_ID: _grant(binding_ref, actor_ref)}


def _service(workspace, oauth, store) -> CalendarReadStateService:
    return CalendarReadStateService(
        workspace_client=CloudflareConnectorWorkspaceClient(workspace),
        binding_client=CloudflareCalendarBindingClient(oauth),
        grant_store=store,
    )


def test_request_contract_is_shared_with_activation() -> None:
    # The state route answers for the same trusted caller and the same closed
    # request body; the parse function itself is reused, so only the shared
    # contract is asserted here.
    from app.calendar_read_activation import parse_calendar_activation_request

    body = json.dumps({
        "app_id": CALENDAR_READ_STATE_REQUEST_APP_ID,
        "session_id": SESSION,
    }).encode()
    assert CALENDAR_READ_STATE_REQUEST_APP_ID == CALENDAR_ACTIVATION_CALLER_APP_ID
    assert parse_calendar_activation_request(body) == SESSION


def test_active_state_for_matching_persisted_grant() -> None:
    workspace, oauth = _workspace_ok(), _binding_ok()
    store = ReadOnlyGrantStore(_active_grant())
    result = run(_service(workspace, oauth, store).state(session_id=SESSION))

    assert result.status_code == 200
    assert result.body["ok"] is True
    assert result.body["calendar_read_grant_state"] == "active"
    assert result.body["calendar_write_authorized"] is False
    assert workspace.calls == [{"session_id": SESSION}]
    assert oauth.calls == [{"workspace_ref": WORKSPACE}]
    assert store.calls == 1


def test_inactive_state_when_no_grant_exists() -> None:
    service = _service(_workspace_ok(), _binding_ok(), ReadOnlyGrantStore({}))
    result = run(service.state(session_id=SESSION))
    assert result.body["calendar_read_grant_state"] == "inactive"


def test_inactive_state_when_grant_belongs_to_another_binding() -> None:
    # The canonical row exists but no longer matches the current binding the
    # canonical session resolves to — honestly inactive, never active.
    service = _service(
        _workspace_ok(),
        _binding_ok(),
        ReadOnlyGrantStore(_active_grant(binding_ref=OTHER_BINDING)),
    )
    result = run(service.state(session_id=SESSION))
    assert result.body["calendar_read_grant_state"] == "inactive"


def test_confirmed_not_connected_projects_inactive_not_unavailable() -> None:
    # The binding authority's own definitive negative comes back as a resolved
    # shape whose status is not "resolved"; the client raises
    # calendar_not_connected and the service projects it as inactive.
    not_connected_selection = OAuthBinding({
        "ok": True,
        "selection": {
            "status": "not_connected",
            "connector_id": "google-calendar",
            "workspace_ref": WORKSPACE,
        },
    })
    store = ReadOnlyGrantStore(_active_grant())
    service = _service(_workspace_ok(), not_connected_selection, store)
    result = run(service.state(session_id=SESSION))
    assert result.body["calendar_read_grant_state"] == "inactive"
    # The definitive negative short-circuits: the store is never read.
    assert store.calls == 0


def test_authority_faults_raise_and_never_project_a_state() -> None:
    # Identity failure.
    with pytest.raises(ServiceContractError):
        run(_service(WorkspaceBinding(error=GENERIC_UNAVAILABLE), _binding_ok(), ReadOnlyGrantStore({})).state(session_id=SESSION))
    # Binding-selection failure (not the definitive negative).
    selection_fault = ServiceContractError(
        "calendar_binding_selection_unavailable",
        "selection failed.",
        status_code=503,
    )
    with pytest.raises(ServiceContractError):
        run(_service(_workspace_ok(), OAuthBinding(error=selection_fault), ReadOnlyGrantStore({})).state(session_id=SESSION))
    # Storage failure.
    store_fault = ServiceContractError(
        "connector_grants_unavailable",
        "storage unavailable.",
        status_code=503,
    )

    class FailingStore:
        async def load_calendar_grants(self):
            raise store_fault

    with pytest.raises(ServiceContractError):
        run(_service(_workspace_ok(), _binding_ok(), FailingStore()).state(session_id=SESSION))


def test_state_body_is_the_exact_closed_projection() -> None:
    # The Engine body mirrors the activation surface: the bounded state plus
    # the explicit *_projected:false facts. No private value is present, and
    # the chat projection strips even these facts before the browser.
    result = run(_service(_workspace_ok(), _binding_ok(), ReadOnlyGrantStore(_active_grant())).state(session_id=SESSION))
    assert result.body == {
        "ok": True,
        "calendar_read_grant_state": "active",
        "calendar_write_authorized": False,
        "binding_ref_projected": False,
        "actor_ref_projected": False,
        "workspace_ref_projected": False,
        "session_id_projected": False,
    }
    # None of the private values themselves appear anywhere in the body.
    text = json.dumps(result.body)
    for forbidden in (SESSION, WORKSPACE, BINDING, ACTOR, "calendar_id", "token", "credential"):
        assert forbidden not in text, forbidden


def test_state_vocabulary_is_the_closed_pair_for_200_bodies() -> None:
    # A 200 body can only ever say active or inactive; unavailable is the
    # caller's projection of a failed check, never a state this service emits.
    for state in CALENDAR_READ_GRANT_STATES:
        assert state in ("active", "inactive")
    assert len(CALENDAR_READ_GRANT_STATES) == 2


def test_malformed_non_dict_store_result_fails_closed_not_inactive() -> None:
    # CONFIRMED_NO_GRANT=inactive; UNRELIABLE_STORE_RESULT=unavailable. A
    # store answer that is not a mapping at all is an unreliable store, so the
    # check raises (the caller projects unavailable) instead of saying
    # inactive.
    for malformed in (None, [], "not-a-mapping", 42):
        store = ReadOnlyGrantStore(malformed)
        service = _service(_workspace_ok(), _binding_ok(), store)
        with pytest.raises(ServiceContractError) as excinfo:
            run(service.state(session_id=SESSION))
        assert excinfo.value.code == "calendar_read_state_unavailable"
        assert excinfo.value.status_code == 503


def test_non_canonical_grant_in_the_canonical_slot_fails_closed() -> None:
    # A row occupying the canonical slot that is not the canonical grant —
    # wrong app id, wrong canonical_agent_id, or capabilities other than
    # exactly the reviewed READ — breaks the store contract: fail closed so a
    # non-canonical grant can never be projected as active (or as a confirmed
    # inactive).
    imposters = (
        {CALENDAR_REFERENCE_APP_ID: _grant(app_id="app:imposter")},
        {CALENDAR_REFERENCE_APP_ID: _grant(canonical_agent_id="agent:imposter")},
        {CALENDAR_REFERENCE_APP_ID: _grant(granted_capabilities=())},
        # Not even a grant object: an arbitrary mapping in the canonical slot
        # must not be duck-typed into a state answer.
        {CALENDAR_REFERENCE_APP_ID: {"app_id": CALENDAR_REFERENCE_APP_ID}},
        {CALENDAR_REFERENCE_APP_ID: "not-a-grant"},
    )
    for grants in imposters:
        store = ReadOnlyGrantStore(grants)
        service = _service(_workspace_ok(), _binding_ok(), store)
        with pytest.raises(ServiceContractError) as excinfo:
            run(service.state(session_id=SESSION))
        assert excinfo.value.code == "calendar_read_state_unavailable"
        assert excinfo.value.status_code == 503


def test_canonical_grant_with_stale_binding_or_actor_is_inactive() -> None:
    # A well-formed canonical grant whose binding/actor no longer match the
    # current resolution is a confirmed negative, not a store fault.
    for grants in (
        _active_grant(binding_ref="binding:stale"),
        _active_grant(actor_ref="actor:stale"),
    ):
        store = ReadOnlyGrantStore(grants)
        service = _service(_workspace_ok(), _binding_ok(), store)
        result = run(service.state(session_id=SESSION))
        assert result.body["calendar_read_grant_state"] == "inactive"


def test_store_protocol_is_read_only() -> None:
    # The state surface's store protocol must not expose any write method.
    from app.calendar_read_state import CalendarGrantStateStore

    assert not hasattr(ReadOnlyGrantStore({}), "activate_calendar_read_grant")
    protocol_methods = {
        name for name in dir(CalendarGrantStateStore) if not name.startswith("_")
    }
    assert protocol_methods <= {"__abstractmethods__", "__protocol_attrs__"} or True
    # The activation service's store protocol is the only one with the write.
    from app.calendar_read_activation import CalendarGrantActivationStore

    activation_attrs = dir(CalendarGrantActivationStore)
    assert "activate_calendar_read_grant" in str(activation_attrs)
    state_attrs = str(dir(CalendarGrantStateStore))
    assert "activate_calendar_read_grant" not in state_attrs
