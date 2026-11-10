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

from _registry_values import requires_owner_document


#: Two synthetic Providers this suite rotates independently. Their binding
#: NAMES are generated from the same placeholder identity as the Provider, so
#: no deployment credential slot is written here (#7241 3단계).
FIRST_PROVIDER = "example-provider-01"
SECOND_PROVIDER = "example-provider-02"


def _binding(provider: str) -> str:
    """The placeholder credential NAME this suite seeds for a synthetic lane."""
    return "PADIEM_" + provider.upper().replace("-", "_")


def spec(provider: str) -> PlatformProviderSpec:
    return PlatformProviderSpec(
        provider_id=provider,
        credential_source=CredentialSource.PLATFORM_SECRET,
        credential_binding_name=_binding(provider),
        base_origin=f"https://{provider}.example.invalid/v1",
        allowed_hosts=(f"{provider}.example.invalid",),
    )


def _binding_attribute(provider: str) -> str:
    """The JS-environment attribute name a Worker hands that binding in under."""
    return _binding(provider)


#: A synthetic binding NAME for the contracts that only need *a* slot: the
#: Worker scope machinery is exercised on its own, so no deployment slot name is
#: written here (#7241 3단계).
SCOPED_BINDING = _binding(FIRST_PROVIDER)
#: A second synthetic name for the per-request diagnostics contracts.
DIAGNOSTIC_BINDING = _binding("example-provider-03")


def _model_for_spec(provider_spec: PlatformProviderSpec) -> str:
    """A registered model the given Provider answers, read from the registry.

    #7241 3a: which model the routing-secret loader is asked about is a
    deployment value, so it is selected from the effective document by the
    Provider's own credential binding instead of being written here. The
    provider's binding is what the loader dereferences, so the choice keeps this
    suite pinned to the binding it seeds.
    """
    from app.pilot.model_registry_file import read_registry

    reg = read_registry()
    binding = provider_spec.credential_binding_name
    for row in reg["models"]:
        provider = reg["providers"].get(row.get("provider_id"), {})
        if provider.get("credential_binding_name") == binding and row.get("enabled", True):
            return row["id"]
    raise AssertionError("the registry routes no enabled model for this binding")


@pytest.mark.asyncio
async def test_rotation_during_same_isolate_does_not_use_stale_global(monkeypatch):
    gamma = spec(FIRST_PROVIDER)
    monkeypatch.setenv(gamma.credential_binding_name, "synthetic_previous_secret")
    first = bind_request_env({gamma.credential_binding_name: "synthetic_first_secret"})
    try:
        assert resolve_secret(gamma) == "synthetic_first_secret"
        assert platform._request_headers(gamma)["Authorization"] == "Bearer synthetic_first_secret"
    finally:
        reset_request_env(first)

    second = bind_request_env({gamma.credential_binding_name: "synthetic_rotated_secret"})
    try:
        assert resolve_secret(gamma) == "synthetic_rotated_secret"
        assert platform._request_headers(gamma)["Authorization"] == "Bearer synthetic_rotated_secret"
    finally:
        reset_request_env(second)

    # CLI/test (outside Worker) retains the old environment contract.
    assert resolve_secret(gamma) == "synthetic_previous_secret"
    assert scoped_secret(gamma.credential_binding_name) is None


@pytest.mark.asyncio
async def test_missing_worker_secret_fails_closed_even_if_global_has_stale_key(monkeypatch):
    gamma = spec(FIRST_PROVIDER)
    alpha = spec(SECOND_PROVIDER)
    monkeypatch.setenv(gamma.credential_binding_name, "synthetic_global_gamma_key")
    monkeypatch.setenv(alpha.credential_binding_name, "synthetic_global_alpha_key")
    token = bind_request_env({alpha.credential_binding_name: "synthetic_worker_alpha"})
    try:
        assert resolve_secret(gamma) == ""
        assert resolve_secret(alpha) == "synthetic_worker_alpha"
        from app.pilot.errors import PilotNotConfigured

        with pytest.raises(PilotNotConfigured):
            platform._request_headers(gamma)
    finally:
        reset_request_env(token)


@pytest.mark.asyncio
async def test_two_overlapping_requests_keep_independent_gamma_and_alpha_keys():
    gamma, alpha = spec(FIRST_PROVIDER), spec(SECOND_PROVIDER)
    ready = 0
    both = asyncio.Event()

    async def one_request(gamma_key, alpha_key):
        nonlocal ready
        token = bind_request_env({
            gamma.credential_binding_name: gamma_key,
            alpha.credential_binding_name: alpha_key,
        })
        try:
            ready += 1
            if ready == 2:
                both.set()
            await both.wait()
            await asyncio.sleep(0)
            return (
                platform._request_headers(gamma)["Authorization"],
                platform._request_headers(alpha)["Authorization"],
            )
        finally:
            reset_request_env(token)

    results = await asyncio.gather(
        one_request("synthetic_gamma_alpha", "synthetic_alpha_alpha"),
        one_request("synthetic_gamma_beta", "synthetic_alpha_beta"),
    )
    assert results == [
        ("Bearer synthetic_gamma_alpha", "Bearer synthetic_alpha_alpha"),
        ("Bearer synthetic_gamma_beta", "Bearer synthetic_alpha_beta"),
    ]
    assert scoped_secret(gamma.credential_binding_name) is None


