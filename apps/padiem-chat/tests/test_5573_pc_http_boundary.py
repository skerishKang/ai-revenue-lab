"""#5573 (3-C-2) boundary: the orchestration surface and the model-tool PC entry.

These drive the real ``POST /api/orchestration`` route with a fake Engine
bridge and fake PC-context sources, so no provider, no Engine and no PC is
contacted. What they pin:

* a server-verified PC offers context to one Engine stream, where the model
  selects a tool; ordinary text creates no PC run;
* no wording decides that deferral, in either direction;
* an unverified PC, or a route without the ``tools`` capability, keeps the
  ordinary Engine turn and never reaches a PC plan;
* a browser-supplied target or recovery handle is never a plan, a target or a
  grant on this surface;
* the surface keeps no second PC executor, no second target store and no
  natural-language table that could drift back into a keyword gate.
"""

from __future__ import annotations

import httpx
import pytest

from types import SimpleNamespace

import app.chat_pc_drive as lane
import app.pc_work_context as pc_work_context
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.main import create_app
from app.orchestration_bridge import B62EngineOrchestrationBridge
from app.orchestration_routes import install_orchestration_routes
from app.pc_device_pairing_store import _NAME_SEPARATOR
# #8061: 공용 준비(상수·_wire·_client·_post)는 _support/pc_http_boundary가 소유한다.
from _support.pc_http_boundary import (
    DEVICE, LIST_ONLY, ORIGIN, OTHER_DEVICE, OWNER, PC_RUN, PC_TEXT, PLAIN_TEXT,
    SECOND, SESSION_SECRET, _Bridge, _Store, _client, _post, _settings, _wire)

def _two_linked_pcs(monkeypatch):
    """The account's pairing directory: two linked PCs, each answering to two names.

    The labels are in the form the label API stores (machine name, separator,
    owner alias), and the second node id carries the ``$`` MeshCentral really
    composes, so this boundary is proven against production-shaped values.
    """
    links = [
        {"mesh_node_id": DEVICE, "label": "Padiem-Command-Center" + _NAME_SEPARATOR + "컴1"},
        {"mesh_node_id": SECOND, "label": "K_lipvoice" + _NAME_SEPARATOR + "컴2"},
    ]

    async def _targets(request, owner_id):
        return links

    async def _resolve(request, **kwargs):
        chosen = kwargs.get("selected_device_id") or DEVICE
        return pc_work_context.PcWorkContext(
            broker_status="ready",
            devices=(
                pc_work_context.PcWorkDevice(DEVICE, None, "CONNECTED", True),
                pc_work_context.PcWorkDevice(
                    SECOND, "K_lipvoice" + _NAME_SEPARATOR + "컴2", "OFFLINE", False,
                ),
            ),
            execution=pc_work_context.PcExecutionTarget(
                status="ready", device_id=chosen, pinned=False,
            ),
            mapping="confirmed",
            selected_device_id=chosen,
            saved_selection_status=pc_work_context.SAVED_SELECTION_SELECTED,
        )

    monkeypatch.setattr(pc_work_context, "linked_pc_targets", _targets)
    monkeypatch.setattr(pc_work_context, "resolve_pc_work_context", _resolve)
    return links


@pytest.mark.parametrize("text", [
    "컴2의 C 드라이브 최상위 목록",
    "k_lipvoice의 C 드라이브 최상위 목록",
])
async def test_the_pc_named_in_the_turn_runs_on_the_stream_lane(monkeypatch, text):
    """#5573: the browser's stale target loses to this turn's words.

    The screen still points at 컴1 while the sentence asks for 컴2, so the
    address that arrives from the composer must neither choose the machine nor,
    by disagreeing with the name, withhold the PC tools altogether.
    """
    app, bridge, store = _wire(monkeypatch)
    _two_linked_pcs(monkeypatch)
    response = await _post(app, text, device_id=DEVICE, pc_run_id=PC_RUN)

    assert response.status_code == 200, response.text
    assert len(bridge.requests) == 1
    assert bridge.requests[0]["pc_tools"]["device_id"] == SECOND
    assert bridge.requests[0]["pc_tools"]["allowed_scopes"] == [
        "query_drives", "browser", "files_list", "files",
    ]


async def test_a_turn_naming_no_pc_keeps_the_saved_target_on_the_stream_lane(monkeypatch):
    """The name is an override, not a second way to lose the ordinary selection."""
    app, bridge, store = _wire(monkeypatch)
    _two_linked_pcs(monkeypatch)
    response = await _post(app, LIST_ONLY, device_id=DEVICE, pc_run_id=PC_RUN)

    assert response.status_code == 200, response.text
    assert bridge.requests[0]["pc_tools"]["device_id"] == DEVICE


