"""#3580: fixed private Engine ToolRuntime transport, no browser authority."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_3580_web_xlsx_p01_request import projected_pause
from app.claw_web_xlsx_p01_request import (
    TrustedWebXlsxP01Request, WebXlsxP01RequestError,
    parse_engine_pause,
)
from app.web_xlsx_p01_engine_client import (
    CloudflareWebXlsxP01EngineClient, build_web_xlsx_p01_engine_client,
    web_xlsx_engine_tool_payload,
)
from app.worker_config import (
    P01_ENGINE_SERVICE_BINDING_NAME, P01_ENGINE_CALLER_ID_ENV,
    P01_ENGINE_CREDENTIAL_ENV,
)

EXPIRY = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()


def scope():
    return TrustedWebXlsxP01Request(
        owner_id="usr_web_engine_owner",
        workspace_id="owner:usr_web_engine_owner",
        run_id="run_web_origin_owner_55",
        selection_ref="sel_" + "a"*32,
        document_id="doc_" + "b"*32,
        source_sha256="c"*64,
        filename="학교견적서.xlsx",
        selection_expires_at=EXPIRY,
    )


class FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self.body = None
        self.value = body

    async def text(self):
        return self.value


class EngineBinding:
    def __init__(self, result=None, status=202, fail=False):
        self.result = result
        self.status = status
        self.fail = fail
        self.calls = []
        self.factories = []

    async def fetch(self, js):
        self.calls.append(js)
        if self.fail:
            raise RuntimeError("private Engine unavailable")
        value = json.dumps(
            self.result if self.result is not None else projected_pause(scope()),
            ensure_ascii=False,
        )
        return FakeResponse(self.status, value)


def client(binding):
    def make(url, *, method, headers, body):
        binding.factories.append({
            "url": url, "method": method,
            "headers": dict(headers), "body": body,
        })
        return SimpleNamespace(js_object={"request": len(binding.factories)})
    return CloudflareWebXlsxP01EngineClient(
        binding,
        caller_id="P01_ENGINE_B62",
        credential="secret-for-tests-only-not-real",
        request_factory=make,
    )


@pytest.mark.asyncio
async def test_existing_p01_credential_fixed_tool_target_and_source_sha():
    binding = EngineBinding()
    source = scope()
    projection = await client(binding).start_pause(source)
    assert projection["tool"]["status"] == "paused"
    exact = parse_engine_pause(projection, original=source)
    assert exact.engine_run_id == "torun:" + "f"*24
    assert len(binding.calls) == 1
    req = binding.factories[0]
    assert req["url"] == "https://engine.internal/internal/v1/tools/execute" or (
        req["url"].endswith("/internal/v1/tools/execute")
        and req["url"].startswith("https://"))
    assert req["method"] == "POST"
    assert req["headers"]["x-padiem-engine-caller"] == "P01_ENGINE_B62"
    assert req["headers"]["x-padiem-engine-credential"] == "secret-for-tests-only-not-real"
    data = json.loads(req["body"])
    assert data == web_xlsx_engine_tool_payload(source)
    assert data["app_id"] == "padiem-web-xlsx-p01"
    assert data["agent_id"] == "agent:padiem:web-xlsx-confirm@1"
    assert data["tool_id"] == "tool:padiem:web-xlsx-confirm@1"
    assert data["arguments"]["owner_id"] == source.owner_id
    assert data["arguments"]["source_sha256"] == source.source_sha256
    assert data["arguments"]["read_content"] is False
    assert data["arguments"]["drive_write"] is False
    assert data["arguments"]["local_pc_access"] is False
    assert not any(k in data for k in (
        "decision", "approval", "continuation_ref", "model", "provider"))
    assert "https://engine.internal" not in req["body"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status,result", [
    (200, {"ok": True, "tool": {"status": "completed"}}),
    (401, {"ok": False, "error": {"code": "unauthorized"}}),
    (503, {"ok": False, "error": {"code": "tool_runtime_unavailable"}}),
    (202, {"ok": True, "orchestration": {"status": "paused"}}),
    (202, {"ok": False, "tool": {"status": "paused"}}),
])
async def test_private_adapter_fails_closed_on_non_engine_pause(status, result):
    binding = EngineBinding(result=result, status=status)
    with pytest.raises(WebXlsxP01RequestError):
        await client(binding).start_pause(scope())
    assert len(binding.calls) == 1


@pytest.mark.asyncio
async def test_unknown_dispatch_or_oversized_private_response_never_retries():
    down = EngineBinding(fail=True)
    with pytest.raises(RuntimeError):
        await client(down).start_pause(scope())
    assert len(down.calls) == 1
    huge = EngineBinding(result={"ok": True, "tool": {"secret": "x"*14000}})
    with pytest.raises(WebXlsxP01RequestError):
        await client(huge).start_pause(scope())
    assert len(huge.calls) == 1


def test_operator_only_composition_reuses_existing_p01_identity():
    binding = EngineBinding()
    class Env:
        pass
    env = Env()
    setattr(env, P01_ENGINE_SERVICE_BINDING_NAME, binding)
    setattr(env, P01_ENGINE_CALLER_ID_ENV, "P01_ENGINE_B62")
    setattr(env, P01_ENGINE_CREDENTIAL_ENV, "x"*32)
    setattr(env, "PADIEM_WEB_XLSX_P01_TOOL_DISPATCH_ENABLED", "true")
    assert build_web_xlsx_p01_engine_client(
        env, request_factory=lambda *_a, **_kw: object(), runtime_mode="mock"
    ) is None
    setattr(env, "PADIEM_WEB_XLSX_P01_TOOL_DISPATCH_ENABLED", "false")
    assert build_web_xlsx_p01_engine_client(
        env, request_factory=lambda *_a, **_kw: object(), runtime_mode="b14"
    ) is None
    setattr(env, "PADIEM_WEB_XLSX_P01_TOOL_DISPATCH_ENABLED", "true")
    assert isinstance(build_web_xlsx_p01_engine_client(
        env, request_factory=lambda *_a, **_kw: object(), runtime_mode="b14"
    ), CloudflareWebXlsxP01EngineClient)
    delattr(env, P01_ENGINE_SERVICE_BINDING_NAME)
    assert build_web_xlsx_p01_engine_client(
        env, request_factory=lambda *_a, **_kw: object(), runtime_mode="b14"
    ) is None


def test_closed_engine_pause_projection_rejects_old_or_fabricated_protocol():
    scope_request = scope()
    expected = projected_pause(scope_request)
    assert parse_engine_pause(expected, original=scope_request).pause_id
    spoof = {"orchestration": {"approval_pause": expected["tool"]["approval_pause"]}}
    with pytest.raises(WebXlsxP01RequestError):
        parse_engine_pause(spoof, original=scope_request)
    for key, val in (
        ("agent_id", "agent:padiem:other@1"),
        ("canonical_tool_id", "tool:padiem:other@1"),
        ("contract_version", "padiem.engine.tools/0.0"),
        ("status", "completed"),
    ):
        bad = {"ok": True, "tool": dict(expected["tool"])}
        bad["tool"][key] = val
        with pytest.raises(WebXlsxP01RequestError):
            parse_engine_pause(bad, original=scope_request)
