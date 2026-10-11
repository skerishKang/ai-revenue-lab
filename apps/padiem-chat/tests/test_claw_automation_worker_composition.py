"""#3260 review — the Worker's REAL first-initialization path must inject the
real runtime env as the automation execution-target authority.

The create-route tests inject a fake app-state, so they cannot catch a
composition defect inside ``Default.fetch`` (a bare ``env`` name that does not
exist in that scope crashes the Worker on first initialization with a
NameError — a Production crash on every cold start). This suite executes the
real ``Default.fetch`` against a minimal fake runtime:

- the ``workers``, ``asgi`` and ``js`` runtime modules are stubbed at the
  boundary inside a child interpreter (no sys.modules pollution, so the
  result does not depend on test-suite ordering);
- the fake env carries NO bindings, so every store resolves to None and the
  composition stays fail-closed;
- the fetched request is dispatched through the real composed app.

Proven in the child:

- WORKER_FIRST_INIT_COMPLETES: ``fetch`` returns without a NameError;
- EXECUTION_TARGET_AUTHORITY_IS_THE_RUNTIME_ENV: the injected
  ``claw_automation_execution_target_authority`` IS the Worker's own ``env``
  object — not a copy, not None, not process-global state.

Restoring the ``= env`` composition defect makes the child crash and this
test fail.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

CHAT_ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = CHAT_ROOT / "worker.py"

_CHILD = r"""
import json
import sys
import types
from types import SimpleNamespace

workers_stub = types.ModuleType("workers")
workers_stub.Request = object


class _Response:
    def __init__(self, body="", *, status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = dict(headers or {})


workers_stub.Response = _Response


class _WorkerEntrypoint:
    def __init__(self, env=None, ctx=None):
        self.env = env
        self.ctx = ctx


workers_stub.WorkerEntrypoint = _WorkerEntrypoint
sys.modules["workers"] = workers_stub

asgi_stub = types.ModuleType("asgi")
asgi_calls = []


async def _asgi_fetch(app, request_js, env):
    asgi_calls.append((app, request_js, env))
    return _Response("ok")


asgi_stub.fetch = _asgi_fetch
sys.modules["asgi"] = asgi_stub

js_stub = types.ModuleType("js")
js_stub.fetch = lambda *a, **k: None
js_stub.AbortSignal = SimpleNamespace(abort=lambda *a, **k: None)
js_stub.URLSearchParams = dict
sys.modules["js"] = js_stub

sys.path.insert(0, r"__CHAT_ROOT__")

import importlib.util

spec = importlib.util.spec_from_file_location("padiem_chat_worker_child", r"__WORKER_PATH__")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
module._worker_app = None


class _Request:
    def __init__(self):
        self.url = "https://worker.example.test/health"
        self.js_object = object()


import asyncio

fake_env = SimpleNamespace()
response = asyncio.run(module.Default(fake_env).fetch(_Request()))

checks = {
    "WORKER_FIRST_INIT_COMPLETES": response is not None,
    "EXECUTED_REAL_COMPOSED_APP": bool(asgi_calls),
    "DISPATCHED_WITH_RUNTIME_ENV": bool(asgi_calls) and asgi_calls[0][2] is fake_env,
    "EXECUTION_TARGET_AUTHORITY_IS_THE_RUNTIME_ENV": (
        module._worker_app is not None
        and module._worker_app.state.claw_automation_execution_target_authority is fake_env
    ),
}
print(json.dumps({"ok": all(checks.values()), "checks": checks}))
"""


def _run_child() -> dict:
    # Token substitution, not str.format: the child source contains dict
    # literals whose braces would be read as format fields.
    code = _CHILD.replace("__CHAT_ROOT__", str(CHAT_ROOT)).replace(
        "__WORKER_PATH__", str(WORKER_PATH)
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(CHAT_ROOT),
    )
    line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return {
            "ok": False,
            "checks": {},
            "stderr": result.stderr[-2000:],
        }


def test_worker_first_initialization_injects_the_runtime_env() -> None:
    payload = _run_child()
    checks = payload.get("checks", {})
    for name in (
        "WORKER_FIRST_INIT_COMPLETES",
        "EXECUTED_REAL_COMPOSED_APP",
        "DISPATCHED_WITH_RUNTIME_ENV",
        "EXECUTION_TARGET_AUTHORITY_IS_THE_RUNTIME_ENV",
    ):
        assert checks.get(name) is True, f"{name}: {payload}"
    assert payload.get("ok") is True, payload