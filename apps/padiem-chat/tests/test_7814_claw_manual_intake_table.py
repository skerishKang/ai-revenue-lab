"""R7-6 claw_manual_intake_execute 증거 시험 (#7814).

리팩터 전 origin/main(78332c2b9)에서 일으킨 응답·기록을 고정한다.
가짜 값만 쓴다.
"""
from __future__ import annotations

import contextlib
import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.auth import SESSION_COOKIE, create_session_token
from test_claw_execution import (
    _app_with_identity,
    _google_settings,
    _injected_adapter,
    _make_adapter,
    _make_workspace_store,
    SIGNED_IN_USER_ID,
)
from kagent.manual_intake import ContractError

GOLDEN_PATH = (
    Path(__file__).resolve().parent
    / "test_7814_claw_manual_intake_table_golden.json"
)


def _norm(obj):
    if isinstance(obj, dict):
        return {k: _norm(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_norm(x) for x in obj]
    if isinstance(obj, str):
        s = re.sub(r"run_[0-9a-f]{16,}", "run_X", obj)
        s = re.sub(r"exec_[0-9a-f]{12}", "exec_X", s)
        return s
    return obj


_UNSET = object()
def _do(name, payload, *, adapter=_UNSET, patches=None, raw=None, ctype="application/json", no_store=False):
    app = _app_with_identity()
    app.state.workspace_document_store = None if no_store else _make_workspace_store()
    ad = _make_adapter() if adapter is _UNSET else adapter
    with TestClient(app, base_url="https://chat.example.test") as client:
        client.cookies.set(
            SESSION_COOKIE,
            create_session_token(_google_settings(), SIGNED_IN_USER_ID, canonical_session_id="session_test_a"),
            domain="chat.example.test",
            path="/",
        )
        with _injected_adapter(client, ad):
            with contextlib.ExitStack() as stack:
                for k, v in (patches or {}).items():
                    if "." in k:
                        stack.enter_context(patch(k, v))
                    else:
                        stack.enter_context(patch("app.claw_routes." + k, v))
                if raw is not None:
                    resp = client.post("/api/claw/manual-intake/execute", content=raw, headers={"content-type": ctype})
                else:
                    resp = client.post("/api/claw/manual-intake/execute", json=payload)
    calls = []
    if hasattr(ad, "execute") and ad.execute.await_count:
        calls.append(("execute", ad.execute.await_count))
    return {
        "name": name,
        "status": resp.status_code,
        "body": _norm(resp.json()),
        "headers": sorted((k.lower(), "REQ" if k.lower() == "x-request-id" else "LEN" if k.lower() == "content-length" else v) for k, v in resp.headers.items() if k.lower() not in ("date", "server")),
        "calls": calls,
    }


BASE = {"content": "가상 테스트: 샘플 20개 견적 요청.", "channel": "kakao", "action": "summary", "sender_hint": "A업체"}


class _BadRouter:
    def process(self, req):
        raise ContractError("bad contract")


class _ErrRouter:
    def process(self, req):
        raise RuntimeError("boom internal detail")


CASES = [
    ("정상_요약", BASE, {}),
    ("정상_답장", {**BASE, "action": "reply", "channel": "email"}, {}),
    ("미디어_형식", None, {"raw": b"{}", "ctype": "text/plain"}),
    ("빈_본문", None, {"raw": b""}),
    ("깨진_JSON", None, {"raw": b"{"}),
    ("객체_아님", None, {"raw": b"[1,2]"}),
    ("원문_없음", {"channel": "kakao", "action": "summary"}, {}),
    ("채널_없음", {**BASE, "channel": "carrier_pigeon"}, {}),
    ("작업_없음", {**BASE, "action": "teleport"}, {}),
    ("원문_너무_김", {**BASE, "content": "가" * 13000}, {}),
    ("발신자_너무_김", {**BASE, "sender_hint": "가" * 500}, {}),
    ("등급_없음", {**BASE, "tier": "bogus"}, {}),
    ("경로_없음", {**BASE, "tier": "free"},
     {"patches": {"app.central_model_route_runtime.resolve_claw_tier_model": AsyncMock(return_value=MagicMock(ok=False, model_id=None))}}),
    ("등급_거부", {**BASE, "tier": "free"},
     {"patches": {"claw_execution_tier_denial": AsyncMock(return_value=JSONResponse({"code": "tier_denied"}, status_code=403))}}),
    ("세션_거부", BASE,
     {"patches": {"_resolve_intake_session_reference": AsyncMock(return_value=(None, JSONResponse({"code": "conv_denied"}, status_code=403)))}}),
    ("산출물_권한_없음", {**BASE, "action": "quote"},
     {"patches": {"_resolve_canonical_owner": AsyncMock(return_value=None)}}),
    ("산출물_저장소_없음", {**BASE, "action": "quote"},
     {"no_store": True, "patches": {"_resolve_canonical_owner": AsyncMock(return_value=("owner1", "tenant1"))}}),
    ("quota_거부", BASE,
     {"patches": {"_usage_gate_denial": AsyncMock(return_value=JSONResponse({"code": "quota_denied"}, status_code=429))}}),
    ("엔진_없음", BASE, {"adapter": None}),
    ("계약_위반", BASE, {"patches": {"ManualIntakeRouter": _BadRouter}}),
    ("준비_실패", BASE, {"patches": {"ManualIntakeRouter": _ErrRouter}}),
    ("겹침_미디어_빈본문", None, {"raw": b"", "ctype": "text/plain"}),
    ("겹침_깨진JSON_채널없음", None, {"raw": b"{"}),
    ("겹침_원문없음_채널없음", {"channel": "carrier_pigeon", "action": "teleport"}, {}),
    ("겹침_등급없음_세션거부", {**BASE, "tier": "bogus"},
     {"patches": {"_resolve_intake_session_reference": AsyncMock(return_value=(None, JSONResponse({"code": "conv_denied"}, status_code=403)))}}),
]


def _golden():
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def test_manual_intake_table_parseable():
    assert [c["name"] for c in _golden()["cases"]] == [c[0] for c in CASES]


def test_manual_intake_table_is_identical_to_golden():
    golden = {c["name"]: c for c in _golden()["cases"]}
    for name, payload, kwargs in CASES:
        got = _do(name, payload, **kwargs)
        got = json.loads(json.dumps(got, ensure_ascii=False))
        assert got == golden[name], name