def test_the_surface_keeps_no_pc_execution_path_of_its_own():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "app" / "orchestration_routes.py"
    ).read_text(encoding="utf-8")
    # The surface reads the one existing availability decision and nothing else:
    # no lane call, no plan, no target hint, no natural-language table.
    assert "from .chat_pc_drive import resolve_chat_pc_stream_context" in source
    assert "execute_chat_pc_drive_lane" not in source
    assert "agent_plan" not in source
    assert "tool_arguments" not in source
    assert "_CHAT_PC_MARKERS" not in source

def test_pc_error_cause_keeps_only_an_internal_code_below_503():
    """#5742's bounded-cause contract, on the envelope this lane now uses."""
    error = lane.ChatPCDriveError(
        "chat_pc_engine_unavailable", "failed", 400,
        cause="private-provider-response: " + "x" * 100,
    )
    assert error.public_error() == {
        "code": "chat_pc_engine_unavailable", "message": "failed",
    }


@pytest.mark.parametrize("code", [
    "chat_pc_run_id_unavailable", "chat_pc_identity_unavailable",
    "chat_pc_store_unavailable", "chat_pc_selection_unavailable",
    "chat_pc_files_unavailable", "chat_pc_engine_unavailable",
])
def test_pc_503_cause_keeps_the_chained_exception_class_and_safe_message(code):
    """#5742: a 503 keeps the exception class and a safe first line.

    ``chat_pc_decision_invalid`` and ``chat_pc_model_unavailable`` are dropped
    from this list because #5573 (3-C-2) removed the Chat-side decision and
    completion calls that could raise them; every code kept here is still
    reachable from the lane.
    """
    original = RuntimeError("D1_ERROR: database is locked")
    error = lane.ChatPCDriveError(code, "PC 작업을 완료하지 못했습니다.")
    error.__cause__ = original
    assert error.status_code == 503
    assert error.public_error()["cause"] == (
        "RuntimeError: D1_ERROR: database is locked"
    )


@pytest.mark.parametrize("message, private", [
    ("authorization: Bearer synthetic-private-token", "synthetic-private-token"),
    ("failed token=synthetic-private-token", "synthetic-private-token"),
    ("failed access_token=private-value", "private-value"),
    ("failed refresh_token=private-value", "private-value"),
    ("failed client_secret=private-value", "private-value"),
    ("failed api key=private-value", "private-value"),
    ("failed session_id=private-value", "private-value"),
    ("failed Bearer synthetic-private-token", "synthetic-private-token"),
    ("failed https://example.test/path?key=synthetic-private-token", "example.test"),
    ("failed 'private-file-content'", "private-file-content"),
    (r"failed C:\Users\private-user\private-file.txt", "private-user"),
    ("failed /home/private-user/private-file.txt", "private-user"),
    ("failed private-user@example.test", "private-user"),
    ("failed syntheticOpaqueCredential0123456789012345", "syntheticOpaqueCredential"),
    ("database locked\nprivate-second-line", "private-second-line"),
])
def test_pc_503_cause_redacts_private_values_before_truncation(message, private):
    error = lane.ChatPCDriveError("chat_pc_store_unavailable", "unavailable")
    error.__cause__ = RuntimeError(message)
    cause = error.public_error()["cause"]
    assert cause.startswith("RuntimeError: ")
    assert private not in cause
    assert len(cause.removeprefix("RuntimeError: ")) <= 120


def test_pc_503_cause_is_bounded_and_present_without_an_underlying_exception():
    error = lane.ChatPCDriveError(
        "chat_pc_store_unavailable", "database is locked; " * 20,
    )
    assert error.cause == "ChatPCDriveError: " + ("database is locked; " * 20)[:120]


@pytest.mark.parametrize("method", [
    "record_chat_pc_drive_run", "get_claw_run",
    "seal_run_terminal", "append_local_task_result",
])
async def test_a_store_failure_keeps_its_redacted_cause_on_the_tool_turn(
    monkeypatch, method,
):
    """#5742 on the #5573 entry: every lane failure stays diagnosable.

    The keyword route that used to produce this 503 is gone, so the same store
    seams are driven through a model-selected tool. Each one must still surface
    one 503 carrying the chained exception class and a redacted message.
    """
    app, bridge, store = _wire(monkeypatch)
    store.run_row = {
        "conversation_id": "chat_" + "s" * 32,
        "result_summary": "verified output",
        "action": "pc_files_query" if method == "seal_run_terminal"
                  else "pc_drive_query",
    }
    store.fail = method
    monkeypatch.setattr(lane, "auth_ready", lambda request: True)
    monkeypatch.setattr(lane, "current_user_id", lambda request: OWNER)
    request = SimpleNamespace(app=SimpleNamespace(state=app.state), cookies={})

    with pytest.raises(lane.ChatPCDriveError) as excinfo:
        await lane.execute_chat_pc_drive_lane(
            request, user_text=LIST_ONLY, skill=None, model_id="m",
            conversation_id=None, selected_tool="files",
        )

    error = excinfo.value
    assert error.status_code == 503
    assert error.public_error() == {
        "code": "chat_pc_store_unavailable",
        "message": "대화 기록을 현재 사용할 수 없습니다.",
        "cause": "RuntimeError: D1_ERROR: database is locked",
    }
    # A staging failure stops before the Engine; a result-leg failure does not.
    assert len(bridge.requests) == (0 if method == "record_chat_pc_drive_run" else 1)


