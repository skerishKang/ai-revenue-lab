"""R7-6 claw_general_execute PC 구간 골든 표 (#7814).

리팩터 전후로 PC 분기(데스크톱·화면·통제·장치·확인 턴·명령·브라우저·
목록·자연 조회·TXT·PC 문맥)의 응답, 대역 호출 순서, 넘어가는 PC 문맥
묶음을 같은 값으로 고정한다. 가짜 값만 쓴다.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.requests import Request
from starlette.responses import JSONResponse

from app import central_model_route_runtime as cmr
from app import claw_general_routes as g
from app import claw_memory_routes
from app import pc_work_context as pc_ctx
from app import pc_browser_intent
from app import pc_command_confirmation
from _support.claw_general_modules import patch_bound

GOLDEN_PATH = (
    Path(__file__).resolve().parent
    / "test_7814_claw_general_pc_branches_table_golden.json"
)
DEVICE = "dev-fixture-1"
OTHER_DEVICE = "dev-fixture-2"


def _run(coro):
    return asyncio.run(coro)


def _req(payload):
    raw = json.dumps(payload).encode()
    app = SimpleNamespace(state=SimpleNamespace(
        settings=SimpleNamespace(runtime_mode="mock", session_secret="x", auth_mode="off"),
        history_store=object(),
    ))
    scope = {"type": "http", "method": "POST", "path": "/api/claw/general",
             "app": app, "headers": [(b"content-type", b"application/json")]}

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}

    return Request(scope, receive=receive)


def _resp(response):
    body = response.body if isinstance(response.body, (bytes, bytearray)) else b""
    try:
        parsed = json.loads(body)
    except Exception:
        parsed = body.decode("utf-8", errors="replace")
    return {
        "status": response.status_code,
        "body": parsed,
        "media_type": response.media_type,
    }


def _pc_context(*, selected=DEVICE, confirmed=True, ready=True,
                devices=((DEVICE, "ONLINE", True),), tool=True,
                execution_device=DEVICE):
    return SimpleNamespace(
        devices=tuple(
            SimpleNamespace(device_id=d, state=s, usable=u) for d, s, u in devices
        ),
        selected_device_id=selected,
        selected_confirmed=confirmed,
        execution=SimpleNamespace(ready=ready, device_id=execution_device),
        tool_available=tool,
        execution_device_id=execution_device if ready else None,
    )


def _setup(monkeypatch, calls, *, mode="none", device=None, confirmed_command=None,
           confirmed_value=None, saved_status=pc_ctx.SAVED_SELECTION_NONE,
           saved_device=None, pc_context=None, preflight_error=None,
           typing_eligible=True, command_eligible=True, attachment_conflict=None,
           authenticated=True):
    text = "fixture turn"
    payload = {"messages": [{"role": "user", "content": text}]}
    if device is not None:
        payload["device_id"] = device

    async def fake_intake(request):
        del request
        return None, {
            "turn_started": 0.0, "data": payload, "user_text": text,
            "document_context": None, "attachment_conflict": attachment_conflict,
        }

    async def fake_session_custom(*args, **kwargs):
        del args, kwargs
        return None, {}

    async def fake_desktop(request, *, user_text, desktop_op, data, **kwargs):
        calls.append(["desktop", desktop_op, kwargs.get("pending_copy")])
        return JSONResponse({"lane": "desktop", "op": desktop_op}, status_code=200)

    async def fake_stage_desktop(request, *, user_text, value, data):
        calls.append(["stage_desktop", value])
        return JSONResponse({"lane": "stage_desktop", "value": value}, status_code=200)

    async def fake_command(request, *, user_text, command, data):
        calls.append(["command", command])
        return JSONResponse({"lane": "command", "command": command}, status_code=200)

    async def fake_stage_command(request, *, user_text, command, data):
        calls.append(["stage_command", command])
        return JSONResponse({"lane": "stage_command", "command": command}, status_code=200)

    async def fake_txt(request, *, user_text, path_relative, data):
        calls.append(["txt", path_relative])
        return JSONResponse({"lane": "txt", "path": path_relative}, status_code=200)

    async def fake_confirmed_command(request, user_text, data):
        calls.append(["check_confirmed_command"])
        return confirmed_command

    async def fake_confirmed_type(request, user_text, data):
        calls.append(["check_confirmed_type"])
        return confirmed_value

    patch_bound(monkeypatch, "_claw_general_intake", fake_intake)
    patch_bound(monkeypatch, "_claw_general_session_custom", fake_session_custom)
    patch_bound(monkeypatch, "_dispatch_user_desktop_request", fake_desktop)
    patch_bound(monkeypatch, "_stage_desktop_type_confirmation", fake_stage_desktop)
    patch_bound(monkeypatch, "_dispatch_user_command_request", fake_command)
    patch_bound(monkeypatch, "_stage_pc_command_confirmation", fake_stage_command)
    patch_bound(monkeypatch, "_dispatch_user_txt_request", fake_txt)
    patch_bound(monkeypatch, "_confirmed_staged_pc_command", fake_confirmed_command)
    patch_bound(monkeypatch, "_confirmed_staged_desktop_type", fake_confirmed_type)

    patch_bound(monkeypatch, "_requested_local_desktop", lambda text: (
        mode in ("desktop", "desktop_type"), "desktop:type\nhello" if mode == "desktop_type" else "whoami"))
    patch_bound(monkeypatch, "_requested_read_only_screen_view", lambda text: mode == "screen")
    patch_bound(monkeypatch, "_requested_desktop_control", lambda text: (
        mode in ("control", "control_type"), "desktop:type\nhello" if mode == "control_type" else "desktop:capture"))
    patch_bound(monkeypatch, "_requested_desktop_task", lambda text: mode == "task")
    patch_bound(monkeypatch, "explicit_pc_instruction", lambda text: mode == "screen")
    patch_bound(monkeypatch, "_requested_local_command", lambda text: (
        mode == "command", "whoami"))
    patch_bound(monkeypatch, "_requested_natural_pc_files", lambda text: mode == "files")
    patch_bound(monkeypatch, "_requested_natural_pc_query", lambda text: (
        mode == "natural", "Get-PSDrive -PSProvider FileSystem"))
    patch_bound(monkeypatch, "_requested_local_txt_path", lambda text: (
        mode == "txt", "notes/report.txt"))
    patch_bound(monkeypatch, "direct_typing_eligible", lambda value: typing_eligible)
    monkeypatch.setattr(pc_command_confirmation, "direct_command_eligible", lambda text, command: command_eligible)
    monkeypatch.setattr(pc_browser_intent, "requested_pc_browser", lambda text, records=(): mode == "browser")
    patch_bound(monkeypatch, "_desktop_exception_question", lambda text: (
        "정말 실행할까요?" if mode == "control" else None))

    async def fake_ref(request, data):
        calls.append(["intake_ref"])
        return "chat_fixture_conversation", None

    patch_bound(monkeypatch, "_resolve_intake_session_reference", fake_ref)
    patch_bound(monkeypatch, "_claw_stage", lambda *args, **kwargs: None)

    async def fake_preflight(request, data, user_text, turn_started):
        calls.append(["preflight"])
        if preflight_error is not None:
            return preflight_error, None
        return None, {
            "grade": SimpleNamespace(tier_id="free"),
            "requested_tier": "free", "admin_lane": False,
            "product_tier": "free", "identity_tier_id": None,
            "claw_route": SimpleNamespace(fallback_model_id=None),
            "central_route_model_id": "model.fixture",
            "conversation_id": None, "adapter": None,
            "has_identity_lane": False, "model_user_text": text,
            "b54_session": None, "drive_result": (None, []),
        }

    patch_bound(monkeypatch, "_claw_general_route_preflight", fake_preflight)
    patch_bound(monkeypatch, "current_user_id", lambda request: "owner_fixture")
    patch_bound(monkeypatch, "auth_ready", lambda request: authenticated)

    async def fake_workspace(request, uid):
        calls.append(["workspace", uid])
        return "ws_fixture"

    monkeypatch.setattr(claw_memory_routes, "_resolve_memory_workspace", fake_workspace)

    async def fake_saved(request, *, owner_id, workspace_id):
        calls.append(["saved_selection", owner_id, workspace_id, saved_status, saved_device])
        return SimpleNamespace(status=saved_status, device_id=saved_device)

    async def fake_resolve(request, **kwargs):
        calls.append(["resolve_pc_context", kwargs])
        return pc_context if pc_context is not None else _pc_context()

    def fake_render(context):
        calls.append(["render_pc_context", context.selected_confirmed])
        return "PC_WORK_CONTEXT"

    monkeypatch.setattr(pc_ctx, "read_saved_device_selection", fake_saved)
    monkeypatch.setattr(pc_ctx, "resolve_pc_work_context", fake_resolve)
    monkeypatch.setattr(pc_ctx, "render_pc_work_context", fake_render)
    patch_bound(monkeypatch, "_start_selectable_model_read", lambda request, mid: (None, False))

    async def fake_usage(request):
        calls.append(["usage_gate"])
        return JSONResponse({"stop": "quota"}, status_code=200)

    patch_bound(monkeypatch, "_usage_gate_denial", fake_usage)

    async def fake_reserve(request, **kwargs):
        calls.append(["reserve_first_turn"])
        return None

    patch_bound(monkeypatch, "reserve_first_turn_grant", fake_reserve)
    return payload


CASES = [
    ("desktop_direct", {"mode": "desktop"}),
    ("desktop_type_confirm", {"mode": "desktop_type", "typing_eligible": False}),
    ("screen", {"mode": "screen"}),
    ("control_question", {"mode": "control"}),
    ("control_type_confirm", {"mode": "control_type", "typing_eligible": False}),
    ("desktop_task_capture", {"mode": "task"}),
    ("device_invalid", {"mode": "none", "device": "bad id"}),
    ("confirmed_command", {"mode": "none", "confirmed_command": "whoami"}),
    ("confirmed_type", {"mode": "none", "confirmed_value": "hello"}),
    ("command_direct", {"mode": "command"}),
    ("command_stage", {"mode": "command", "command_eligible": False}),
    ("browser", {"mode": "browser", "device": DEVICE}),
    ("files", {"mode": "files", "device": DEVICE}),
    ("natural_drive", {"mode": "natural", "device": DEVICE}),
    ("txt", {"mode": "txt"}),
    ("stale_selection", {"mode": "files", "device": DEVICE,
                         "saved_status": pc_ctx.SAVED_SELECTION_SELECTED,
                         "saved_device": OTHER_DEVICE}),
    ("revoked", {"mode": "files", "device": DEVICE,
                 "saved_status": pc_ctx.SAVED_SELECTION_SELECTED,
                 "saved_device": DEVICE,
                 "pc_context": _pc_context(devices=((DEVICE, "REVOKED", True),))}),
    ("target_unavailable", {"mode": "files", "device": DEVICE,
                            "pc_context": _pc_context(confirmed=False, ready=False)}),
    ("target_mismatch", {"mode": "files", "device": DEVICE,
                         "pc_context": _pc_context(confirmed=False)}),
    ("browser_auto_target", {"mode": "browser",
                             "pc_context": _pc_context(selected=None)}),
    ("no_authenticated_owner", {"mode": "task", "authenticated": False}),
    ("other_owner_scope", {"mode": "none",
                           "preflight_error": JSONResponse(
                               {"code": "canonical_b54_session_unavailable"},
                               status_code=403)}),
    ("saved_unavailable", {"mode": "files",
                           "saved_status": pc_ctx.SAVED_SELECTION_UNAVAILABLE}),
]


def _golden():
    if not GOLDEN_PATH.exists():
        return {"cases": []}
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def _write_golden(document):
    GOLDEN_PATH.write_text(json.dumps(
        document, ensure_ascii=False, indent=2,
    ) + "\n", encoding="utf-8")


def test_branches_table_parseable():
    golden = _golden()
    if os.environ.get("UPDATE_7814_GOLDEN") == "1":
        return
    assert [c["name"] for c in golden["cases"]] == [c[0] for c in CASES]


def test_branches_table_is_identical_to_golden(monkeypatch):
    golden = {c["name"]: c for c in _golden()["cases"]}
    for name, kwargs in CASES:
        calls = []
        payload = _setup(monkeypatch, calls, **kwargs)
        response = _run(g.claw_general_execute(_req(payload)))
        got = json.loads(json.dumps(
            {"name": name, "resp": _resp(response), "calls": calls},
            ensure_ascii=False,
        ))
        if os.environ.get("UPDATE_7814_GOLDEN") == "1":
            golden[name] = got
            continue
        assert got == golden[name], name
    if os.environ.get("UPDATE_7814_GOLDEN") == "1":
        document = _golden()
        document["cases"] = [golden[name] for name, _ in CASES]
        _write_golden(document)


def test_two_pc_context_consumers_receive_the_same_bundle(monkeypatch):
    """The PC-context helper's inputs are exactly the branch helper's outputs."""

    seen = []
    real = g._claw_general_pc_work_context

    async def capture(request, **kwargs):
        seen.append(kwargs)
        return await real(request, **kwargs)

    patch_bound(monkeypatch, "_claw_general_pc_work_context", capture)
    for name, kwargs in (("files", {"mode": "files", "device": DEVICE}),
                         ("browser", {"mode": "browser", "device": DEVICE})):
        calls = []
        payload = _setup(monkeypatch, calls, **kwargs)
        _run(g.claw_general_execute(_req(payload)))
    assert len(seen) == 2
    for bundle in seen:
        assert bundle == {
            "initial_pc_drive_query": False,
            "pc_files_requested": bundle["pc_files_requested"],
            "pc_browser_requested": bundle["pc_browser_requested"],
            "desktop_device_id": None,
            "pc_files_device_id": DEVICE if bundle["pc_files_requested"] else None,
            "pc_browser_device_id": DEVICE if bundle["pc_browser_requested"] else None,
            "canonical_session_id": None,
        }
        assert bundle["pc_files_requested"] != bundle["pc_browser_requested"]


def _real_confirmation_snapshot(monkeypatch):
    """One staged card, its affirmative turn, and the real Mesh dispatch call."""

    import test_pc_screen_view_s1_261102 as harness
    from app import oracle_mesh_read_return_routes as mesh_routes

    state = harness._state()
    history = state.history_store
    calls = []
    run_numbers = iter(range(1, 20))
    patch_bound(monkeypatch, "create_claw_run", lambda *args, **kwargs: SimpleNamespace(
            run_id=f"run_fixture_{next(run_numbers)}"
        ))
    monkeypatch.setattr(
        mesh_routes.uuid, "uuid4", lambda: SimpleNamespace(hex="c" * 32),
    )

    async def record(**fields):
        calls.append(["stage", {
            "action": fields.get("action"),
            "conversation_id": fields.get("conversation_id"),
            "run_id": fields["run_id"],
            "status": fields.get("status"),
            "user_id": fields["user_id"],
            "user_text": fields["user_text"],
            "workspace_id": fields["workspace_id"],
        }])
        history.staged.append({
            **fields,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "title": "Chat: " + fields["user_text"],
        })
        return harness.CONVERSATION

    async def list_recent(uid, limit=10):
        calls.append(["list_pending_cards", uid, limit])
        return [
            {
                "run_id": row["run_id"],
                "action": row.get("action"),
                "status": row.get("status"),
                "title": row["title"],
                "conversation_id": harness.CONVERSATION,
                "created_at": row["created_at"],
            }
            for row in history.staged if row.get("action") == "pc_command"
        ]

    async def context(uid, conversation_id, *, product_scope):
        calls.append(["read_staged_turn", uid, conversation_id, product_scope])
        staged = next(
            row for row in history.staged if row.get("action") == "pc_command"
        )
        return {
            "id": conversation_id,
            "messages": [{"role": "user", "content": staged["user_text"]}],
        }

    async def consume(uid, run_id):
        calls.append(["consume_card", uid, run_id])
        row = next(
            (row for row in history.staged
             if row["run_id"] == run_id and row.get("action") == "pc_command"
             and row.get("status") == pc_command_confirmation.STATUS_AWAITING_CONFIRMATION),
            None,
        )
        if row is None:
            return False
        row["status"] = "cancelled"
        return True

    original_get_run = history.get_claw_run
    original_correlation = history.get_local_task_correlation
    original_dispatch = history.create_oracle_mesh_dispatch

    async def get_run(uid, run_id):
        calls.append(["read_dispatch_run", uid, run_id])
        return await original_get_run(uid, run_id)

    async def correlation(uid, run_id):
        calls.append(["read_dispatch_correlation", uid, run_id])
        return await original_correlation(uid, run_id)

    async def create_dispatch(**fields):
        recorded = dict(fields)
        recorded["expires_at"] = "<bounded>"
        calls.append(["create_dispatch", recorded])
        return await original_dispatch(**fields)

    history.record_txt_pending_run = record
    history.list_recent_claw_runs = list_recent
    history.get_conversation_model_context = context
    history.consume_pc_command_confirmation = consume
    history.get_claw_run = get_run
    history.get_local_task_correlation = correlation
    history.create_oracle_mesh_dispatch = create_dispatch

    staged_turn = "문서 초안입니다.\n내 PC에서 `whoami` 실행해"
    card = harness._run_route(monkeypatch, state, question=staged_turn)
    assert card.status_code == 200
    assert history.rows == {}
    assert history.staged[0]["status"] == (
        pc_command_confirmation.STATUS_AWAITING_CONFIRMATION
    )

    before = time.time()
    confirmed = harness._run_route(monkeypatch, state, question="네")
    after = time.time()
    assert confirmed.status_code == 200
    assert len(history.rows) == 1
    row = next(iter(history.rows.values()))
    expires = datetime.fromisoformat(
        row["expires_at"].replace("Z", "+00:00")
    ).timestamp()
    assert before + 500 <= expires <= after + 610
    assert row["command_text"] == "whoami"
    assert calls[-1][0] == "create_dispatch"
    return {
        "name": "confirmation_card_then_dispatch",
        "input_turns": [staged_turn, "네"],
        "responses": [_resp(card), _resp(confirmed)],
        "calls": calls,
        "dispatch_expires_range_seconds_from_turn": [500, 610],
    }


def test_real_confirmation_turn_is_identical_to_golden(monkeypatch):
    got = _real_confirmation_snapshot(monkeypatch)
    if os.environ.get("UPDATE_7814_GOLDEN") == "1":
        document = _golden()
        document["integrated_cases"] = [got]
        _write_golden(document)
        return
    assert got == _golden()["integrated_cases"][0]


def test_a_real_screen_dispatch_keeps_its_ttl_window(monkeypatch):
    """The moved screen branch still stages one dispatch with the existing TTL."""

    import test_pc_screen_view_s1_261102 as harness

    state = harness._state()
    before = time.time()
    response = harness._run_route(monkeypatch, state)
    after = time.time()

    assert response.status_code == 200
    row = next(iter(state.history_store.rows.values()))
    expires = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00")).timestamp()
    assert before + 500 <= expires <= after + 610
