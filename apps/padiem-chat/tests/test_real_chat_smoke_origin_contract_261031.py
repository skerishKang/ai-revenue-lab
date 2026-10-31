"""The real-chat smoke's mutation headers satisfy the actual Chat origin guard."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.same_origin_guard import SameOriginGuardMiddleware

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / ".github" / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("real_chat_smoke_origin_contract", SCRIPTS / "post_deploy_real_chat_smoke.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)
import b62_live_long_context_canary as canary


@pytest.mark.parametrize("base", ["https://chat.padiem.net", "https://other.example:8443"])
def test_engine_smoke_mutations_pass_real_guard(monkeypatch, base):
    monkeypatch.setattr(canary, "ORIGIN", base)
    monkeypatch.setenv(smoke.QA_USERNAME_ENV, "test-user")
    monkeypatch.setenv(smoke.QA_PASSWORD_ENV, "test-password")
    guard = SameOriginGuardMiddleware(None)
    observed = []
    conversation = "chat_" + "a" * 32

    class Response:
        status = 200
        def __init__(self, data):
            self.data = json.dumps(data).encode()
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, limit):
            return self.data[:limit]

    class Opener:
        def open(self, request, timeout):
            from urllib.parse import urlsplit
            path = urlsplit(request.full_url).path
            method = request.get_method()
            if method in ("POST", "DELETE"):
                headers = {k.lower(): v for k, v in request.header_items()}
                assert headers["origin"] == base
                assert headers["referer"] == base + "/"
                scope_headers = [(k.encode(), v.encode()) for k, v in headers.items()]
                scope_headers.append((b"cookie", b"padiem_session=synthetic"))
                if request.data is not None:
                    scope_headers.append((b"content-length", str(len(request.data)).encode()))
                scope = {
                    "method": method, "path": path, "headers": scope_headers,
                    "app": SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(public_base_url=base))),
                }
                assert guard.decide(scope) is None
                without_origin = dict(scope, headers=[x for x in scope_headers if x[0] != b"origin"])
                assert guard.decide(without_origin).status_code == 403
                wrong_origin = dict(scope, headers=[x for x in scope_headers if x[0] != b"origin"] + [(b"origin", b"https://evil.example")])
                assert guard.decide(wrong_origin).status_code == 403
                if request.data is not None:
                    no_json = dict(scope, headers=[x for x in scope_headers if x[0] != b"content-type"])
                    assert guard.decide(no_json).status_code == 415
                observed.append((method, path))
            data = {
                smoke.LOGIN: {"ok": True},
                smoke.STATUS: {"authenticated": True},
                smoke.ORCHESTRATION: {"answer": "test answer", "conversation_id": conversation},
                smoke.CONVERSATION + conversation: {"deleted": True},
            }[path]
            return Response(data)

    monkeypatch.setattr(smoke, "build_opener", lambda *_: Opener())
    assert smoke.run("engine") == 0
    assert observed == [
        ("POST", smoke.LOGIN),
        ("POST", smoke.ORCHESTRATION),
        ("DELETE", smoke.CONVERSATION + conversation),
    ]
