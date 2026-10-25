"""#4434: the revision routes answered end to end over fake server authorities.

Not an HTTP transport test. The handlers are called with the same Request shape
Starlette gives them, against fake Identity consent, a fake Broker binding and
execution profile, and a fake history row. What is observed is behaviour: the
codes, the exact edits shown to the owner, one enqueue per confirmation, and the
refusals that must happen before anything is minted.

No network, no device, no real file, no approval shortcut: the fake Broker records
what it was handed and the tests assert what the routes were *not* allowed to do.
"""

from __future__ import annotations

import asyncio
import json
import types
from datetime import datetime, timezone

import pytest
from starlette.requests import Request

from app import connector_xlsx_revision_routes as handlers

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
ROOT = "quote_root"
PATH = "quote\\book.xlsx"
EXECUTABLE = "C:\\Program Files\\PADIEM\\padiem-agent.exe"
EDITS = [{"cell": "B2", "previous_value": 88_000_000, "replacement_value": 91_500_000}]
BODY = {
    "device_id": "dev_4434", "root_ref": ROOT, "path_relative": PATH,
    "sheet_name": "Quote", "edits": [dict(item) for item in EDITS],
    "run_id": "run_4434",
}


class RecordingBroker:
    def __init__(self, *, calls: list, executable: str = EXECUTABLE) -> None:
        self._calls = calls
        self._executable = executable

    async def resolve_device_binding(self, **_kwargs):
        return {"binding_ref": "bind_4434", "credential_generation": 3}

    async def installed_txt_execution_profile(self, **_kwargs):
        return self._executable

    async def enqueue_xlsx_revision_command(self, *, command, material):
        self._calls.append((command, material))
        return {
            "command_id": command["command_id"], "run_id": command["run_id"],
            "revision_ref": "rev_4434",
            "request_fingerprint": command["request_fingerprint"],
        }


class Identity:
    def __init__(self, *, workspace_mismatch: bool = False) -> None:
        self._mismatch = workspace_mismatch

    async def resolve_connector_enrollment_consent_for_device(self, **_kwargs):
        return {"device_id": "dev_4434", "account_ref": "acct_4434",
                "workspace_ref": "cws_4434", "consent_id": "consent_4434",
                "withdrawn_at": None}

    async def resolve_connector_workspace(self, **_kwargs):
        return "cws_other" if self._mismatch else "cws_4434"


class History:
    def __init__(self, *, foreign_run: bool = False) -> None:
        self._foreign_run = foreign_run

    async def get_claw_run(self, _uid, run_id):
        if self._foreign_run:
            return {"run_id": run_id, "workspace_id": "someone_elses_workspace",
                    "conversation_id": "conv_4434"}
        return {"run_id": run_id, "workspace_id": "mem_ws",
                "conversation_id": "conv_4434"}


def _request(body, monkeypatch, *, enqueued: list, auth: bool = True,
             identity: Identity | None = None, history: History | None = None,
             executable: str = EXECUTABLE):
    broker = RecordingBroker(calls=enqueued, executable=executable)
    state = types.SimpleNamespace(
        control_plane_identity_authority=identity or Identity(),
        connector_txt_read_source=broker,
        history_store=history or History())
    scope = {"type": "http", "method": "POST", "path": "/",
             "headers": [(b"content-type", b"application/json")],
             "query_string": b"", "scheme": "https",
             "app": types.SimpleNamespace(state=state), "state": {},
             "client": ("127.0.0.1", 1)}
    raw = json.dumps(body).encode()

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}

    async def verified(_request):
        if not auth:
            return None, handlers._error(401, "canonical_session_required")
        return types.SimpleNamespace(session_id="sess_4434"), None

    async def workspace(_request, _uid):
        return "mem_ws"

    monkeypatch.setattr(handlers, "_verified_owner_request", verified)
    monkeypatch.setattr(handlers, "_resolve_memory_workspace", workspace)
    monkeypatch.setattr(handlers, "current_user_id", lambda _r: "usr_4434")
    monkeypatch.setattr(handlers, "auth_ready", lambda _r: auth)
    return Request(scope, receive)


async def _returns(value):
    return value


def preview(monkeypatch, body=None, **kwargs):
    enqueued = kwargs.pop("enqueued", [])
    request = _request(body or dict(BODY), monkeypatch, enqueued=enqueued, **kwargs)
    return asyncio.run(handlers.preview_revision(request)), enqueued


def confirm(monkeypatch, ref, body=None, **kwargs):
    enqueued = kwargs.pop("enqueued", [])
    request = _request({**(body or dict(BODY)), "preview_ref": ref, "confirmed": True},
                       monkeypatch, enqueued=enqueued, **kwargs)
    return asyncio.run(handlers.request_revision(request)), enqueued


def test_preview_shows_the_exact_edits_and_queues_nothing(monkeypatch):
    response, enqueued = preview(monkeypatch)
    body = json.loads(response.body)

    assert response.status_code == 200
    assert body["edits"] == [dict(item) for item in EDITS]
    assert body["sheet_name"] == "Quote"
    assert body["result_path_relative"] == "quote\\book_revised.xlsx"
    assert body["path_relative"] == PATH
    assert body["read_only_envelope"] is True
    assert body["write_approval_minted_here"] is False
    assert enqueued == []


