"""R7-5 claw_general_execute 2단계 증거 시험 (#7814).

세션 소유자 턴·Custom·등급·경로·대화 참조·선행 읽기 구간이
리팩터 전 origin/main(b2b2ae01)에서 일으킨 응답과 대역 호출이
리팩터 후에도 같은지 고정한다. 가짜 값만 쓴다.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from starlette.requests import Request
from starlette.responses import JSONResponse

from app import claw_general_routes as g
from app import chat_pc_session as sess
from app import central_model_route_runtime as cmr
from app.history import HistoryContextIncomplete
from _support.claw_general_modules import patch_bound

GOLDEN_PATH = (
    Path(__file__).resolve().parent
    / "test_7814_claw_general_branches_table_golden.json"
)


def _run(coro):
    return asyncio.run(coro)


class _Hist:
    pass


def _req(payload, headers=None):
    raw = json.dumps(payload).encode()
    hdrs = [(b"content-type", b"application/json")]
    if headers:
        hdrs += headers
    app = SimpleNamespace(state=SimpleNamespace(
        settings=SimpleNamespace(runtime_mode="mock", session_secret="x", auth_mode="off"),
        history_store=_Hist(),
    ))
    scope = {"type": "http", "method": "POST", "path": "/api/claw/general", "app": app, "headers": hdrs}

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}

    return Request(scope, receive=receive)


def _plain():
    return {"messages": [{"role": "user", "content": "안녕하세요"}]}


def _resp(r):
    body = r.body if isinstance(r.body, (bytes, bytearray)) else b""
    try:
        parsed = json.loads(body)
    except Exception:
        parsed = body.decode(errors="replace")
    return {"status": r.status_code, "body": parsed, "headers": sorted((k.lower(), v) for k, v in r.headers.items())}


def _setup(monkeypatch, calls, *, session_ret=None, tier_model=None, conv=("conv1", None),
           hist="이전 대화", drive=(None, []), catalog=(None, False), uid="owner1"):
    async def fake_handle(request, **kw):
        calls.append(("handle_owner_turn", kw.get("user_text"), kw.get("conversation_id")))
        return session_ret

    def fake_claw(resp):
        calls.append(("claw_response",))
        return JSONResponse({"lane": "session"}, status_code=200)

    monkeypatch.setattr(sess, "handle_owner_turn", fake_handle)
    monkeypatch.setattr(sess, "claw_response", fake_claw)
    patch_bound(monkeypatch, "current_user_id", lambda request: uid)
    patch_bound(monkeypatch, "auth_ready", lambda request: True)

    async def fake_custom_direct(request, **kw):
        calls.append(("custom_direct", kw.get("uid"), kw.get("user_text")))
        return JSONResponse({"lane": "custom", "uid": kw.get("uid")}, status_code=200)

    patch_bound(monkeypatch, "_claw_custom_direct", fake_custom_direct)

    async def fake_tier_model(request, tier):
        calls.append(("tier_model", tier))
        return tier_model if tier_model is not None else SimpleNamespace(
            ok=True, model_id="model.x", fallback_model_id=None, source="central")

    monkeypatch.setattr(cmr, "resolve_claw_tier_model", fake_tier_model)

    async def fake_tier_denial(request, user_id, grade):
        calls.append(("tier_denial", user_id, getattr(grade, "tier_id", None)))
        return None

    patch_bound(monkeypatch, "claw_execution_tier_denial", fake_tier_denial)

    async def fake_ref(request, data):
        calls.append(("intake_ref", data.get("conversation_id")))
        return conv

    patch_bound(monkeypatch, "_resolve_intake_session_reference", fake_ref)

    async def fake_hist(request, cid, text):
        calls.append(("owner_context", cid, text))
        if isinstance(hist, Exception):
            raise hist
        return hist

    patch_bound(monkeypatch, "_owner_claw_context", fake_hist)

    async def fake_drive(request, text):
        calls.append(("drive", text))
        return drive

    patch_bound(monkeypatch, "drive_general_grounding", fake_drive)

    def fake_catalog(request, mid):
        calls.append(("catalog_start", mid))
        return catalog

    patch_bound(monkeypatch, "_start_selectable_model_read", fake_catalog)

    async def fake_usage(request):
        calls.append(("usage_gate",))
        return None

    patch_bound(monkeypatch, "_usage_gate_denial", fake_usage)

    async def noop(*a, **k):
        calls.append(("noop",))
        return None

    patch_bound(monkeypatch, "_refund_active_reservation", noop)
    patch_bound(monkeypatch, "fail_first_turn_grant", noop)
    if hasattr(g, "reserve_first_turn_grant"):
        async def fake_reserve(request, **kw):
            calls.append(("reserve_first", kw.get("user_id")))
            return None

        patch_bound(monkeypatch, "reserve_first_turn_grant", fake_reserve)


def _txt_custom():
    return {"messages": [{"role": "user", "content": "내 PC의 notes/report.txt 읽어줘"}],
            "custom": {"provider": "fixture", "model": "fixture-model"}}


def _attach_custom():
    return {"messages": [{"role": "user", "content": "안녕하세요"}],
            "custom": {"provider": "fixture", "model": "fixture-model"},
            "attachments": [{"type": "document", "name": "a.txt", "media_type": "text/plain",
                             "text": "fake document text"}]}


def _custom():
    return {"provider": "fixture", "model": "fixture-model"}


# (이름, 요청, setup kwargs)
CASES = [
    ("세션_턴_응답", lambda: _req(_plain()), {"session_ret": object()}),
    ("일반_진입_엔진_없음", lambda: _req(_plain()), {"conv": (None, None)}),
    ("Custom_정상", lambda: _req({**_plain(), "custom": _custom()}), {}),
    ("Custom_형식_오류", lambda: _req({**_plain(), "custom": {"provider": "fixture"}}), {}),
    ("Custom_라이브", lambda: _req({**_plain(), "custom": _custom()},
                                    headers=[(b"x-padiem-claw-live", b"p01-events-v1")]), {}),
    ("Custom_도구_거부", lambda: _req(_txt_custom()), {}),
    ("Custom_첨부_거부", lambda: _req(_attach_custom()), {}),
    ("Custom_미로그인", lambda: _req({**_plain(), "custom": _custom()}), {"uid": None}),
    ("등급_없음", lambda: _req({**_plain(), "tier": "bogus"}), {}),
    ("경로_없음", lambda: _req({**_plain(), "tier": "free"}),
     {"tier_model": SimpleNamespace(ok=False, model_id=None, fallback_model_id=None, source="central")}),
    ("모델_선언_불일치", lambda: _req({**_plain(), "tier": "free", "model_id": "model.y"}), {}),
    ("대화_참조_거부", lambda: _req({**_plain(), "tier": "free"}),
     {"conv": (None, JSONResponse({"code": "conv_denied"}, status_code=403))}),
    ("이력_없음", lambda: _req({**_plain(), "tier": "free"}), {"hist": HistoryContextIncomplete("x")}),
    ("이력_불가", lambda: _req({**_plain(), "tier": "free"}), {"hist": RuntimeError("d1 down")}),
    ("일반_진입_두번째", lambda: _req({**_plain(), "tier": "free"}), {"conv": (None, None)}),
]


def _golden():
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def test_branches_table_parseable():
    golden = _golden()
    assert [c["name"] for c in golden["cases"]] == [c[0] for c in CASES]


def test_branches_table_is_identical_to_golden(monkeypatch):
    golden = {c["name"]: c for c in _golden()["cases"]}
    for name, req_factory, kwargs in CASES:
        calls = []
        _setup(monkeypatch, calls, **kwargs)
        resp = _run(g.claw_general_execute(req_factory()))
        got = json.loads(json.dumps({"name": name, "resp": _resp(resp), "calls": calls}, ensure_ascii=False))
        assert got == golden[name], name
