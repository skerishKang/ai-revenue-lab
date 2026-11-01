"""App attribution travels through host P01 to the existing B14 ledger.

Only provider transport is mocked: ASGI request scoping, LocalB14Binding,
the ledger's origin parser and ledger records are the real implementations.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from app import local_runtime as rt

MODEL = "google/gemini-3.1-flash-lite"
B14_URL = "https://b14.internal/api/pilot/v1/chat/completions"
LEDGER_PATH = Path(__file__).resolve().parents[2] / "korean-ai-platform/app/pilot/call_ledger.py"
_spec = importlib.util.spec_from_file_location("apps_ai_existing_call_ledger", LEDGER_PATH)
ledger = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = ledger
_spec.loader.exec_module(ledger)


async def _call(app, *, name="bookai", app_id="b61", path="/internal/v1/execute",
                method="POST", body=None, extra_headers=None):
    headers = {"content-type": "application/json", "x-padiem-client-app": name}
    headers.update(extra_headers or {})
    if body is None:
        body = json.dumps({"app_id": app_id, "model": MODEL}).encode()
    scope = {
        "type": "http", "http_version": "1.1", "method": method,
        "path": path, "raw_path": path.encode(), "query_string": b"",
        "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
        "server": ("127.0.0.1", 8811), "client": ("127.0.0.1", 50123),
        "scheme": "http",
    }
    result = {}

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            result["status"] = message["status"]
        if message["type"] == "http.response.body":
            result["body"] = message["body"]

    await app(scope, receive, send)
    return result


def _binding(monkeypatch, rows, *, outcome="success"):
    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def request(self, method, url, headers, content):
            await asyncio.sleep(0)  # Deliberately interleave the two app requests.
            model = json.loads(content)["model"]
            origin = ledger.origin_from_headers(headers)
            draft = ledger.LedgerDraft(
                log_id=ledger.new_log_id(), request_id="apps-ai-attribution-test",
                endpoint="/api/pilot/v1/chat/completions",
                protocol="chat/completions", streaming=False,
                requested_model_id=model, started_at=ledger.utc_now_iso(),
                origin=origin,
            )
            draft.record_attempt(provider="google", model_id=model, outcome=outcome)
            rows.append(draft.finish(
                outcome=outcome, http_status=200 if outcome == "success" else 503,
                selected_model_id=model, selected_provider="google",
                actual_response_model=model,
            ))
            return SimpleNamespace(
                content=b'{"choices":[]}', status_code=200,
                headers={"content-type": "application/json"},
            )

    monkeypatch.setattr(rt.httpx, "AsyncClient", lambda **_kw: Client())
    return rt.LocalB14Binding(
        "http://127.0.0.1:8789",
        values={rt.B14_PROOF_SECRET_ENV: "synthetic-test-" + "x" * 40},
    )


def _entry(binding, *, fail=False):
    class Entry:
        async def fetch(self, request):
            if fail:
                raise RuntimeError("synthetic_dispatch_failure")
            await asyncio.sleep(0)
            await binding.fetch(rt.LocalRequest(
                B14_URL, method="POST", body=json.dumps({"model": MODEL}).encode(),
                headers={"content-type": "application/json"},
            ))
            return rt.LocalResponse(b'{"ok":true}', status=200)
    return Entry()


@pytest.mark.parametrize("name", ["storymemory", "bookai"])
@pytest.mark.parametrize("outcome", ["success", "error"])
async def test_app_model_and_result_reach_existing_ledger(monkeypatch, name, outcome):
    rows = []
    binding = _binding(monkeypatch, rows, outcome=outcome)
    app = rt.LocalEngineApp(entry=_entry(binding))

    assert (await _call(app, name=name))["status"] == 200
    assert len(rows) == 1
    row = rows[0]
    assert row.product == "engine"
    assert row.client_app == name
    assert row.requested_model_id == row.selected_model_id == MODEL
    assert row.outcome == outcome
    assert row.origin_source == "caller_declared"
    assert rt._APPS_AI_CLIENT_APP.get() is None


async def test_concurrent_apps_and_later_plain_requests_do_not_leak(monkeypatch):
    rows = []
    binding = _binding(monkeypatch, rows)
    app = rt.LocalEngineApp(entry=_entry(binding))
    await asyncio.gather(_call(app, name="storymemory"), _call(app, name="bookai"))
    assert sorted(row.client_app for row in rows) == ["bookai", "storymemory"]

    await binding.fetch(rt.LocalRequest(B14_URL, method="POST",
        body=json.dumps({"model": MODEL}).encode()))
    assert rows[-1].client_app is None
    assert rows[-1].product == "unknown"


@pytest.mark.parametrize("override", [
    {"name": "unregistered-app"},
    {"app_id": "padiem-chat"},
    {"path": "/internal/v1/orchestrate"},
    {"method": "GET"},
    {"body": b"not-json"},
])
async def test_attribution_is_bounded_to_b61_apps_execute(monkeypatch, override):
    rows = []
    app = rt.LocalEngineApp(entry=_entry(_binding(monkeypatch, rows)))
    await _call(app, **override)
    assert rows[0].client_app is None
    assert rows[0].product == "unknown"


async def test_dispatch_exception_resets_request_context(monkeypatch):
    rows = []
    binding = _binding(monkeypatch, rows)
    with pytest.raises(RuntimeError, match="synthetic_dispatch_failure"):
        await _call(rt.LocalEngineApp(entry=_entry(binding, fail=True)))
    assert rt._APPS_AI_CLIENT_APP.get() is None
    await binding.fetch(rt.LocalRequest(B14_URL, method="POST",
        body=json.dumps({"model": MODEL}).encode()))
    assert rows[-1].client_app is None


async def test_app_attribution_header_does_not_bypass_engine_auth(monkeypatch):
    rows = []
    _binding(monkeypatch, rows)
    app = rt.create_local_app({
        "PADIEM_ENGINE_CPYTHON_HOST": "1",
        "PADIEM_ENGINE_LOCAL_B14_ORIGIN": "http://127.0.0.1:8789",
        "PADIEM_ENGINE_CALLER_ID": "synthetic-apps-caller",
        "PADIEM_ENGINE_CALLER_SECRET": "synthetic-test-" + "x" * 40,
        "PADIEM_ENGINE_ALLOWED_APPS": "b61",
    })
    result = await _call(app, name="bookai")
    assert result["status"] == 401
    assert json.loads(result["body"])["error"]["code"] == "service_authentication_failed"
    assert rows == []
    assert rt._APPS_AI_CLIENT_APP.get() is None