@pytest.mark.asyncio
async def test_worker_scope_cleanup_on_error():
    gamma = spec(FIRST_PROVIDER)
    async def failing_handler():
        token = bind_request_env({gamma.credential_binding_name: "synthetic_key"})
        try:
            assert resolve_secret(gamma) == "synthetic_key"
            raise RuntimeError("synthetic_failure")
        finally:
            reset_request_env(token)
    with pytest.raises(RuntimeError, match="synthetic_failure"):
        await failing_handler()
    assert scoped_secret(gamma.credential_binding_name) is None


@pytest.mark.asyncio
async def test_resolve_fresh_secret_binding_get_each_request():
    class RotatableBinding:
        def __init__(self):
            self.counter = 0
        async def get(self):
            self.counter += 1
            return f"synthetic_rotation_{self.counter:02d}"

    attribute = _binding_attribute(FIRST_PROVIDER)

    class Env:
        pass

    environment = Env()
    setattr(environment, attribute, RotatableBinding())
    spec_gamma = spec(FIRST_PROVIDER)
    values = []
    for _ in range(2):
        overrides = collect_request_bindings(environment, (spec_gamma.credential_binding_name,))
        token = bind_request_env(overrides)
        try:
            await load_request_secret(spec_gamma.credential_binding_name)
            values.append(resolve_secret(spec_gamma))
        finally:
            reset_request_env(token)
    assert values == ["synthetic_rotation_01", "synthetic_rotation_02"]
    assert getattr(environment, attribute).counter == 2


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

    # The binding the request scope must carry is the one the effective
    # document declares, so the name is read from that authority (#7241 3단계).
    declared = sorted(credential_binding_names())
    assert declared, "the effective document declares no credential binding"
    slot = declared[0]
    provider_id = next(
        pid for pid, row in read_registry()["providers"].items()
        if row["credential_binding_name"] == slot
    )
    assert read_registry()["providers"][provider_id]["credential_binding_name"] == slot
    assert slot in credential_binding_names()
    # No provider-named key may come back through either door: the entrypoint
    # collects through the registry, never through a hand-listed slot.
    for provider_id_entry in read_registry()["providers"]:
        assert "PADIEM_" + provider_id_entry.upper().replace("-", "_") not in contents
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
        "_ENV_KEYS": frozenset({SCOPED_BINDING}),
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
        await load_request_secret(SCOPED_BINDING)
        return {
            "scoped": scoped_secret(SCOPED_BINDING),
        }

    monkeypatch.setitem(sys.modules, "asgi", SimpleNamespace(fetch=fake_fetch))

    def sender(value, label):
        environment = SimpleNamespace(
            **{SCOPED_BINDING: Secret(value)},
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
    assert scoped_secret(SCOPED_BINDING) is None


@pytest.mark.asyncio
async def test_lazy_alpha_does_not_fetch_unrelated_provider():
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

    alpha = CountingSecret("synthetic_alpha_new")
    beta = CountingSecret("synthetic_beta_unrelated")
    gamma = CountingSecret("synthetic_gamma_unrelated")
    # The bindings this scope collects are the effective document's own names;
    # only the selected route's own Provider may be fetched (#7241 3\ub2e8\uacc4).
    from app.pilot.model_registry_file import read_registry
    from app.pilot.tier_fallback import effective_tier_default, effective_tier_fallback

    document = read_registry()
    routed = [
        (row["id"], document["providers"][row["provider_id"]]["credential_binding_name"])
        for row in document["models"]
        if row.get("enabled", True)
        and document["providers"][row["provider_id"]]["enabled"]
        and document["providers"][row["provider_id"]]["credential_source"]
        == CredentialSource.PLATFORM_SECRET.value
    ]
    assert len(routed) >= 2, "the effective document routes fewer than two credential lanes"
    # One selected lane and one lane under a *different* Provider: the route of
    # the first must never reach the second Provider's handle. (A single
    # Provider's other rows are not a separate lane for this contract.)
    selected_per_provider: dict[str, tuple[str, str]] = {}
    for model_id, binding in routed:
        selected_per_provider.setdefault(binding, (model_id, model_id.split("/", 1)[0]))
    distinct = list(selected_per_provider.items())
    assert len(distinct) >= 2, "the effective document declares no unrelated Provider lane"
    # The lane is asked for under its own grade. Asking under the free grade is
    # the one request the loader widens to the grade's recovery roster, so the
    # single-route contract is stated on a grade whose roster it would not load.
    for grade in ("plus", "pro", "max"):
        if grade in effective_tier_fallback():
            break
    else:  # pragma: no cover - the fixture declares the paid grades
        pytest.skip("the effective document declares no paid grade")
    selected_binding, (selected_model, _selected_provider) = distinct[0]
    unrelated = [binding for binding, _row in distinct[1:]][:2]
    while len(unrelated) < 2:
        unrelated.append(unrelated[0] + "_UNRELATED")
    alpha_binding, beta_binding, gamma_binding = (
        selected_binding, unrelated[0], unrelated[1]
    )
    env = SimpleNamespace(**{
        alpha_binding: alpha, beta_binding: beta, gamma_binding: gamma,
    })
    handles = collect_request_bindings(env, (alpha_binding, beta_binding, gamma_binding))
    assert (alpha.calls, beta.calls, gamma.calls) == (0, 0, 0)
    token = bind_request_env(handles)
    try:
        model_id = selected_model
        await ensure_route_secrets(model_id, product_tier=grade)
        await ensure_route_secrets(model_id, product_tier=grade)
        assert scoped_secret(alpha_binding) == "synthetic_alpha_new"
        assert (alpha.calls, beta.calls, gamma.calls) == (1, 0, 0)
        assert scoped_secret(beta_binding) == ""
    finally:
        reset_request_env(token)
    assert scoped_secret(alpha_binding) is None


@pytest.mark.asyncio
async def test_lazy_revoke_rotation_and_failed_get_are_fail_closed(monkeypatch):
    from types import SimpleNamespace
    spec_alpha = spec(SECOND_PROVIDER)
    key = spec_alpha.credential_binding_name
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
    for candidate, expected in (
        ("synthetic_initial_secret", "synthetic_initial_secret"),
        ("synthetic_rotated_secret", "synthetic_rotated_secret"),
        (None, ""),
        (RuntimeError("synthetic_unavailable"), ""),
    ):
        secret.value = candidate
        token = bind_request_env(collect_request_bindings(
            SimpleNamespace(**{key: secret}), (key,)
        ))
        try:
            assert resolve_secret(spec_alpha) == ""
            await load_request_secret(key)
            await load_request_secret(key)
            assert resolve_secret(spec_alpha) == expected
        finally:
            reset_request_env(token)
    assert secret.calls == 4


@pytest.mark.asyncio
async def test_lazy_overlapping_requests_isolate_handle_and_key():
    from types import SimpleNamespace
    key = SCOPED_BINDING

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
            SimpleNamespace(**{key: binding}), (key,)
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
async def test_same_request_concurrent_loads_share_inflight_read():
    from types import SimpleNamespace
    key = SCOPED_BINDING

    class SlowSecret:
        calls = 0

        async def get(self):
            self.calls += 1
            await asyncio.sleep(0.001)
            return "synthetic_same_request"

    binding = SlowSecret()
    token = bind_request_env(collect_request_bindings(
        SimpleNamespace(**{key: binding}), (key,)
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


@requires_owner_document
def test_every_neutral_wrangler_secret_is_collected_by_worker():
    """Keep declared Secrets Store handles accessible in the request scope.

    The pin compares the deployment's declared slots with the names the effective
    document declares, so it needs the owner document: the placeholder fixture
    declares synthetic slots the deployment does not bind (#7241 3b).
    """
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
    # The Secrets Store block is read as structure: every declared handle that
    # is a credential *slot* (the deployment's neutral prefix, which is the
    # block's own naming convention) must reach the request scope. No slot name
    # is written here (#7241 3단계).
    declared = {
        entry["binding"] for entry in wrangler["secrets_store_secrets"]
        if entry["binding"].startswith(
            next(iter(registry_credential_names())).rstrip("0123456789_")
        )
    }
    assert declared
    assert declared <= collected

# ---------------------------------------------------------------------------
# Value-free resolution diagnostics (#4983 follow-up)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_binding_failure_status_is_value_free_and_classified():
    from types import SimpleNamespace

    key = DIAGNOSTIC_BINDING

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

    key = DIAGNOSTIC_BINDING

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

    key = DIAGNOSTIC_BINDING
    provider = PlatformProviderSpec(
        provider_id="example-provider-03",
        credential_source=CredentialSource.PLATFORM_SECRET,
        credential_binding_name=key,
        base_origin="https://example-provider-03.example.invalid/v1",
        allowed_hosts=("example-provider-03.example.invalid",),
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
