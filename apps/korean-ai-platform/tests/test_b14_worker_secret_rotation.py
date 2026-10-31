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
    credential_failure_reason,
    resolve_secret,
)
from app.pilot.worker_env import (
    bind_request_env,
    collect_env_overrides,
    collect_request_bindings,
    load_request_secret,
    reset_request_env,
    scoped_secret,
    secret_status,
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
    # The stable neutral slot is what the request scope must carry. It reaches
    # the entrypoint through the registry now instead of a hand-listed key, so
    # the name is pinned at the authority that owns it — and the legacy
    # provider-named key must not come back through either door.
    from app.pilot.model_registry_file import (
        credential_binding_names, read_registry,
    )

    assert read_registry()["providers"]["experiential"][
        "credential_binding_name"
    ] == "PADIEM_B14_CREDENTIAL_04"
    assert "PADIEM_B14_CREDENTIAL_04" in credential_binding_names()
    assert "PADIEM_EXPERIENTIAL_API_KEY" not in contents
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
async def test_retired_auto_chain_prep_loads_nothing_and_manual_prep_loads_its_route(monkeypatch):
    """B7: the b14/auto secret-prep branch is gone with the chain.

    The retired id resolves to no catalog model, so no Provider binding is
    fetched for it; a manual route still preloads exactly its own binding.
    """
    from app.pilot.b14_runtime_config import runtime_config
    monkeypatch.setattr(runtime_config, "provider_mode", "live")
    from types import SimpleNamespace
    from app.pilot import platform as _registration  # noqa: F401
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

    manual_id = "agnes-ai/agnes-3.0-flash"
    manual_key = get_platform_provider(
        get_catalog_by_id(manual_id).platform_provider_id
    ).credential_binding_name
    other_key = "PADIEM_B14_CREDENTIAL_04"
    first, other = Binding("synthetic_agnes_usable"), Binding("synthetic_exlab")
    env = SimpleNamespace(**{manual_key: first, other_key: other})
    token = bind_request_env(collect_request_bindings(env, (manual_key, other_key)))
    try:
        await ensure_route_secrets("b14/auto")
        await ensure_route_secrets(manual_id)
        assert (first.calls, other.calls) == (1, 0)
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

def test_every_neutral_wrangler_secret_is_collected_by_worker():
    """Keep declared Secrets Store handles accessible in the request scope."""
    import ast
    import tomllib

    root = Path(__file__).resolve().parents[1]
    worker_src = (root / "worker.py").read_text(encoding="utf-8")
    tree = ast.parse(worker_src)

    def _assignment(target_id: str):
        return next(
            node for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == target_id
                for target in node.targets
            )
        )

    from app.pilot.model_registry_file import (
        credential_binding_names as registry_credential_names,
    )

    # Evaluated from the entrypoint's own expression, so this stays true to what
    # the Worker actually collects rather than what a test unions here.
    scope: dict[str, object] = {}
    for node in (_assignment("_FIXED_ENV_KEYS"), _assignment("_ENV_KEYS")):
        exec(
            compile(ast.Module(body=[node], type_ignores=[]), "worker.py", "exec"),
            {"credential_binding_names": registry_credential_names},
            scope,
        )
    collected = set(scope["_ENV_KEYS"])
    wrangler = tomllib.loads((root / "wrangler.toml").read_text(encoding="utf-8"))
    declared = {
        entry["binding"] for entry in wrangler["secrets_store_secrets"]
        if entry["binding"].startswith("PADIEM_B14_CREDENTIAL_")
    }
    assert len(declared) == 14
    assert declared <= collected

# ---------------------------------------------------------------------------
# Value-free resolution diagnostics (#4983 follow-up)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_binding_failure_status_is_value_free_and_classified():
    from types import SimpleNamespace

    key = "PADIEM_B14_CREDENTIAL_11"

    class JsLikeError(Exception):
        name = "Error"

    class RaisingSecret:
        def __init__(self, exc):
            self.exc = exc

        async def get(self):
            raise self.exc

    cases = (
        (JsLikeError('Secret "secret-value-canary" not found'), "error:not_found"),
        (JsLikeError("Cannot perform I/O on behalf of a different request"), "error:cross_request"),
        (JsLikeError("binding not implemented in this runtime"), "error:unsupported"),
        (RuntimeError("secret-value-canary"), "error:RuntimeError"),
    )
    for exc, expected in cases:
        token = bind_request_env(collect_request_bindings(
            SimpleNamespace(**{key: RaisingSecret(exc)}), (key,)
        ))
        try:
            await load_request_secret(key)
            status = secret_status(key)
            assert status == expected
            assert "secret-value-canary" not in status
            assert scoped_secret(key) == ""
        finally:
            reset_request_env(token)
    assert secret_status(key) == ""


@pytest.mark.asyncio
async def test_binding_status_distinguishes_missing_empty_and_resolved():
    from types import SimpleNamespace

    key = "PADIEM_B14_CREDENTIAL_11"

    class PlainSecret:
        def __init__(self, value):
            self.value = value

        async def get(self):
            return self.value

    for binding, expected, scoped in (
        (None, "missing", ""),
        (PlainSecret(""), "empty", ""),
        (PlainSecret("synthetic_value_11"), "resolved", "synthetic_value_11"),
    ):
        env = SimpleNamespace() if binding is None else SimpleNamespace(**{key: binding})
        token = bind_request_env(collect_request_bindings(env, (key,)))
        try:
            await load_request_secret(key)
            assert secret_status(key) == expected
            assert scoped_secret(key) == scoped
        finally:
            reset_request_env(token)


@pytest.mark.asyncio
async def test_credential_failure_reason_is_value_free():
    from types import SimpleNamespace

    key = "PADIEM_B14_CREDENTIAL_11"
    provider = PlatformProviderSpec(
        provider_id="opencode-go",
        credential_source=CredentialSource.PLATFORM_SECRET,
        credential_binding_name=key,
        base_origin="https://opencode.example/v1",
        allowed_hosts=("opencode.example",),
    )

    class PlainSecret:
        def __init__(self, value):
            self.value = value

        async def get(self):
            return self.value

    class JsLikeError(Exception):
        name = "Error"

    class RaisingSecret:
        async def get(self):
            raise JsLikeError('Secret "secret-value-canary" not found')

    cases = (
        (PlainSecret(""), "empty"),
        (PlainSecret("test-key-placeholder-123"), "placeholder"),
        (PlainSecret("synthetic_value_11"), ""),
        (RaisingSecret(), "error:not_found"),
    )
    for binding, expected in cases:
        token = bind_request_env(collect_request_bindings(
            SimpleNamespace(**{key: binding}), (key,)
        ))
        try:
            await load_request_secret(key)
            reason = credential_failure_reason(provider)
            assert reason == expected
            assert "secret-value-canary" not in reason
        finally:
            reset_request_env(token)

    # Uncollected/unresolved binding inside a request is not "empty".
    token = bind_request_env({})
    try:
        assert credential_failure_reason(provider) == "unresolved"
    finally:
        reset_request_env(token)

    # Outside a Worker request the CLI env contract (or absence) applies.
    assert credential_failure_reason(provider) == ""
