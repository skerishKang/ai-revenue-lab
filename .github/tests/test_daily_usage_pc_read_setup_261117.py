"""#6724 2번 2단계 — pc_read 설정 검증 선행 계약.

`flow_pc_read`는 send_probe 전에 설치·승인 구간을 검증하고, 실패하면 bounded
`setup_*` 코드로 USAGE_FLOW 판정을 남긴다. 이 시험은 가짜 조회만 쓰고 실제
PC·운영 토큰·네트워크에 닿지 않는다. 토큰 값은 출력·로그·고정값에 넣지 않는다.
"""
from __future__ import annotations

import importlib.util
import secrets
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECK = HERE.parent / "scripts" / "daily_real_usage_check.py"


def _load():
    spec = importlib.util.spec_from_file_location("daily_real_usage_check_setup", CHECK)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _fake_token() -> str:
    """발급 규칙과 같은 방법으로 만든 값 — 실제 발급 토큰이 아니다."""
    return "mcp_" + uuid.uuid4().hex + "." + secrets.token_urlsafe(32)


def test_setup_runs_before_the_probe(monkeypatch):
    mod = _load()
    fake = _fake_token()
    monkeypatch.setenv(mod.PC_TOKEN_ENV, fake)
    monkeypatch.delenv(mod.PC_READ_PATH_ENV, raising=False)
    monkeypatch.setattr(mod, "_pc_setup_lookup", lambda cookie, opener: {"approved": True, "roots": 1})

    called = []

    def probe(token, path):
        called.append(token)
        return {"http_status": 200, "call_status": "completed",
                "content_head20": "PADIEM MESHCENTRAL SINGLE-PC TXT TEST"}

    monkeypatch.setattr(mod, "send_probe", probe)
    flow = mod.Flow("pc_read")
    mod.flow_pc_read(flow, "cookie-value")
    assert called == [fake]
    assert flow.verdict == "PASS"


def test_setup_failure_stops_before_the_probe_with_a_bounded_code(monkeypatch):
    mod = _load()
    monkeypatch.setenv(mod.PC_TOKEN_ENV, _fake_token())
    monkeypatch.setattr(
        mod, "_pc_setup_lookup", lambda cookie, opener: {"approved": False, "roots": 0})

    def probe(*args, **kwargs):
        raise AssertionError("probe must not run when setup failed")

    monkeypatch.setattr(mod, "send_probe", probe)
    flow = mod.Flow("pc_read")
    mod.flow_pc_read(flow, "cookie-value")
    assert flow.verdict == "FAIL"
    assert flow.code == "setup_not_approved"
    line = flow.line()
    assert "verdict=FAIL" in line and "code=setup_not_approved" in line
    assert _fake_token() not in line


def test_empty_cookie_skips_setup_and_still_runs_the_probe(monkeypatch):
    mod = _load()
    monkeypatch.setenv(mod.PC_TOKEN_ENV, _fake_token())

    calls = {"lookup": 0, "probe": 0}

    def lookup(cookie, opener):
        calls["lookup"] += 1
        raise AssertionError("no setup lookup without a session")

    def probe(token, path):
        calls["probe"] += 1
        return {"http_status": 200, "call_status": "completed",
                "content_head20": "PADIEM MESHCENTRAL SINGLE-PC TXT TEST"}

    monkeypatch.setattr(mod, "_pc_setup_lookup", lookup)
    monkeypatch.setattr(mod, "send_probe", probe)
    flow = mod.Flow("pc_read")
    mod.flow_pc_read(flow, "")
    assert calls == {"lookup": 0, "probe": 1}
    assert flow.verdict == "PASS"
    line = flow.line()
    assert "setup=skipped_no_session" in line
    assert "verdict=PASS" in line


def test_canary_public_code_is_kept_bounded(monkeypatch):
    mod = _load()
    monkeypatch.setenv(mod.PC_TOKEN_ENV, _fake_token())

    def lookup(cookie, opener):
        raise mod.CanaryError("setup_lookup_http_401")

    monkeypatch.setattr(mod, "_pc_setup_lookup", lookup)
    flow = mod.Flow("pc_read")
    mod.flow_pc_read(flow, "cookie-value")
    assert flow.verdict == "FAIL"
    assert flow.code == "setup_lookup_http_401"
    assert "setup_lookup_http_401" in flow.line()


def test_missing_token_still_skips(monkeypatch):
    mod = _load()
    monkeypatch.delenv(mod.PC_TOKEN_ENV, raising=False)
    flow = mod.Flow("pc_read")
    mod.flow_pc_read(flow, "")
    assert flow.verdict == "SKIPPED"
    assert flow.code == "pc_token_missing"


def test_owner_scoped_lookup_reduces_to_approval_and_roots(monkeypatch):
    mod = _load()

    class Done:
        status = 200

        def getcode(self):
            return 200

        def read(self, limit=0):
            import json
            return json.dumps({
                "ok": True,
                "links": [
                    {"state": "active", "roots": [{"state": "active"}, {"state": "active"}]},
                    {"state": "paused", "roots": [{"state": "active"}]},
                ],
            }).encode("utf-8")

        headers = {}

    class Ctx:
        def __enter__(self):
            return Done()

        def __exit__(self, *args):
            return False

    class Opener:
        def open(self, request, timeout):
            assert request.full_url.endswith(mod.PC_SETUP_PATH)
            assert "Cookie" in request.headers
            return Ctx()

    out = mod._pc_setup_lookup("cookie-value", Opener())
    assert out == {"approved": True, "roots": 2}
