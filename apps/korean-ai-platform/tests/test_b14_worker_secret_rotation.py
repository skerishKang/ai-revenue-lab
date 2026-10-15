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
    collect_request_bindings,
    load_request_secret,
    reset_request_env,
    scoped_secret,
)


def spec(provider: str) -> PlatformProviderSpec:
    return PlatformProviderSpec(
        provider_id=provider,
        credential_source=CredentialSource.PLATFORM_SECRET,
        credential_binding_name=("PADIEM_B14_CREDENTIAL_05" if provider == "gemini" else f"PADIEM_{provider.upper()}_API_KEY"),
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
        overrides = collect_request_bindings(environment, (spec_exlab.credential_binding_name,))
        token = bind_request_env(overrides)
        try:
            await load_request_secret(spec_exlab.credential_binding_name)
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
    assert "PADIEM_B14_CREDENTIAL_04" in contents  # stable account binding name
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
        await load_request_secret("PADIEM_EXPERIENTIAL_API_KEY")
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


@pytest.mark.asyncio
async def test_lazy_gemini_does_not_fetch_unrelated_provider():
    from types import SimpleNamespace
    from app.pilot import platform as _registration  # noqa: F401
    from app.pilot.platform_secrets import ensure_route_secrets

    class CountingSecret:
        def __init__(self, value):
            self.value = value
            self.calls = 0

        async def get(self):
            self.calls += 1
            return self.value

    gemini = CountingSecret("synthetic_gemini_new")
    kira = CountingSecret("synthetic_kira_unrelated")
    exlab = CountingSecret("synthetic_exlab_unrelated")
    env = SimpleNamespace(
        PADIEM_B14_CREDENTIAL_05=gemini,
        PADIEM_B14_CREDENTIAL_09=kira,
        PADIEM_B14_CREDENTIAL_04=exlab,
    )
    handles = collect_request_bindings(env, (
        "PADIEM_B14_CREDENTIAL_05", "PADIEM_B14_CREDENTIAL_09", "PADIEM_B14_CREDENTIAL_04"
    ))
    assert (gemini.calls, kira.calls, exlab.calls) == (0, 0, 0)
    token = bind_request_env(handles)
    try:
        await ensure_route_secrets("google/gemini-3.1-flash-lite")
        await ensure_route_secrets("google/gemini-3.1-flash-lite")
        assert scoped_secret("PADIEM_B14_CREDENTIAL_05") == "synthetic_gemini_new"
        assert (gemini.calls, kira.calls, exlab.calls) == (1, 0, 0)
        assert scoped_secret("PADIEM_B14_CREDENTIAL_09") == ""
    finally:
        reset_request_env(token)
    assert scoped_secret("PADIEM_B14_CREDENTIAL_05") is None


@pytest.mark.asyncio
async def test_lazy_revoke_rotation_and_failed_get_are_fail_closed(monkeypatch):
    from types import SimpleNamespace
    key = "PADIEM_B14_CREDENTIAL_05"
    monkeypatch.setenv(key, "synthetic_global_must_not_be_used")

    class MutableSecret:
        calls = 0
        value = "synthetic_initial_secret"

        async def get(self):
            self.calls += 1
            if isinstance(self.value, Exception):
                raise self.value
            return self.value

    secret = MutableSecret()
    spec_gemini = spec("gemini")
    for candidate, expected in (
        ("synthetic_initial_secret", "synthetic_initial_secret"),
        ("synthetic_rotated_secret", "synthetic_rotated_secret"),
        (None, ""),
        (RuntimeError("synthetic_unavailable"), ""),
    ):
        secret.value = candidate
        token = bind_request_env(collect_request_bindings(
            SimpleNamespace(PADIEM_B14_CREDENTIAL_05=secret), (key,)
        ))
        try:
            assert resolve_secret(spec_gemini) == ""
            await load_request_secret(key)
            await load_request_secret(key)
            assert resolve_secret(spec_gemini) == expected
        finally:
            reset_request_env(token)
    assert secret.calls == 4


@pytest.mark.asyncio
async def test_lazy_overlapping_requests_isolate_handle_and_key():
    from types import SimpleNamespace
    key = "PADIEM_B14_CREDENTIAL_05"

    class BoundSecret:
        def __init__(self, value):
            self.value = value
            self.calls = 0

        async def get(self):
            self.calls += 1
            await asyncio.sleep(0)
            return self.value

    async def invoke(value):
        binding = BoundSecret(value)
        token = bind_request_env(collect_request_bindings(
            SimpleNamespace(PADIEM_B14_CREDENTIAL_05=binding), (key,)
        ))
        try:
            await load_request_secret(key)
            return (scoped_secret(key), binding.calls)
        finally:
            reset_request_env(token)

    assert await asyncio.gather(
        invoke("synthetic_request_alpha"), invoke("synthetic_request_beta")
    ) == [
        ("synthetic_request_alpha", 1),
        ("synthetic_request_beta", 1),
    ]


@pytest.mark.asyncio
async def test_auto_chain_fetches_only_chain_and_stops_without_fallback(monkeypatch):
    from app.pilot.b14_runtime_config import runtime_config
    monkeypatch.setattr(runtime_config, "provider_mode", "live")
    from types import SimpleNamespace
    from app.pilot import platform as _registration  # noqa: F401
    from app.pilot.routing_policy import B14_AUTO_CHAIN
    from app.pilot.platform_secrets import (
        ensure_route_secrets, get_platform_provider,
    )
    from app.pilot.catalog import get_catalog_by_id

    class Binding:
        def __init__(self, value):
            self.value = value
            self.calls = 0

        async def get(self):
            self.calls += 1
            return self.value

    chain_keys = [
        get_platform_provider(get_catalog_by_id(mid).platform_provider_id).credential_binding_name
        for mid in B14_AUTO_CHAIN
    ]
    assert len(chain_keys) == 2
    first, second, other = Binding("synthetic_agnes_usable"), Binding("synthetic_poolside"), Binding("synthetic_exlab")
    env = SimpleNamespace(**dict(zip(chain_keys, (first, second))),
                          PADIEM_B14_CREDENTIAL_04=other)
    token = bind_request_env(collect_request_bindings(
        env, (*chain_keys, "PADIEM_B14_CREDENTIAL_04")
    ))
    try:
        await ensure_route_secrets("b14/auto", allow_external_fallback=False)
        assert (first.calls, second.calls, other.calls) == (1, 0, 0)
    finally:
        reset_request_env(token)

    # Without fallback, a revoked primary must permit the next *ready*
    # fixed-chain position to be selected, not falsely report no route.
    first.value = None
    token = bind_request_env(collect_request_bindings(
        env, (*chain_keys, "PADIEM_B14_CREDENTIAL_04")
    ))
    try:
        await ensure_route_secrets("b14/auto", allow_external_fallback=False)
        assert (first.calls, second.calls, other.calls) == (2, 1, 0)
    finally:
        reset_request_env(token)
    first.value = "synthetic_agnes_usable"

    token = bind_request_env(collect_request_bindings(
        env, (*chain_keys, "PADIEM_B14_CREDENTIAL_04")
    ))
    try:
        await ensure_route_secrets("b14/auto", allow_external_fallback=True)
        assert (first.calls, second.calls, other.calls) == (3, 2, 0)
    finally:
        reset_request_env(token)



@pytest.mark.asyncio
async def test_same_request_concurrent_loads_share_inflight_read():
    from types import SimpleNamespace
    key = "PADIEM_B14_CREDENTIAL_05"

    class SlowSecret:
        calls = 0

        async def get(self):
            self.calls += 1
            await asyncio.sleep(0.001)
            return "synthetic_same_request"

    binding = SlowSecret()
    token = bind_request_env(collect_request_bindings(
        SimpleNamespace(PADIEM_B14_CREDENTIAL_05=binding), (key,)
    ))
    try:
        async def reader():
            await load_request_secret(key)
            return scoped_secret(key)

        assert await asyncio.gather(reader(), reader()) == [
            "synthetic_same_request", "synthetic_same_request",
        ]
        assert binding.calls == 1
    finally:
        reset_request_env(token)