def test_confirmation_mints_the_read_envelope_and_enqueues_once(monkeypatch):
    response, _ = preview(monkeypatch)
    ref = json.loads(response.body)["preview_ref"]

    confirmed, enqueued = confirm(monkeypatch, ref)
    body = json.loads(confirmed.body)

    assert confirmed.status_code == 200
    assert body["read_approval_issued"] is True
    assert body["write_approval_issued"] is False
    assert body["file_modified_by_this_call"] is False
    assert body["conversation_id"] == "conv_4434"
    assert len(enqueued) == 1
    command, material = enqueued[0]
    assert material["p01_approval_payload"]["format"] == "claw-xlsx-revision-approval.v1"
    assert material["p01_approval_payload"]["revision"]["edits"] == (
        [dict(item) for item in EDITS])
    assert material["shell_authority"] is False
    assert material["admin_elevation"] is False
    assert command["binding_ref"] == "bind_4434"


def test_the_same_reference_cannot_confirm_twice(monkeypatch):
    response, _ = preview(monkeypatch)
    ref = json.loads(response.body)["preview_ref"]
    enqueued: list = []

    first, _ = confirm(monkeypatch, ref, enqueued=enqueued)
    second, _ = confirm(monkeypatch, ref, enqueued=enqueued)

    assert first.status_code == 200
    assert second.status_code == 409
    assert json.loads(second.body)["error"]["code"] == "revision_preview_not_confirmed"
    assert len(enqueued) == 1


def test_an_intent_changed_after_the_preview_is_refused(monkeypatch):
    response, _ = preview(monkeypatch)
    ref = json.loads(response.body)["preview_ref"]
    changed = [{"cell": "B2", "previous_value": 88_000_000, "replacement_value": 7}]

    refused, enqueued = confirm(monkeypatch, ref,
                                body={**BODY, "edits": changed})

    assert refused.status_code == 409
    assert enqueued == []


@pytest.mark.parametrize("value", [
    "/srv/book.xlsx", "\\\\server\\share\\book.xlsx", "C:\\x\\book.xlsx",
    "..\\other\\book.xlsx", "quote\\notes.txt",
])
def test_selections_that_cannot_run_on_the_pc_are_refused_before_minting(
        monkeypatch, value):
    response, enqueued = preview(monkeypatch, {**BODY, "path_relative": value})

    assert response.status_code == 400
    assert json.loads(response.body)["error"]["code"] == "revision_intent_refused"
    assert enqueued == []


@pytest.mark.parametrize("edits,code", [
    ([], "revision_invalid_body"),
    ([{"cell": "B2", "previous_value": 1, "replacement_value": "=SUM(A1)"}],
     "revision_intent_refused"),
    ([{"cell": "B2", "previous_value": 1, "replacement_value": 1.5}],
     "revision_intent_refused"),
    ([{"cell": "b2", "previous_value": 1, "replacement_value": 2}],
     "revision_intent_refused"),
])
def test_non_literal_or_malformed_edit_requests_are_refused(monkeypatch, edits, code):
    response, enqueued = preview(monkeypatch, {**BODY, "edits": edits})

    assert response.status_code == 400
    assert json.loads(response.body)["error"]["code"] == code
    assert enqueued == []


def test_an_unverified_session_is_refused_before_any_authority_is_read(monkeypatch):
    response, enqueued = preview(monkeypatch, auth=False)

    assert response.status_code == 401
    assert enqueued == []


def test_consent_that_does_not_match_the_connector_workspace_is_refused(monkeypatch):
    response, enqueued = preview(monkeypatch, identity=Identity(workspace_mismatch=True))

    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == "revision_consent_required"
    assert enqueued == []


def test_a_run_belonging_to_another_workspace_is_not_reachable(monkeypatch):
    response, enqueued = preview(monkeypatch, history=History(foreign_run=True))

    assert response.status_code == 404
    assert json.loads(response.body)["error"]["code"] == "revision_run_unavailable"
    assert enqueued == []


def test_an_untrusted_execution_profile_stops_the_preview(monkeypatch):
    response, enqueued = preview(monkeypatch, executable="python")

    assert response.status_code == 400
    assert json.loads(response.body)["error"]["code"] == "revision_intent_refused"
    assert enqueued == []


def test_a_request_without_confirmation_is_refused(monkeypatch):
    response, _ = preview(monkeypatch)
    ref = json.loads(response.body)["preview_ref"]
    enqueued: list = []
    request = _request({**BODY, "preview_ref": ref, "confirmed": False}, monkeypatch,
                       enqueued=enqueued)

    refused = asyncio.run(handlers.request_revision(request))

    assert refused.status_code == 400
    assert enqueued == []


def test_the_response_never_leaks_paths_authorities_or_secrets(monkeypatch):
    response, _ = preview(monkeypatch)
    ref = json.loads(response.body)["preview_ref"]

    confirmed, _ = confirm(monkeypatch, ref)
    serialized = json.loads(confirmed.body)

    assert set(serialized) == {
        "ok", "command", "conversation_id", "result_path_relative",
        "read_approval_issued", "write_approval_issued", "file_modified_by_this_call",
    }
    assert set(serialized["command"]) == {"command_id", "run_id", "tool_request_ref"}
    assert "device_id" not in serialized
    assert "credential" not in json.dumps(serialized)
