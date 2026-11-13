"""App session authority, confirmation and one-shot inputs without a real PC."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app import chat_pc_session as lane
from app import mcp_gateway_session as transport
from test_7065_pc_session_tools import rig, UID, DEVICE, IDENTITY, call as mcp_call

CID = "chat_" + "9" * 32


@pytest.fixture
def app_rig(rig, monkeypatch):
    request, history, helper, queue = rig
    request.app.state.settings.chat_pc_session_enabled = True
    history.messages, history.notices = [], []
    history.conversations = {CID, "chat_" + "8" * 32}
    request.app.state.fixture_user = UID

    async def verify(req):
        return SimpleNamespace(session_id="session_fixture", tenant_id="workspace"), None

    async def workspace(*args):
        return "workspace"

    async def conversation(uid, cid, **kwargs):
        return {"id": cid} if uid == UID and cid in history.conversations else None

    async def stage(**fields):
        cid = fields["conversation_id"] or CID
        history.runs[fields["run_id"]] = {**fields, "conversation_id": cid}
        history.messages.append({"role": "user", "content": fields["user_text"], "conversation_id": cid})
        return cid

    async def begin(**fields):
        return await stage(**fields)

    async def record(**fields):
        history.runs[fields["run_id"]] = {**fields, "created_at": datetime.now(timezone.utc).isoformat()}

    async def run(uid, rid):
        value = history.runs.get(rid)
        return value if value and value["user_id"] == uid else None

    async def recent(uid, **kwargs):
        return [v for v in reversed(list(history.runs.values())) if v["user_id"] == uid]

    async def context(uid, cid, **kwargs):
        return {"messages": [m for m in history.messages if m["conversation_id"] == cid]}

    async def private_turn(*, user_id, run_id):
        row = await run(user_id, run_id)
        if row is None:
            return None
        rows = [m for m in history.messages if m["conversation_id"] == row["conversation_id"]]
        return rows[-1]["content"] if rows else None

    async def consume(uid, rid, *, action):
        value = await run(uid, rid)
        if value and value.get("action") == action and value.get("status") == "waiting_approval":
            value["status"] = "cancelled"
            return True
        return False

    async def notice(**fields):
        history.notices.append(fields)
        return True

    async def memory(method, *, ref, text=None):
        if method == "take_desktop_text":
            return await queue.take_desktop_text(ref=ref)
        assert method == "deposit_desktop_text"
        queue.values[ref] = text
        return True

    from app import auth_routes, claw_connector_enrollment_routes, oracle_mesh_read_return_routes
    monkeypatch.setattr(claw_connector_enrollment_routes, "_verified_owner_request", verify)
    monkeypatch.setattr(auth_routes, "current_user_id", lambda req: req.app.state.fixture_user)
    monkeypatch.setattr(oracle_mesh_read_return_routes, "_dispatch_workspace_id", workspace)
    monkeypatch.setattr(history, "record_chat_pc_drive_run", stage)
    monkeypatch.setattr(history, "get_conversation", conversation, raising=False)
    monkeypatch.setattr(history, "get_claw_run", run, raising=False)
    monkeypatch.setattr(history, "begin_chat_stream_turn", begin, raising=False)
    monkeypatch.setattr(history, "record_claw_run", record, raising=False)
    monkeypatch.setattr(history, "list_recent_claw_runs", recent, raising=False)
    monkeypatch.setattr(history, "get_conversation_model_context", context, raising=False)
    monkeypatch.setattr(history, "read_pc_session_confirmation_turn", private_turn, raising=False)
    monkeypatch.setattr(history, "consume_pc_command_confirmation", consume, raising=False)
    monkeypatch.setattr(history, "append_step_result_message", notice, raising=False)
    monkeypatch.setattr(queue, "call", memory)
    return rig


def turn(rig, text, *, cid=CID, **options):
    response = asyncio.run(lane.handle_owner_turn(rig[0], user_text=text, conversation_id=cid,
                                                  selected_device=DEVICE, **options))
    return None if response is None else json.loads(response.body)


def opened(rig):
    result = turn(rig, "PC 세션 시작 `python`")
    assert result["pc_session"]["ok"] is True, result
    return result["pc_session"]["job_id"]


def card(rig, job, **fields):
    request = Request({"type": "http", "method": "POST", "path": lane.API_PATH,
                       "headers": [(b"content-type", b"application/json")], "app": rig[0].app})
    request._body = json.dumps({"conversation_id": CID, "op": "input", "job_id": job, **fields}).encode()
    response = asyncio.run(lane.session_card_request(request))
    return json.loads(response.body)


def test_start_input_read_stop_and_reload_handle_use_shared_transport(app_rig):
    job = opened(app_rig)
    assert job in app_rig[1].notices[0]["content"]
    result = card(app_rig, job, text="owner input")
    assert result["pc_session"]["output"] == "owner input\n"
    assert result["conversation_id"] == CID
    assert card(app_rig, job, op="read", offset=0)["pc_session"]["output"].startswith("prompt>")
    assert card(app_rig, job, key="enter")["pc_session"]["ok"] is True
    assert card(app_rig, job, op="stop")["pc_session"]["alive"] is False
    assert all(run["conversation_id"] == CID for run in app_rig[1].runs.values())
    assert all(run["action"] == "pc_session" for run in app_rig[1].runs.values())


@pytest.mark.parametrize("value", ["a" * 201, "first\nsecond", "first\n`literal`"])
def test_long_card_reconstructs_server_payload_and_consumes_once(app_rig, value):
    job = opened(app_rig)
    before = len(app_rig[2].operations)
    staged = card(app_rig, job, text=value, enter=False, offset=0)
    assert staged["decision_status"] == "pc_session_confirm"
    assert len(app_rig[2].operations) == before
    result = turn(app_rig, "네")
    assert value in result["pc_session"]["output"]
    assert app_rig[2].operations[-1]["enter"] is False
    assert turn(app_rig, "네") is None
    assert len(app_rig[2].operations) == before + 1


def test_start_card_pins_original_pc_and_owner_turn(app_rig):
    value = "x" * 201
    assert turn(app_rig, "PC 세션 시작 cmd `" + value + "`")["decision_status"] == "pc_session_confirm"
    result = turn(app_rig, "네")
    assert result["pc_session"]["ok"] is True
    assert app_rig[2].operations[0]["shell"] == "cmd"


@pytest.mark.parametrize("change", ["owner", "conversation", "workspace", "origin", "operation"])
def test_followup_requires_app_origin_same_owner_conversation_workspace(app_rig, change):
    job = opened(app_rig)
    row = app_rig[1].rows[job]
    run = app_rig[1].runs[row["run_id"]]
    if change == "owner":
        app_rig[0].app.state.fixture_user = "usr_" + "f" * 32
    elif change == "conversation":
        run["conversation_id"] = "chat_" + "8" * 32
    elif change == "workspace":
        run["workspace_id"] = "other"
    elif change == "origin":
        run["action"] = "pc_files_query"
    else:
        row["job_operation"] = None
    assert card(app_rig, job, text="forbidden")["error"]["code"] == "pc_session_not_found"
    assert len(app_rig[2].operations) == 1 and not app_rig[3].values


def test_mcp_tokens_still_require_their_own_receipt(app_rig):
    job = opened(app_rig)
    result = mcp_call(app_rig, "pc_shell_input", {"job_id": job, "text": "forbidden"},
                      identity={**IDENTITY, "token_id": "mcp_" + "f" * 32})
    assert result["status"] == "denied"
    assert len(app_rig[2].operations) == 1


def test_failed_secret_probe_keeps_unconsumed_card_and_one_owner_turn(app_rig):
    job = opened(app_rig)
    app_rig[2].features.append("secret_mask")
    before = len(app_rig[1].messages)
    staged = card(app_rig, job, text="x" * 201, secret=True)
    assert staged["decision_status"] == "pc_session_confirm"
    assert len(app_rig[1].messages) == before + 1
    app_rig[2].error = "user_session_unavailable"
    denied = turn(app_rig, "네")
    assert denied["pc_session"]["code"] == "user_session_unavailable"
    assert len(app_rig[1].messages) == before + 1
    assert len(app_rig[3].values) == 1
    app_rig[2].error = None
    accepted = turn(app_rig, "네")
    assert accepted["pc_session"]["ok"] is True
    # The actual input adds one length-only owner record; both capability
    # probes add only existing run/result records.
    assert len(app_rig[1].messages) == before + 2
    assert sum(op["op"] == "input" for op in app_rig[2].operations) == 1


def test_start_handle_survives_a_failed_extra_reload_notice(app_rig, monkeypatch):
    async def fail(**kwargs):
        raise RuntimeError("notice unavailable")
    monkeypatch.setattr(app_rig[1], "append_step_result_message", fail)
    result = turn(app_rig, "PC 세션 시작 `python`")
    assert result["pc_session"]["ok"] is True
    assert result["pc_session"]["job_id"].startswith("dsp_")
    assert result["pc_session"]["history_notice_saved"] is False


def test_secret_value_taken_for_confirmation_is_revalidated(app_rig):
    job = opened(app_rig)
    app_rig[2].features.append("secret_mask")
    card(app_rig, job, text="a" * 201, secret=True)
    reference = next(iter(app_rig[3].values))
    app_rig[3].values[reference] = "\r" + "a" * 200
    result = turn(app_rig, "네")
    assert result["error"]["code"] == "pc_session_bad_request"
    assert not any(op["op"] == "input" for op in app_rig[2].operations)


@pytest.mark.parametrize("text", ["PC 세션: 내 PC에서 `echo fixture` 실행해",
    "PC세션: 내 PC에서 `echo fixture` 실행해", "PC 세션 시작 python", "PC 세션 시작 `one` `two`",
    "PC 세션 비밀 입력 `fixture-private`", "PC 세션 secret `fixture-private`"])
def test_reserved_malformed_or_secret_chat_never_dispatches(app_rig, text):
    assert turn(app_rig, text)["error"]["code"] == "pc_session_bad_request"
    assert not app_rig[1].runs and not app_rig[1].staged


def test_model_or_previous_owner_turn_cannot_authorize_a_session(app_rig):
    assert turn(app_rig, "PC 세션 시작 `python`", owner_turn=False)["error"]["code"] == "pc_session_owner_turn_required"
    assert turn(app_rig, "일반 답변", owner_turn=False) is None
    assert not app_rig[1].runs


@pytest.mark.parametrize("flag", ["chat_pc_session_enabled", "mcp_pc_session_enabled",
    "mcp_pc_shell_enabled", "mcp_pc_shell_user_mode_enabled"])
def test_default_off_and_each_transport_gate_withhold_api(app_rig, flag):
    setattr(app_rig[0].app.state.settings, flag, False)
    result = card(app_rig, "dsp_" + "a" * 32, text="not sent")
    assert result["error"]["code"] == "pc_session_disabled"
    if flag == "chat_pc_session_enabled":
        assert turn(app_rig, "PC 세션 시작 `python`") is None
    assert not app_rig[1].staged


def test_csrf_denial_happens_before_staging_or_deposit(app_rig, monkeypatch):
    from app import claw_connector_enrollment_routes
    async def deny(request):
        return None, lane._error("connector_enrollment_csrf_denied", 403)
    monkeypatch.setattr(claw_connector_enrollment_routes, "_verified_owner_request", deny)
    assert turn(app_rig, "PC 세션 시작 `python`")["error"]["code"] == "connector_enrollment_csrf_denied"
    assert not app_rig[1].runs and not app_rig[3].values


@pytest.mark.parametrize("enter", [True, False])
@pytest.mark.parametrize("expire", [False, True])
def test_secret_confirmation_memory_only_then_once_or_expired(app_rig, enter, expire):
    job = opened(app_rig)
    app_rig[2].features.append("secret_mask")
    value = "fixture-private-\n" + "x" * 205
    result = card(app_rig, job, text=value, secret=True, enter=enter)
    assert result["decision_status"] == "pc_session_confirm"
    assert len(app_rig[3].values) == 1
    records = json.dumps(app_rig[1].runs) + json.dumps(app_rig[1].messages) + repr(result)
    assert value not in records and base64.b64encode(value.encode()).decode() not in records
    assert hashlib.sha256(value.encode()).hexdigest()[:8] not in records
    if expire:
        app_rig[3].values.clear()
    confirmed = turn(app_rig, "네")
    if expire:
        assert confirmed["error"]["code"] == "pc_session_input_expired"
        assert not any(op["op"] == "input" for op in app_rig[2].operations)
    else:
        assert confirmed["pc_session"]["output"].startswith("[masked]")
        assert app_rig[2].operations[-1]["enter"] is enter
    assert turn(app_rig, "네") is None
    assert not app_rig[3].values


def test_old_helper_blocks_secret_card_before_any_deposit(app_rig):
    job = opened(app_rig)
    assert card(app_rig, job, text="x" * 201, secret=True)["pc_session"]["code"] == "pc_session_unsupported"
    assert not app_rig[3].values
    assert not any(row.get("status") == "waiting_approval" for row in app_rig[1].runs.values())


def test_short_secret_never_enters_history_or_exceptions(app_rig, monkeypatch, caplog):
    job = opened(app_rig)
    app_rig[2].features.append("secret_mask")
    value = "fixture-private"
    assert card(app_rig, job, text=value, secret=True)["pc_session"]["output"] == "[masked]\n"
    records = json.dumps(app_rig[1].runs) + json.dumps(app_rig[1].messages) + caplog.text
    assert value not in records and base64.b64encode(value.encode()).decode() not in records
    async def fail(*args, **kwargs):
        raise RuntimeError(value)
    monkeypatch.setattr(transport, "execute_authorized_session", fail)
    result = card(app_rig, job, text=value, secret=True)
    assert value not in json.dumps(result) + caplog.text


def test_closed_bounds_and_unknown_browser_options(app_rig):
    job = opened(app_rig)
    for fields in ({"text": "x" * 4001}, {"text": "\0"}, {"text": "\r"}, {"text": "x", "wait_ms": 10001},
                   {"text": "x", "confirmed": True}, {"op": "start", "command": "python"},
                   {"text": "x", "device_id": DEVICE}):
        assert card(app_rig, job, **fields)["error"]["code"] == "pc_session_bad_request"
    assert len(app_rig[2].operations) == 1