async def test_a_lane_engine_503_retains_the_original_engine_code(monkeypatch):
    """The engine's own code survives inside the redacted cause."""
    from app.orchestration_bridge import B62OrchestrationError

    app, bridge, store = _wire(monkeypatch)

    async def fail(**fields):
        raise B62OrchestrationError(
            "upstream_unavailable", "AI unavailable", status_code=503,
        )

    bridge.start = fail
    monkeypatch.setattr(lane, "auth_ready", lambda request: True)
    monkeypatch.setattr(lane, "current_user_id", lambda request: OWNER)
    request = SimpleNamespace(app=SimpleNamespace(state=app.state), cookies={})

    with pytest.raises(lane.ChatPCDriveError) as excinfo:
        await lane.execute_chat_pc_drive_lane(
            request, user_text=LIST_ONLY, skill=None, model_id="m",
            conversation_id=None, selected_tool="files",
        )

    assert excinfo.value.status_code == 503
    assert excinfo.value.public_error()["cause"] == (
        "B62OrchestrationError: upstream_unavailable: AI unavailable"
    )


async def test_invalid_stream_recovery_handle_is_refused_before_any_engine_or_history_call(monkeypatch):
    app, bridge, store = _wire(monkeypatch)
    response = await _post(app, PLAIN_TEXT, pc_run_id="noncanonical")
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "invalid_request"
    assert bridge.requests == [] and store.pending_turns == [] and store.staged == []


async def test_resumed_stream_appends_only_the_answer_to_the_original_user_turn(monkeypatch):
    app, bridge, store = _wire(monkeypatch)
    calls = []
    async def resume(**fields):
        return SimpleNamespace(stream_run_id=PC_RUN, conversation_id="chat_saved", answer="resumed",
            user_text=PLAIN_TEXT, orchestration={"events": [], "approval_pause": None}, decision_status=None)
    async def finish(**fields):
        calls.append(fields)
        return "chat_saved"
    async def forbidden_exchange(*args, **kwargs):
        raise AssertionError("the already stored user turn must not be appended again")
    bridge.resume = resume
    store.finish_chat_stream_turn = finish
    store.append_exchange = forbidden_exchange
    async with _client(app) as client:
        response = await client.post("/api/orchestration/resume", headers={"Origin": ORIGIN}, json={
            "continuationRef": "cont_abcdefgh12345678", "pauseId": "pause_1", "outcome": "approved", "requiresTrustedDecision": True})
    assert response.status_code == 200, response.text
    assert response.json()["answer"] == "resumed"
    assert calls == [{"user_id": OWNER, "run_id": PC_RUN, "answer": "resumed"}]


async def test_stream_user_turn_store_failure_preserves_only_the_existing_redacted_cause(monkeypatch):
    app, bridge, store = _wire(monkeypatch)
    async def fail(**fields):
        raise RuntimeError("database locked token=synthetic-private-token")
    store.begin_chat_stream_turn = fail
    # The staged-turn machinery is PC-branch behavior; an explicit PC turn
    # reaches it (a general question never enters this branch since #6686).
    response = await _post(app, PC_TEXT, pc_run_id=PC_RUN)
    assert response.status_code == 503, response.text
    error = response.json()["error"]
    assert error["code"] == "chat_pc_store_unavailable"
    assert error["cause"].startswith("RuntimeError: database locked")
    assert "synthetic-private-token" not in response.text
    assert bridge.requests == [] and store.staged == []


async def test_orchestration_terminal_error_marks_its_owner_pc_run_failed(monkeypatch):
    from app.orchestration_bridge import B62OrchestrationError
    app, bridge, store = _wire(monkeypatch)
    settled = []
    async def update(user_id, run_id, status):
        settled.append((user_id, run_id, status))
        return True
    async def failed_stream(**fields):
        raise B62OrchestrationError("upstream_auth_error", "safe error", status_code=403)
        yield
    store.update_claw_run_status = update
    bridge.start_stream = failed_stream
    async with _client(app) as client:
        response = await client.post("/api/orchestration", json={
            "messages": [{"role": "user", "content": PC_TEXT}],
            "tier": "free", "pc_run_id": PC_RUN,
        })
    assert response.status_code == 200
    assert "event: error" in response.text
    assert settled == [(OWNER, PC_RUN, "failed")]
    assert not store.answers
