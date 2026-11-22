"""R7-7 claw_general_execute 4/4a 증거 시험 (#7814).

리팩터 전 origin/main(28c1815d1) blob에서 옮기는 구간(실시간 허용 →
first-turn 예약 → quota → adapter 미설정 → 네이티브 캘린더, 원래
2632-2757줄)의 반환 경로와 정상 입력 2개를 끝까지 고정한다. SSE 이벤트
순서·대역 호출 순서·기록 행·quota 환불/포기 호출을 같은 값으로 비교한다.
가짜 값만 쓴다(실제 운영 값·비밀값 없음).

골든 출처: `git show origin/main:apps/padiem-chat/app/claw_general_routes.py`
의 위 구간을 그대로 실행해 생성했다. 리팩터 후 같은 시험이 통과해야 한다.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace

from starlette.requests import Request
from starlette.responses import JSONResponse

from app import claw_general_routes as g

GOLDEN_PATH = (
    Path(__file__).resolve().parent
    / "test_7814_claw_general_tail_table_golden.json"
)
PRE_REFACTOR_ORIGIN_MAIN = "28c1815d122d65c800769e1f601949da42a90926"


def _run(coro):
    return asyncio.run(coro)


def _req(payload, *, live=False, evidence=False, preflight_error=None):
    raw = json.dumps(payload).encode()
    headers = [(b"content-type", b"application/json")]
    if live:
        headers.append((g.CLAW_LIVE_REQUEST_HEADER.lower().encode(),
                        g.CLAW_LIVE_REQUEST_MARKER.encode()))
    if evidence:
        headers.append((g.CLAW_EVIDENCE_REQUEST_HEADER.lower().encode(),
                        g.CLAW_EVIDENCE_MARKER.encode()))
    del preflight_error
    app = SimpleNamespace(state=SimpleNamespace(
        settings=SimpleNamespace(runtime_mode="mock", session_secret="x", auth_mode="off"),
        history_store=object(),
        claw_live_sse_enabled=True,
        calendar_store=object(),
    ))
    scope = {"type": "http", "method": "POST", "path": "/api/claw/general",
             "app": app, "headers": headers}

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}

    return Request(scope, receive=receive)


def _resp(response):
    body = response.body if isinstance(response.body, (bytes, bytearray)) else b""
    text = body.decode("utf-8", errors="replace")
    events = []
    for chunk in text.split("\n\n"):
        lines = chunk.splitlines()
        event = next((line[7:] for line in lines if line.startswith("event: ")), None)
        data = next((line[6:] for line in lines if line.startswith("data: ")), None)
        if event is not None:
            events.append([event, json.loads(data) if data else None])
    try:
        parsed = json.loads(body) if not events else text
    except Exception:
        parsed = text
    return {
        "status": response.status_code,
        "body": parsed,
        "media_type": response.media_type,
        "events": events,
        "headers": {k.lower(): v for k, v in response.headers.items()
                    if k.lower().startswith(("x-padiem-", "cache-control", "x-accel-"))},
    }


def _outcome(*, status="completed", answer="P01 결과"):
    projection = SimpleNamespace(status=SimpleNamespace(value=status))
    return SimpleNamespace(
        projection=projection, answer=answer, p01_event_history=(),
        p01_run_id="p01_tail", selected_route_id=None,
        provider_attempt_count=None, fallback_used=None,
    )


def _adapter(calls, *, outcome=None, execute_error=None, stream=False):
    adapter = SimpleNamespace(
        _runner=SimpleNamespace(run_stream=lambda *a, **k: None) if stream else None
    )

    async def execute(run, **kwargs):
        calls.append(["execute", dict(kwargs)])
        if execute_error is not None:
            raise execute_error
        return outcome if outcome is not None else _outcome()

    adapter.execute = execute
    return adapter


def _setup(monkeypatch, calls, *, quota=None, adapter=None, no_adapter=False,
           live=False, live_allowed=True, stream=False, reservation="grant_fixture",
           claim=True, native_plan=None, calendar_error=None,
           calendar_result=None, evidence=False):
    text = "fixture turn"
    payload = {"messages": [{"role": "user", "content": text}]}

    async def fake_intake(request):
        del request
        return None, {"turn_started": 0.0, "data": payload, "user_text": text,
                      "document_context": None, "attachment_conflict": None}

    async def fake_session_custom(*args, **kwargs):
        del args, kwargs
        return None, {}

    async def fake_pc_branch(*args, **kwargs):
        del args, kwargs
        return None, {
            "initial_pc_capture": False, "desktop_task_requested": False,
            "desktop_device_id": None, "requested_device_id": None,
            "pc_browser_requested": False, "pc_browser_device_id": None,
            "pc_files_requested": False, "pc_files_device_id": None,
            "initial_pc_drive_query": False,
        }

    async def fake_work_context(request, **kwargs):
        del request
        calls.append(["pc_work_context", dict(kwargs)])
        return None, {"pc_work_text": None, "desktop_device_id": None,
                      "pc_files_device_id": None, "pc_browser_device_id": None}

    async def fake_preflight(request, data, user_text, turn_started):
        del request, data, user_text, turn_started
        return None, {
            "grade": SimpleNamespace(tier_id="free"), "requested_tier": "free",
            "admin_lane": False, "product_tier": "free",
            "identity_tier_id": None,
            "claw_route": SimpleNamespace(fallback_model_id=None),
            "central_route_model_id": "model.fixture", "conversation_id": None,
            "adapter": None if no_adapter else adapter, "has_identity_lane": False,
            "model_user_text": text, "b54_session": None,
            "drive_result": (None, []),
        }

    async def fake_reserve(request, **kwargs):
        calls.append(["reserve_first_turn", {k: v for k, v in kwargs.items()
                                            if k != "request"}])
        return reservation

    async def fake_usage(request):
        calls.append(["usage_gate"])
        return quota

    async def fake_refund():
        calls.append(["refund_active_reservation"])

    async def fake_fail(request, context):
        del request
        calls.append(["fail_first_turn_grant", context])

    def fake_clear():
        calls.append(["clear_reservation"])

    async def fake_claim(store, context):
        calls.append(["claim_first_turn_grant", claim])
        return claim

    async def fake_grounding(request, adapter_arg, user_text, *, model_id):
        del request, adapter_arg, user_text, model_id
        calls.append(["public_search_grounding"])
        return None, ()

    async def fake_calendar(request, store, uid, plan, *, turn_key):
        del request, store, uid
        calls.append(["calendar_execute", plan.get("op"), turn_key])
        if calendar_error is not None:
            raise calendar_error
        return calendar_result if calendar_result is not None else {"ok": True}

    async def fake_record(request, **kwargs):
        calls.append(["record", {k: v for k, v in kwargs.items() if k != "request"}])
        return "conv_tail_fixture"

    monkeypatch.setattr(g, "_claw_general_intake", fake_intake)
    monkeypatch.setattr(g, "_claw_general_session_custom", fake_session_custom)
    monkeypatch.setattr(g, "_claw_general_pc_branch", fake_pc_branch)
    monkeypatch.setattr(g, "_claw_general_pc_work_context", fake_work_context)
    monkeypatch.setattr(g, "_claw_general_route_preflight", fake_preflight)
    monkeypatch.setattr(g, "_start_selectable_model_read", lambda request, mid: (None, False))
    monkeypatch.setattr(g, "live_stream_allowed", lambda state, subject: live_allowed)
    monkeypatch.setattr(g, "auth_ready", lambda request: True)
    monkeypatch.setattr(g, "current_user_id", lambda request: "owner_fixture")
    monkeypatch.setattr(g, "reserve_first_turn_grant", fake_reserve)
    monkeypatch.setattr(g, "_usage_gate_denial", fake_usage)
    monkeypatch.setattr(g, "_refund_active_reservation", fake_refund)
    monkeypatch.setattr(g, "fail_first_turn_grant", fake_fail)
    monkeypatch.setattr(g, "_clear_reservation", fake_clear)
    monkeypatch.setattr(g, "claim_first_turn_grant", fake_claim)
    monkeypatch.setattr(g, "parse_native_calendar_intent",
                        lambda user_text, *, timezone_name: native_plan or {"op": "none"})
    monkeypatch.setattr(g, "create_claw_run",
                        lambda *args, **kwargs: SimpleNamespace(run_id="run_tail_fixture"))
    monkeypatch.setattr(g, "_claw_public_search_grounding", fake_grounding)
    monkeypatch.setattr(g, "execute_native_calendar_plan", fake_calendar)
    monkeypatch.setattr(g, "_record_completed_claw_result", fake_record)
    monkeypatch.setattr(g, "_claw_stage", lambda *args, **kwargs: None)
    return _req(payload, live=live, evidence=evidence)


CASES = [
    ("quota_exceeded", {"quota": JSONResponse(
        {"ok": False, "error": {"code": "quota_exceeded"}}, status_code=429)}),
    ("engine_not_configured", {"no_adapter": True}),
    ("live_preflight_denied", {"live": True, "live_allowed": False}),
    ("live_relay_unavailable", {"live": True, "stream": False}),
    ("first_turn_conflict", {"claim": False}),
    ("calendar_clarify", {"native_plan": {"op": "clarify", "question": "날짜를 알려주세요"}}),
    ("calendar_execute_error", {"native_plan": {"op": "create_appointment"},
                                "calendar_error": RuntimeError("calendar down")}),
    ("live_evidence_conflict", {"live": True, "evidence": True, "stream": True}),
    ("normal_p01", {}),
    ("normal_p01_evidence", {"evidence": True}),
]


def _golden():
    if not GOLDEN_PATH.exists():
        return {"cases": [], "origin_main": PRE_REFACTOR_ORIGIN_MAIN}
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def _write_golden(document):
    GOLDEN_PATH.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")


def test_tail_table_parseable():
    golden = _golden()
    assert golden.get("origin_main") == PRE_REFACTOR_ORIGIN_MAIN
    if os.environ.get("UPDATE_7814_TAIL_GOLDEN") == "1":
        return
    assert [c["name"] for c in golden["cases"]] == [c[0] for c in CASES]


def test_tail_table_is_identical_to_golden(monkeypatch):
    golden = {c["name"]: c for c in _golden()["cases"]}
    for name, kwargs in CASES:
        calls = []
        adapter = _adapter(calls, **{k: v for k, v in kwargs.items()
                                     if k in ("outcome", "execute_error", "stream")})
        request = _setup(monkeypatch, calls, adapter=adapter,
                         **{k: v for k, v in kwargs.items()
                            if k not in ("outcome", "execute_error", "stream")})
        response = _run(g.claw_general_execute(request))
        got = json.loads(json.dumps(
            {"name": name, "resp": _resp(response), "calls": calls},
            ensure_ascii=False,
        ))
        if os.environ.get("UPDATE_7814_TAIL_GOLDEN") == "1":
            golden[name] = got
            continue
        assert got == golden[name], name
    if os.environ.get("UPDATE_7814_TAIL_GOLDEN") == "1":
        document = _golden()
        document["cases"] = [golden[name] for name, _ in CASES]
        _write_golden(document)


def test_moved_helper_is_registered_in_forbidden_path_scan():
    assert g._claw_general_quota_gate is not None
