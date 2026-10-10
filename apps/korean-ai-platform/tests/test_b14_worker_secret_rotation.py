"""B14 Secrets Store rotation: no stale globals, cross-provider reuse or cross-task leak.

All credentials are synthetic; no Worker live POST/Secrets Store access.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.pilot import platform
from app.pilot.platform_secrets import (
    CredentialSource,
    PlatformProviderSpec,
    resolve_secret,
)
from app.pilot.worker_env import (
    bind_request_env,
    collect_env_overrides,
    reset_request_env,
    scoped_secret,
)


def spec(provider: str) -> PlatformProviderSpec:
    return PlatformProviderSpec(
        provider_id=provider,
        credential_source=CredentialSource.PLATFORM_SECRET,
        credential_binding_name=f"PADIEM_{provider.upper()}_API_KEY",
        base_origin=f"https://{provider}.example.net/v1",
        allowed_hosts=(f"{provider}.example.net",),
    )


@pytest.mark.asyncio
async def test_rotation_during_same_isolate_does_not_use_stale_global(monkeypatch):
    exlab = spec("experiential")
    monkeypatch.setenv(exlab.credential_binding_name, "synthetic_previous_secret")
    first = bind_request_env({exlab.credential_binding_name: "synthetic_first_secret"})
    try:
        assert resolve_secret(exlab) == "synthetic_first_secret"
        assert platform._request_headers(exlab)["Authorization"] == "Bearer synthetic_first_secret"
    finally:
        reset_request_env(first)

    second = bind_request_env({exlab.credential_binding_name: "synthetic_rotated_secret"})
    try:
        assert resolve_secret(exlab) == "synthetic_rotated_secret"
        assert platform._request_headers(exlab)["Authorization"] == "Bearer synthetic_rotated_secret"
    finally:
        reset_request_env(second)

    # CLI/test (outside Worker) retains the old environment contract.
    assert resolve_secret(exlab) == "synthetic_previous_secret"
    assert scoped_secret(exlab.credential_binding_name) is None


@pytest.mark.asyncio
async def test_missing_worker_secret_fails_closed_even_if_global_has_stale_key(monkeypatch):
    exlab = spec("experiential")
    gemini = spec("gemini")
    monkeypatch.setenv(exlab.credential_binding_name, "synthetic_global_exlab_key")
    monkeypatch.setenv(gemini.credential_binding_name, "synthetic_global_gemini_key")
    token = bind_request_env({gemini.credential_binding_name: "synthetic_worker_gemini"})
    try:
        assert resolve_secret(exlab) == ""
        assert resolve_secret(gemini) == "synthetic_worker_gemini"
        from app.pilot.errors import PilotNotConfigured

        with pytest.raises(PilotNotConfigured):
            platform._request_headers(exlab)
    finally:
        reset_request_env(token)


@pytest.mark.asyncio
async def test_two_overlapping_requests_keep_independent_exlab_and_gemini_keys():
    exlab, gemini = spec("experiential"), spec("gemini")
    ready = 0
    both = asyncio.Event()

    async def one_request(exlab_key, gemini_key):
        nonlocal ready
        token = bind_request_env({
            exlab.credential_binding_name: exlab_key,
            gemini.credential_binding_name: gemini_key,
        })
        try:
            ready += 1
            if ready == 2:
                both.set()
            await both.wait()
            await asyncio.sleep(0)
            return (
                platform._request_headers(exlab)["Authorization"],
                platform._request_headers(gemini)["Authorization"],
            )
        finally:
            reset_request_env(token)

    results = await asyncio.gather(
        one_request("synthetic_exlab_alpha", "synthetic_gemini_alpha"),
        one_request("synthetic_exlab_beta", "synthetic_gemini_beta"),
    )
    assert results == [
        ("Bearer synthetic_exlab_alpha", "Bearer synthetic_gemini_alpha"),
        ("Bearer synthetic_exlab_beta", "Bearer synthetic_gemini_beta"),
    ]
    assert scoped_secret(exlab.credential_binding_name) is None


@pytest.mark.asyncio
async def test_worker_scope_cleanup_on_error():
    exlab = spec("experiential")
    async def failing_handler():
        token = bind_request_env({exlab.credential_binding_name: "synthetic_key"})
        try:
            assert resolve_secret(exlab) == "synthetic_key"
            raise RuntimeError("synthetic_failure")
        finally:
            reset_request_env(token)
    with pytest.raises(RuntimeError, match="synthetic_failure"):
        await failing_handler()
    assert scoped_secret(exlab.credential_binding_name) is None


@pytest.mark.asyncio
async def test_resolve_fresh_secret_binding_get_each_request():
    class RotatableBinding:
        def __init__(self):
            self.counter = 0
        async def get(self):
            self.counter += 1
            return f"synthetic_rotation_{self.counter:02d}"

    class Env:
        PADIEM_EXPERIENTIAL_API_KEY = RotatableBinding()

    environment = Env()
    spec_exlab = spec("experiential")
    values = []
    for _ in range(2):
        overrides = await collect_env_overrides(environment, (spec_exlab.credential_binding_name,))
        token = bind_request_env(overrides)
        try:
            values.append(resolve_secret(spec_exlab))
        finally:
            reset_request_env(token)
    assert values == ["synthetic_rotation_01", "synthetic_rotation_02"]
    assert environment.PADIEM_EXPERIENTIAL_API_KEY.counter == 2


def test_worker_entrypoint_guards_scoped_binding_and_global_secret():
    worker = Path(__file__).resolve().parents[1] / "worker.py"
    contents = worker.read_text(encoding="utf-8")
    assert "token = bind_request_env(env_overrides)" in contents
    assert "finally:\n            reset_request_env(token)" in contents
    assert "if _env_key in _NON_SECRET_ENV_KEYS:" in contents
    assert "PADIEM_EXLAB_API_KEY" in contents  # stable account binding name
    assert 'if _env_key in _NON_SECRET_ENV_KEYS:\n            _os.environ' in contents

@pytest.mark.asyncio
async def test_actual_worker_fetch_scopes_and_resets_overlapping_requests(monkeypatch):
    import ast
    import sys
    from types import SimpleNamespace
    from urllib.parse import urlparse

    worker_text = (Path(__file__).resolve().parents[1] / "worker.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(worker_text)
    worker_class = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Default"
    )
    fetch = next(
        node for node in worker_class.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "fetch"
    )
    module = ast.Module(body=[fetch], type_ignores=[])
    globals_for_fetch = {
        "urlparse": urlparse,
        "_ENV_KEYS": frozenset({"PADIEM_EXPERIENTIAL_API_KEY"}),
        "_apply_env_once": lambda _: None,
        "_apply_security_headers": lambda response: response,
        "app": object(),
    }
    exec(compile(module, "<worker_entrypoint_scope_test>", "exec"), globals_for_fetch)  # noqa: S102
    worker_fetch = globals_for_fetch["fetch"]

    class Secret:
        def __init__(self, value):
            self.value = value

        async def get(self):
            return self.value

    entered = 0
    both_entered = asyncio.Event()

    async def fake_fetch(_app, label, _environment):
        nonlocal entered
        entered += 1
        if entered == 2:
            both_entered.set()
        await both_entered.wait()
        await asyncio.sleep(0)
        if label == "error":
            raise RuntimeError("synthetic_failed_handler")
        return {
            "scoped": scoped_secret("PADIEM_EXPERIENTIAL_API_KEY"),
        }

    monkeypatch.setitem(sys.modules, "asgi", SimpleNamespace(fetch=fake_fetch))

    def sender(value, label):
        environment = SimpleNamespace(
            PADIEM_EXPERIENTIAL_API_KEY=Secret(value),
        )
        request = SimpleNamespace(url="https://example.org/workspace", js_object=label)
        return worker_fetch(SimpleNamespace(env=environment), request)

    good, bad = await asyncio.gather(
        sender("synthetic_first_secret", "success"),
        sender("synthetic_second_secret", "error"),
        return_exceptions=True,
    )
    assert good["scoped"] == "synthetic_first_secret"
    assert isinstance(bad, RuntimeError)
    assert str(bad) == "synthetic_failed_handler"
    assert scoped_secret("PADIEM_EXPERIENTIAL_API_KEY") is None
