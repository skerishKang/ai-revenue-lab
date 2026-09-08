"""#1990 — the engine's B14 transport timeout covers B14's retry budget.

B14's same-route retry chain (#1988) has a 45s hard cap. The engine's
B14ExecutionConfig previously defaulted to 20s, so a retried B14 call was
cut off by the engine transport's TimeoutError (not an ExecutionRuntimeError)
and surfaced as engine_internal_error 500. The default is now 50s
(45s retry cap + 5s margin; the 60s orchestration budget keeps 10s headroom),
env-tunable via the PADIEM_ENGINE_B14_TIMEOUT_SECONDS plain Worker var.
Core's 1-60s bound is unchanged and re-pinned here.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import types
from pathlib import Path
from typing import Any

import httpx
import pytest
from padiem_ai_core import B14ChatRequest, B14ExecutionClient, B14ExecutionConfig

APP_ROOT = Path(__file__).resolve().parents[1]


class _FakeResponse:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass


class _FakeWorkerEntrypoint:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass


def _workers_stub() -> types.ModuleType:
    module = types.ModuleType("workers")
    module.Request = lambda *args, **kwargs: None  # type: ignore[attr-defined]
    module.Response = _FakeResponse  # type: ignore[attr-defined]
    module.WorkerEntrypoint = _FakeWorkerEntrypoint  # type: ignore[attr-defined]
    return module


@pytest.fixture()
def worker() -> Any:
    """Import the real worker.py with the workers runtime stubbed (same
    pattern as test_engine_canonical_composition_runtime)."""
    if str(APP_ROOT) not in sys.path:
        sys.path.insert(0, str(APP_ROOT))
    saved = {
        name: sys.modules.get(name)
        for name in ("workers", "worker", "worker_identity")
    }
    sys.modules["workers"] = _workers_stub()
    for name in ("worker", "worker_identity"):
        sys.modules.pop(name, None)
    try:
        yield importlib.import_module("worker")
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


class _Env:
    def __init__(self, **attrs: Any) -> None:
        self.__dict__.update(attrs)


# ---------------------------------------------------------------------------
# Config default + env wiring
# ---------------------------------------------------------------------------

def test_default_b14_timeout_is_50_seconds(worker: Any) -> None:
    assert worker.B14_TIMEOUT_DEFAULT_SECONDS == 50.0
    assert worker._b14_timeout_seconds_for_env(_Env()) == 50.0


def test_b14_timeout_is_env_tunable(worker: Any) -> None:
    env = _Env(PADIEM_ENGINE_B14_TIMEOUT_SECONDS="42.5")
    assert worker._b14_timeout_seconds_for_env(env) == 42.5
    # blank/whitespace falls back to the default, never 0
    assert worker._b14_timeout_seconds_for_env(
        _Env(PADIEM_ENGINE_B14_TIMEOUT_SECONDS="  ")
    ) == 50.0


def test_both_worker_compositions_pass_timeout_to_config() -> None:
    legacy_source = (APP_ROOT / "worker.py").read_text(encoding="utf-8")
    identity_source = (APP_ROOT / "worker_identity.py").read_text(encoding="utf-8")

    expected = "timeout_seconds=_b14_timeout_seconds_for_env(env)"
    assert expected in legacy_source
    assert "timeout_seconds=legacy_worker._b14_timeout_seconds_for_env(env)" in identity_source
    # no bare B14ExecutionConfig construction may remain without the timeout
    for source in (legacy_source, identity_source):
        for line in source.splitlines():
            if "B14ExecutionConfig(" in line and "base_url=B14_INTERNAL_ORIGIN)" in line:
                raise AssertionError(f"bare config construction: {line!r}")


# ---------------------------------------------------------------------------
# Core bound (1-60) re-pinned — Core contract unchanged
# ---------------------------------------------------------------------------

def test_core_bound_still_enforced() -> None:
    config = B14ExecutionConfig(
        base_url="https://b14.internal", timeout_seconds=50.0
    )
    assert config.timeout_seconds == 50.0
    with pytest.raises(ValueError, match="between 1 and 60"):
        B14ExecutionConfig(base_url="https://b14.internal", timeout_seconds=61)
    with pytest.raises(ValueError, match="between 1 and 60"):
        B14ExecutionConfig(base_url="https://b14.internal", timeout_seconds=0.5)


# ---------------------------------------------------------------------------
# Propagation: the transport receives the configured timeout
# ---------------------------------------------------------------------------

class _TimeoutCapturingTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.captured: dict[str, Any] | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.captured = dict(request.extensions.get("timeout") or {})
        return httpx.Response(
            200,
            json={
                "id": "cmpl-1",
                "model": "test/model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            },
        )


def test_transport_receives_configured_timeout(worker: Any) -> None:
    transport = _TimeoutCapturingTransport()
    config = B14ExecutionConfig(
        base_url="https://b14.internal",
        timeout_seconds=worker.B14_TIMEOUT_DEFAULT_SECONDS,
    )
    client = B14ExecutionClient(config, transport=transport)
    request = B14ChatRequest(
        messages=[{"role": "user", "content": "hi"}],
        model="test/model",
    )

    result = __import__("asyncio").run(client.execute(request))

    assert result.answer == "ok"
    assert transport.captured is not None
    # read timeout carries the full 50s budget; connect/write/pool stay at the
    # Core-capped 10s phase limits.
    assert transport.captured["read"] == 50.0
    assert transport.captured["connect"] == 10.0
