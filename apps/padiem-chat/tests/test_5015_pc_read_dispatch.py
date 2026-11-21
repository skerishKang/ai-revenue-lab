"""#5015: Chat PC read_file stages the existing kind=read download lane.

The list tool stays on the PowerShell command lane. The read tool must stage a
kind=read dispatch, carry the server-computed 20 MB bound to the executor, and
return the verified raw body through the existing result store/route. No live
Mesh, Identity or Broker is involved.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import oracle_mesh_read_return_routes as routes

from _support.pc_read_dispatch import (
    OWNER,
    SUBJECT,
    ACCOUNT,
    WORKSPACE,
    RUN,
    CONVERSATION,
    DEVICE,
    NODE,
    SECOND_NODE,
    SECRET,
    CHANNEL_SECRET,
    ROOT,
    READ_CALL,
    LIST_CALL,
    READ_BODY,
    READ_MARKER,
    _mapping,
    _Identity,
    _History,
    _SignedRequest,
    _workspace,
    _OwnerLinks,
    _owner_link,
    _legacy_mapping,
    _state,
    _dispatch,
    _base_payload as _shared_base_payload,
    _pending_read_row,
    _context_payload as _shared_context_payload,
)


# Keep the historical hub RUN override used by the signed-stream test.
# The shared builders still own the default payload fields.
def _base_payload(**overrides):
    return _shared_base_payload(**{"run_id": RUN, **overrides})


def _context_payload(**overrides):
    return _shared_context_payload(**{"run_id": RUN, **overrides})


# --------------------------------------------------------------- dispatch
def test_list_stays_command_and_read_stages_kind_read(monkeypatch):
    state = _state(monkeypatch)

    status, body = _dispatch(state, _base_payload())
    assert status == 200, body
    assert body["dispatch"]["kind"] == "command"
    listed = state.history_store.rows[body["dispatch"]["dispatch_id"]]
    assert listed["kind"] == "command"
    assert "Get-ChildItem -LiteralPath" in listed["command_text"]
    assert listed["tool_call_ref"] == LIST_CALL

    status, body = _dispatch(state, _base_payload(
        op="read", path="notes.txt", tool_call_ref=READ_CALL,
    ))
    assert status == 200, body
    assert body["dispatch"]["kind"] == "read"
    read = state.history_store.rows[body["dispatch"]["dispatch_id"]]
    assert read["kind"] == "read"
    assert read.get("command_text") is None
    assert read["node_ref"] == NODE
    assert read["device_id"] == DEVICE
    assert read["root_ref"] == routes._PC_FILES_READ_ROOT_REF
    assert read["path_relative"] == "notes.txt"
    assert read["file_path"] == ROOT + "/notes.txt"
    assert read["tool_request_ref"] == READ_CALL
    assert ":read_file:" in read["tool_request_ref"]


def test_the_read_bound_is_not_a_caller_or_model_field(monkeypatch):
    state = _state(monkeypatch)
    status, body = _dispatch(state, _base_payload(
        op="read", path="notes.txt", tool_call_ref=READ_CALL,
        max_bytes=5_000_000,
    ))
    assert status == 400
    assert body["error"]["code"] == "claw_engine_files_invalid_body"
    assert state.history_store.rows == {}


# ------------------------------------------------------------------- poll
def _poll(state, *, secret=CHANNEL_SECRET):
    request = SimpleNamespace(
        app=SimpleNamespace(state=state),
        headers={routes.ORACLE_MESH_CHANNEL_HEADER: secret},
    )
    response = asyncio.run(routes.oracle_mesh_read_poll(request))
    return response.status_code, json.loads(response.body)


def test_poll_sends_twenty_mb_for_the_chat_read_and_six_mb_for_other_reads(
    monkeypatch,
):
    history = _History()
    state = _state(monkeypatch, history=history)

    history.rows["dsp-read"] = _pending_read_row()
    status, body = _poll(state)
    assert status == 200, body
    assert body["dispatch"]["kind"] == "read"
    assert body["dispatch"]["max_bytes"] == routes.PC_FILES_READ_MAX_BYTES
    assert body["dispatch"]["max_bytes"] == 20_000_000

    # A browser/other read consumer has no PC-files marker and keeps 6 MB.
    other = _pending_read_row(tool_request_ref="oracle_mesh_tool_" + "e" * 24)
    other["dispatch_id"] = "dsp-other"
    other["root_ref"] = "meshcentral_private_trial"
    history.rows["dsp-other"] = other
    status, body = _poll(state)
    assert status == 200, body
    assert body["dispatch"]["dispatch_id"] == "dsp-other"
    # Owner decision 2026-10-28: a non-PC-files read carries no PADIEM bound.
    assert body["dispatch"]["max_bytes"] is None


def test_the_server_root_decides_the_bound_not_the_caller_reference():
    row = _pending_read_row(tool_request_ref="opaque-call-ref")
    assert routes._oracle_mesh_poll_max_bytes(row) == 20_000_000
    row.pop("root_ref")
    assert routes._oracle_mesh_poll_max_bytes(row) is None


def test_poll_names_the_granted_root_for_the_pc_files_read_only(monkeypatch):
    """#5994 D3 후속: the executor's reparse walk needs the real granted root.

    The staged row already holds it — ``file_path`` is staged as
    ``root + "/" + path_relative`` — so the poll derives the root from the
    row, never from a caller, and every other lane keeps a dispatch without
    the field.
    """
    history = _History()
    state = _state(monkeypatch, history=history)

    history.rows["dsp-read"] = _pending_read_row()
    status, body = _poll(state)
    assert status == 200, body
    assert body["dispatch"]["granted_root"] == ROOT

    # A file below one folder of the root still names the root itself.
    nested = _pending_read_row()
    nested["dispatch_id"] = "dsp-nested"
    nested["path_relative"] = "docs/notes.txt"
    nested["file_path"] = ROOT + "/docs/notes.txt"
    history.rows["dsp-nested"] = nested
    status, body = _poll(state)
    assert status == 200, body
    assert body["dispatch"]["dispatch_id"] == "dsp-nested"
    assert body["dispatch"]["granted_root"] == ROOT

    # The trial lane keeps the pre-#5994 shape: no granted root on the wire.
    other = _pending_read_row(tool_request_ref="oracle_mesh_tool_" + "e" * 24)
    other["dispatch_id"] = "dsp-other"
    other["root_ref"] = "meshcentral_private_trial"
    other["path_relative"] = "meshcentral-padiem-trial.txt"
    other["file_path"] = ROOT + "/meshcentral-padiem-trial.txt"
    history.rows["dsp-other"] = other
    status, body = _poll(state)
    assert status == 200, body
    assert body["dispatch"]["dispatch_id"] == "dsp-other"
    assert "granted_root" not in body["dispatch"]


def test_poll_still_rejects_a_wrong_channel_secret(monkeypatch):
    state = _state(monkeypatch)
    state.history_store.rows["dsp-read"] = _pending_read_row()
    status, body = _poll(state, secret="not-the-channel-secret")
    assert status == 403
    assert body["error"]["code"] == "oracle_mesh_channel_rejected"


# ----------------------------------------------------------------- result
def _seed_result(state, *, state_name, exit_code, body_bytes, termination):
    dispatch = _pending_read_row()
    dispatch.update({
        "state": state_name,
        "result_sha256": hashlib.sha256(body_bytes).hexdigest(),
        "result_bytes": len(body_bytes),
        "termination": termination, "exit_code": exit_code,
    })
    state.history_store.rows["dsp-read"] = dispatch
    state.history_store.originals["dsp-read"] = body_bytes
    return dispatch


def test_read_result_returns_the_exact_raw_bytes_and_sha(monkeypatch):
    state = _state(monkeypatch)
    _seed_result(
        state, state_name="done", exit_code=0,
        body_bytes=READ_BODY.encode("utf-8"), termination="exited",
    )
    status, body = _dispatch(state, {
        "subject_id": SUBJECT, "run_id": RUN, "dispatch_id": "dsp-read",
        "mode": "result",
    })
    assert status == 200, body
    row = body["dispatch"]
    assert row["kind"] == "read"
    assert row["output"] == READ_BODY
    assert row["content_sha256"] == hashlib.sha256(
        READ_BODY.encode("utf-8")
    ).hexdigest()
    assert row["content_bytes"] == len(READ_BODY.encode("utf-8"))
    assert row["termination"] == "exited"
    assert row["exit_code"] == 0
    assert state.history_store.message_ids["dsp-read"] == routes.result_message_id(
        conversation_id=CONVERSATION,
        command_id="oracle_mesh_cmd_read", revision_ref="rev",
    )


def test_failed_read_result_still_returns_the_marker_body(monkeypatch):
    state = _state(monkeypatch)
    _seed_result(
        state, state_name="failed", exit_code=1,
        body_bytes=READ_MARKER.encode("utf-8"), termination="exited",
    )
    status, body = _dispatch(state, {
        "subject_id": SUBJECT, "run_id": RUN, "dispatch_id": "dsp-read",
        "mode": "result",
    })
    assert status == 200, body
    assert body["dispatch"]["kind"] == "read"
    assert body["dispatch"]["state"] == "failed"
    assert body["dispatch"]["output"] == READ_MARKER
    assert body["dispatch"]["exit_code"] == 1


def test_command_result_mode_keeps_its_done_only_contract(monkeypatch):
    state = _state(monkeypatch)
    dispatch = _pending_read_row()
    dispatch.update({
        "kind": "command", "state": "failed", "termination": "exited",
        "exit_code": 1, "result_sha256": hashlib.sha256(b"x").hexdigest(),
        "result_bytes": 1,
    })
    state.history_store.rows["dsp-read"] = dispatch
    state.history_store.originals["dsp-read"] = b"x"
    status, body = _dispatch(state, {
        "subject_id": SUBJECT, "run_id": RUN, "dispatch_id": "dsp-read",
        "mode": "result",
    })
    assert status == 409
    assert body["error"]["code"] == "oracle_mesh_result_not_ready"

def test_read_result_has_no_pc_read_cap_and_keeps_six_mb_for_other_lanes():
    oversized = "x" * (routes.PC_FILES_READ_MAX_BYTES + 1)
    raw = oversized.encode("utf-8")
    wire = {
        "content_utf8": oversized,
        "content_bytes": len(raw),
        "content_sha256": hashlib.sha256(raw).hexdigest(),
    }
    # #5882 A: a verified PC read body is accepted whatever one answer's size
    # is; a file larger than a page is paged by the Engine, not refused here.
    assert routes._verified_read_result_text(
        {"root_ref": routes._PC_FILES_READ_ROOT_REF}, wire,
    ) == oversized
    assert routes._verified_read_result_text(
        {"root_ref": "other-read-lane"}, wire,
    ) is not None
    accepted = "x" * 6_000_001
    wire.update(content_utf8=accepted, content_bytes=len(accepted),
                content_sha256=hashlib.sha256(accepted.encode()).hexdigest())
    assert routes._verified_read_result_text(
        {"root_ref": routes._PC_FILES_READ_ROOT_REF}, wire,
    ) == accepted
    assert routes._verified_read_result_text(
        {"root_ref": "other-read-lane"}, wire,
    ) is not None


def _scope_claim(plan="files_list"):
    return {"version": 1, "requested": plan, "admitted": plan,
            "source": "declared", "ops": ["list"] if plan == "files_list" else ["list", "read"],
            "app_id": "padiem-chat"}


def _scoped_dispatch(state, payload, claim):
    response = asyncio.run(routes.oracle_mesh_engine_chat_files_call(
        _SignedRequest(state, payload, scope=claim),
    ))
    return response.status_code, json.loads(response.body)


def test_list_ceiling_refuses_kind_read_at_the_real_dispatch_boundary(monkeypatch):
    state = _state(monkeypatch)
    claim = _scope_claim()
    status, body = _scoped_dispatch(state, _base_payload(), claim)
    assert status == 200 and body["dispatch"]["kind"] == "command"
    status, body = _scoped_dispatch(state, _base_payload(
        op="read", path="notes.txt", tool_call_ref=READ_CALL), claim)
    assert status == 403 and body["error"]["code"] == "pc_scope_denied"
    assert [row["kind"] for row in state.history_store.rows.values()] == ["command"]
    assert state.history_store.scopes[(OWNER, RUN)] == claim


def test_scope_cannot_widen_or_downgrade_to_the_legacy_wire(monkeypatch):
    state = _state(monkeypatch)
    assert _scoped_dispatch(state, _base_payload(), _scope_claim())[0] == 200
    read = _base_payload(op="read", path="notes.txt", tool_call_ref=READ_CALL)
    status, body = _scoped_dispatch(state, read, _scope_claim("files"))
    assert status == 403 and body["error"]["code"] == "pc_scope_frozen"
    status, body = _dispatch(state, read)
    assert status == 403 and body["error"]["code"] == "pc_scope_required"
    assert [row["kind"] for row in state.history_store.rows.values()] == ["command"]


def test_new_chat_accepts_old_engine_wire_with_all_original_guards(monkeypatch):
    state = _state(monkeypatch)
    read = _base_payload(op="read", path="notes.txt", tool_call_ref=READ_CALL)
    request = _SignedRequest(state, read)
    assert "X-Claw-PC-Scope" not in request.headers
    assert "X-Claw-PC-Scope-Proof" not in request.headers
    response = asyncio.run(routes.oracle_mesh_engine_chat_files_call(request))
    assert response.status_code == 200
    assert json.loads(response.body)["dispatch"]["kind"] == "read"
    state = _state(monkeypatch)
    status, body = _dispatch(state, {**read, "path": "../outside.txt"})
    assert status == 422 and state.history_store.rows == {}


def test_scope_proof_binds_claim_to_the_exact_signed_body(monkeypatch):
    state = _state(monkeypatch)
    request = _SignedRequest(state, _base_payload(), scope=_scope_claim())
    request.headers["X-Claw-PC-Scope"] = json.dumps(_scope_claim("files"))
    response = asyncio.run(routes.oracle_mesh_engine_chat_files_call(request))
    assert response.status_code == 401
    assert json.loads(response.body)["error"]["code"] == "pc_scope_proof_invalid"
    assert state.history_store.rows == {}


def test_full_ceiling_keeps_read_and_server_target_path_checks(monkeypatch):
    state = _state(monkeypatch)
    read = _base_payload(op="read", path="notes.txt", tool_call_ref=READ_CALL)
    status, body = _scoped_dispatch(state, read, _scope_claim("files"))
    assert status == 200 and body["dispatch"]["kind"] == "read"
    state = _state(monkeypatch)
    assert _scoped_dispatch(state, {**read, "path": "../outside.txt"}, _scope_claim("files"))[0] == 422
    assert state.history_store.rows == {}
    assert _scoped_dispatch(state, {**read, "device_id": "foreign-pc"}, _scope_claim("files"))[0] == 403
    assert state.history_store.rows == {}


# ------------------------------------------------------- progress projection
# #5573 3-D-2: the conversation reads its own run row, so a PC step the Engine
# actually reached has to show up there as "running" before any answer exists.



def test_a_reached_pc_dispatch_projects_running_without_touching_the_answer(monkeypatch):
    """The dispatch observation is the first real fact that the PC tool ran."""
    state = _state(monkeypatch)
    status, body = _dispatch(state, _base_payload())
    assert status == 200, body
    assert state.history_store.status_writes == [(OWNER, RUN, "running")], (
        state.history_store.status_writes
    )
    row = state.history_store.run_rows[RUN]
    assert row["status"] == "running", row
    # Progress is a projection, never the run's terminal answer.
    assert row["result_summary"] is None, row


def test_the_device_context_call_never_claims_a_pc_step_is_running(monkeypatch):
    """Context is tool discovery: no PC work happened, so the run stays pending."""
    state = _state(monkeypatch)
    status, body = _dispatch(state, _context_payload())
    assert status == 200, body
    assert set(body) == {"ok", "device", "tools", "run_id", "roots", "delegation_roots"}
    assert state.history_store.status_writes == []
    assert state.history_store.run_rows[RUN]["status"] == "pending"


def test_context_keeps_model_labels_separate_from_guard_paths(monkeypatch):
    """(A): the model is given the label of each approved folder, nothing else.

    The real Windows path reaches only the signed Engine guard side channel;
    the model-facing roots/device/tools projection still contains no real path.
    """
    state = _state(monkeypatch)
    status, body = _dispatch(state, _context_payload())
    assert status == 200, body
    assert body["roots"] == [{"label": ROOT.rsplit("/", 1)[-1]}]
    assert body["delegation_roots"] == [{"label": ROOT.rsplit("/", 1)[-1], "path": ROOT}]
    assert ROOT not in json.dumps({key: body[key] for key in ("roots", "device", "tools")}, ensure_ascii=False)
    assert state.history_store.rows == {}


def test_a_status_poll_of_a_running_step_projects_running_too(monkeypatch):
    """The Engine polls the step it dispatched; either leg may be the first one seen."""
    state = _state(monkeypatch)
    status, body = _dispatch(state, _base_payload())
    assert status == 200, body
    dispatch_id = body["dispatch"]["dispatch_id"]
    state.history_store.status_writes.clear()

    status, polled = _dispatch(state, {
        "subject_id": SUBJECT, "run_id": RUN,
        "dispatch_id": dispatch_id, "mode": "command_status",
    })
    assert status == 200, polled
    assert state.history_store.status_writes == [(OWNER, RUN, "running")]


def test_a_status_poll_with_several_owner_links_uses_the_dispatch_node(monkeypatch):
    """The Engine's status leg names only the dispatch; the dispatch names the PC.

    Two active links with no device hint used to answer "ambiguous" and the
    map fallback could not rescue it, so a step that had already run was
    reported as an unverified target.
    """
    state = _state(
        monkeypatch, links=[_owner_link(NODE), _owner_link(SECOND_NODE)],
        mapping=_legacy_mapping(),
    )
    status, created = _dispatch(state, _base_payload(device_id=NODE))
    assert status == 200, created
    dispatch_id = created["dispatch"]["dispatch_id"]
    status, polled = _dispatch(state, {
        "subject_id": SUBJECT, "run_id": RUN,
        "dispatch_id": dispatch_id, "mode": "command_status",
    })
    assert status == 200, polled
    assert polled["dispatch"]["dispatch_id"] == dispatch_id


def test_a_dispatch_for_an_unlinked_pc_is_refused(monkeypatch):
    """A dispatch can only bind a PC this owner currently has as an active link."""
    state = _state(
        monkeypatch, links=[_owner_link(NODE), _owner_link(SECOND_NODE)],
        mapping=_legacy_mapping(),
    )
    foreign = _pending_read_row()
    foreign.update({
        "dispatch_id": "dsp-foreign", "device_id": "device-foreign",
        "node_ref": "node-foreign",
    })
    state.history_store.rows["dsp-foreign"] = foreign
    status, body = _dispatch(state, {
        "subject_id": SUBJECT, "run_id": RUN,
        "dispatch_id": "dsp-foreign", "mode": "command_status",
    })
    assert status == 403
    assert body["error"]["code"] == "oracle_mesh_device_unverified"


def test_a_result_with_several_owner_links_uses_the_dispatch_node(monkeypatch):
    state = _state(
        monkeypatch, links=[_owner_link(NODE), _owner_link(SECOND_NODE)],
        mapping=_legacy_mapping(),
    )
    _seed_result(
        state, state_name="done", exit_code=0,
        body_bytes=READ_BODY.encode("utf-8"), termination="exited",
    )
    state.history_store.rows["dsp-read"].update(
        {"device_id": NODE, "node_ref": NODE},
    )
    status, body = _dispatch(state, {
        "subject_id": SUBJECT, "run_id": RUN,
        "dispatch_id": "dsp-read", "mode": "result",
    })
    assert status == 200, body
    assert body["dispatch"]["output"] == READ_BODY


def test_the_result_return_leg_projects_running_without_becoming_the_answer(monkeypatch):
    """The Engine also reports the step when it comes back with the result."""
    state = _state(monkeypatch)
    _seed_result(
        state, state_name="done", exit_code=0,
        body_bytes=READ_BODY.encode("utf-8"), termination="exited",
    )
    state.history_store.status_writes.clear()
    status, body = _dispatch(state, {
        "subject_id": SUBJECT, "run_id": RUN, "dispatch_id": "dsp-read",
        "mode": "result",
    })
    assert status == 200, body
    assert state.history_store.status_writes == [(OWNER, RUN, "running")]
    row = state.history_store.run_rows[RUN]
    assert row["status"] == "running", row
    # The raw bytes travel back on the dispatch row, never as the run's answer.
    assert row["result_summary"] is None, row


def test_a_completed_run_is_never_reopened_by_a_late_progress_step(monkeypatch):
    state = _state(monkeypatch)
    settled = state.history_store.run_rows[RUN]
    settled["status"] = "completed"
    settled["result_summary"] = "already sealed answer"
    status, body = _dispatch(state, _base_payload())
    assert status == 200, body
    assert state.history_store.status_writes == [(OWNER, RUN, "running")]
    assert settled["status"] == "completed", settled
    assert settled["result_summary"] == "already sealed answer", settled


def test_a_progress_write_failure_does_not_lose_the_pc_step(monkeypatch):
    """The answer must not depend on a status chip the user has not seen yet."""
    state = _state(monkeypatch)

    async def _unavailable(*args, **kwargs):
        raise RuntimeError("d1 write unavailable")

    state.history_store.update_claw_run_status = _unavailable
    status, body = _dispatch(state, _base_payload())
    assert status == 200, body
    assert body["dispatch"]["kind"] == "command"
    assert state.history_store.run_rows[RUN]["status"] == "pending"


def test_a_run_the_owner_does_not_have_gets_no_progress_write(monkeypatch):
    state = _state(monkeypatch)
    status, body = _dispatch(state, _base_payload(run_id="chat_pcq_" + "e" * 24))
    assert status == 404, body
    assert state.history_store.status_writes == []


@pytest.mark.parametrize("pending,valid_proof", [(True, True), (False, True), (True, False)])
def test_signed_stream_context_promotes_only_a_pending_owned_turn(monkeypatch, pending, valid_proof):
    # A genuine Engine tool choice may promote the stored ordinary user turn;
    # neither a browser request nor a signed request without that receipt may.
    monkeypatch.setattr(__import__(__name__, fromlist=["RUN"]), "RUN", "chat_pcq_" + "c" * 32)
    history = _History()
    history.run_rows.clear()
    promotions = []
    async def promote(**fields):
        promotions.append(fields)
        if not pending or fields["user_id"] != OWNER:
            return None
        row = {"run_id": RUN, "user_id": OWNER, "conversation_id": CONVERSATION,
               "workspace_id": WORKSPACE, "status": "pending", "action": fields["action"],
               "result_summary": None}
        history.run_rows[RUN] = row
        return row
    history.promote_chat_stream_pc_run = promote
    state = _state(monkeypatch, history)
    claim = {"version": 1, "requested": "files_list", "admitted": "files_list",
             "source": "declared", "ops": ["list"], "app_id": "padiem-chat"}
    request = _SignedRequest(state, _context_payload(), scope=claim)
    if not valid_proof:
        request.headers["X-Claw-Engine-Proof"] = "0" * 64
    response = asyncio.run(routes.oracle_mesh_engine_chat_files_call(request))
    body = json.loads(response.body)
    if not valid_proof:
        assert response.status_code == 401, body
        assert promotions == [] and history.run_rows == {}
    elif not pending:
        assert response.status_code == 404, body
        assert history.run_rows == {}
    else:
        assert response.status_code == 200, body
        assert len(promotions) == 1
        assert promotions[0]["action"] == "pc_files_query"
        assert history.scopes[(OWNER, RUN)] == claim
        assert history.rows == {}  # context selection never creates a dispatch
        denied = asyncio.run(routes.oracle_mesh_engine_chat_files_call(
            _SignedRequest(state, _base_payload(op="read", path="notes.txt"), scope=claim)))
        assert denied.status_code == 403, json.loads(denied.body)
        assert json.loads(denied.body)["error"]["code"] == "pc_scope_denied"
        assert history.rows == {}


def test_twenty_mb_pc_result_crosses_the_channel_body_parser():
    from starlette.requests import Request
    raw = b"a" * 20_000_000
    wire = {"dispatch_id": "dsp-read", "nonce": "n" * 32,
            "termination": "exited", "exit_code": 0,
            "content_utf8": raw.decode(), "content_bytes": len(raw),
            "content_sha256": hashlib.sha256(raw).hexdigest()}
    encoded = json.dumps(wire).encode()

    async def receive():
        return {"type": "http.request", "body": encoded, "more_body": False}

    request = Request({"type": "http", "method": "POST", "path": "/",
                       "headers": [(b"content-type", b"application/json"),
                                   (b"content-length", str(len(encoded)).encode())]}, receive)
    parsed, blob = asyncio.run(routes._read_result_body(request))
    assert blob is None
    assert routes._verified_read_result_text(
        {"root_ref": routes._PC_FILES_READ_ROOT_REF}, parsed,
    ) == raw.decode()
    assert routes._verified_read_result_text({"root_ref": "other"}, parsed) is not None
    # No PADIEM text ceiling remains (Owner decision 2026-10-28).
    assert routes._verified_result_text({}, parsed, max_bytes=routes._MAX_FILE_TEXT_BYTES) is not None


def test_a_twenty_five_mb_result_is_not_refused_without_a_product_cap():
    """Owner decision 2026-10-28: no PADIEM text ceiling — only the platform
    limit applies, so a 25MB verified result is accepted whole."""
    import hashlib as _hashlib
    text = "y" * 25_000_000
    raw = text.encode("utf-8")
    wire = {
        "content_utf8": text, "content_bytes": len(raw),
        "content_sha256": _hashlib.sha256(raw).hexdigest(),
    }
    assert routes._verified_read_result_text({"root_ref": "other-lane"}, wire) == text
    assert routes._verified_result_text({"root_ref": "other-lane"}, wire) == text
