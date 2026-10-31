"""Cold-import contract for the Chat Worker isolate.

The isolate's own import must stay light: the cron lane loads on the first
cron tick, the composition builders load inside the first app build, and the
B14 response ceiling loads on the first B14 call. Every moved import resolves
to the same object as before — only the import moment changed, so each first
call still has to behave exactly as documented (fail closed without bindings).
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from test_claw_automation_async_composition_seam import _load_worker

_APP_ROOT = Path(__file__).resolve().parents[1]

#: Feature lanes the isolate import must not touch (verified against the
#: factory graph: none of these is imported by ``app.app_factory`` either).
_CRON_LANE_MODULES = [
    "app.claw_automation_due_workspace_discovery",
    "app.claw_automation_scheduled_execution",
    "app.claw_automation_owner_resolution",
    "kagent.claw_automation_trigger",
]
_BUILD_ONLY_MODULES = [
    "app.claw_drive_upload_host_composition",
    "app.claw_local_access_composition",
    "app.claw_p01_composition",
    "app.claw_telegram_delivery_host_composition",
    "app.document_parser_transport",
    "padiem_ai_core.isolated_parser_composition",
]

_PROBE = r"""
import sys
import types

stub = types.ModuleType("workers")
stub.Request = object


class _Response:
    def __init__(self, body="", *, status=200, headers=None):
        self.body, self.status, self.headers = body, status, dict(headers or {})


class _WorkerEntrypoint:
    def __init__(self, env=None, ctx=None):
        self.env, self.ctx = env, ctx


stub.Response = _Response
stub.WorkerEntrypoint = _WorkerEntrypoint
sys.modules["workers"] = stub

import worker  # the isolate's own import

blocked = %s
leaked = [name for name in blocked if name in sys.modules]
if leaked:
    raise AssertionError("cold import pulled feature modules: " + ", ".join(leaked))
print("COLD_IMPORT_CLEAN")
"""


def test_the_worker_isolate_import_stays_free_of_feature_lanes():
    completed = subprocess.run(
        [sys.executable, "-c", _PROBE % repr(_CRON_LANE_MODULES + _BUILD_ONLY_MODULES)],
        cwd=_APP_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )
    assert completed.returncode == 0, (completed.stdout + completed.stderr)[-2000:]
    assert "COLD_IMPORT_CLEAN" in completed.stdout


def test_first_scheduled_tick_loads_the_cron_lane_and_fails_closed(monkeypatch):
    module = _load_worker(monkeypatch)
    env = SimpleNamespace(PADIEM_CHAT_AUTOMATION_SCHEDULER_ENABLED=True)
    result = asyncio.run(module.run_scheduled_automation_source(env))
    assert result is None  # no bindings: the tick refuses after loading the lane
    for name in _CRON_LANE_MODULES:
        assert name in sys.modules  # the first call itself brought the lane in


class _StubBindingResponse:
    """The narrow CPython shape read_bounded_service_binding_body accepts."""

    status = 200
    headers = {"content-type": "application/json"}

    def __init__(self, payload: str):
        self._payload = payload

    async def text(self) -> str:
        return self._payload


def test_first_b14_post_json_call_loads_the_response_ceiling(monkeypatch):
    module = _load_worker(monkeypatch)
    monkeypatch.setattr(
        module, "Request",
        lambda *args, **kwargs: SimpleNamespace(js_object=object()),
    )

    class _Binding:
        async def fetch(self, js_request):
            return _StubBindingResponse('{"ok": true}')

    transport = module.CloudflareB14ServiceTransport(_Binding(), proof_secret="unit-test-proof")
    status, body = asyncio.run(transport.post_json("https://b14.internal/api/pilot/models", {"x": 1}))
    assert status == 200 and body == b'{"ok": true}'
    assert "padiem_ai_core.b14_execution" in sys.modules  # loaded by this call


def test_first_build_time_builder_calls_still_fail_closed():
    from app.claw_drive_upload_host_composition import build_claw_drive_artifact_uploader
    from app.claw_local_access_composition import (
        build_claw_local_access_source_with_diagnostic,
        build_mesh_presence_generation_resolver,
    )
    from app.claw_p01_composition import build_claw_p01_lanes_with_diagnostic
    from app.claw_telegram_delivery_host_composition import (
        build_claw_telegram_artifact_delivery,
    )
    from padiem_ai_core.isolated_parser_composition import (
        reset_worker_isolated_parser_async_composition,
    )

    assert build_claw_drive_artifact_uploader() is None
    assert build_claw_telegram_artifact_delivery() is None
    source, diagnostic = build_claw_local_access_source_with_diagnostic(
        SimpleNamespace(), presence_store=None)
    assert source is None and diagnostic == "local_access_authority_binding_absent"
    assert build_mesh_presence_generation_resolver(SimpleNamespace()) is None
    adapter, continuation, diagnostic = build_claw_p01_lanes_with_diagnostic(
        SimpleNamespace(), request_factory=object)
    assert adapter is None and continuation is None and diagnostic == "engine_service_missing"
    reset_worker_isolated_parser_async_composition()  # idempotent without a transport
