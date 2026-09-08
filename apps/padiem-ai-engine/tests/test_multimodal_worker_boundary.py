"""Canonical-entrypoint boundary proof for Engine E5A (#1750).

Locks the composition-root invariant that adding the trusted multimodal route
leaves every pre-existing Engine route family unchanged and never opens a
browser/public surface.
"""

from __future__ import annotations

import asyncio
import ast
import importlib
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

CALLER_ID = "e5-boundary-caller"
CALLER_SECRET = "e5-boundary-secret-0123456789abcdef-0123456789abcdef"
ALLOWED_APP = "b62"
MULTIMODAL_PATH = "/internal/v1/multimodal/execute"
MULTIMODAL_STREAM_PATH = "/internal/v1/multimodal/stream"
VALID_REF = "att_F1xture-Ref_000123"


class _FakeResponse:
    def __init__(self, body: Any = None, status: int = 200, headers: Any = None) -> None:
        self.body = body
        self.status = status
        self.headers = headers or {}


class _FakeWorkerEntrypoint:
    def __init__(self, ctx: Any = None, env: Any = None) -> None:
        self.ctx = ctx
        self.env = env


def _workers_stub() -> types.ModuleType:
    module = types.ModuleType("workers")
    module.Request = lambda *args, **kwargs: None  # type: ignore[attr-defined]
    module.Response = _FakeResponse  # type: ignore[attr-defined]
    module.WorkerEntrypoint = _FakeWorkerEntrypoint  # type: ignore[attr-defined]
    return module


@pytest.fixture(scope="module")
def identity_modules():
    saved = {
        name: sys.modules.get(name) for name in ("workers", "worker", "worker_identity")
    }
    sys.modules["workers"] = _workers_stub()
    for name in ("worker", "worker_identity"):
        sys.modules.pop(name, None)
    try:
        identity = importlib.import_module("worker_identity")
        legacy = importlib.import_module("worker")
        yield legacy, identity
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


class _Env:
    def __init__(self, **attrs: Any) -> None:
        self.__dict__.update(attrs)


class _Request:
    def __init__(
        self,
        path: str,
        *,
        method: str = "POST",
        body: bytes = b"{}",
        authenticated: bool = True,
    ) -> None:
        self.url = f"https://engine.internal{path}"
        self.method = method
        headers: dict[str, str] = {"content-type": "application/json"}
        if authenticated:
            headers["x-padiem-engine-caller"] = CALLER_ID
            headers["x-padiem-engine-credential"] = CALLER_SECRET
        self.headers = headers
        self._text = body.decode("utf-8")

    async def text(self) -> str:
        return self._text


def _identity_env(**extra: Any) -> _Env:
    return _Env(
        PADIEM_ENGINE_CALLER_ID=CALLER_ID,
        PADIEM_ENGINE_CALLER_SECRET=CALLER_SECRET,
        PADIEM_ENGINE_ALLOWED_APPS=ALLOWED_APP,
        **extra,
    )


def _fetch(identity: Any, env: Any, request: Any) -> Any:
    return asyncio.run(identity.Default(ctx=None, env=env).fetch(request))


def _body(response: Any) -> dict:
    return json.loads(str(response.body))


def _execute_body() -> bytes:
    return json.dumps({"app_id": ALLOWED_APP}).encode("utf-8")


def _multimodal_payload() -> bytes:
    return json.dumps(
        {
            "app_id": ALLOWED_APP,
            "agent": {
                "id": "vision-assistant",
                "title": "Vision Assistant",
                "description": "Bounded image-aware assistant fixture.",
                "system_instruction": "Describe the attached image factually.",
                "task_type": "general",
                "optimize_for": "balanced",
                "max_tokens": 256,
                "model_policy": {"model": "test/route"},
            },
            "messages": [{"role": "user", "content": "What is in this image?"}],
            "attachment_ref": VALID_REF,
        }
    ).encode("utf-8")


class _FakeD1Statement:
    """D1-shaped statement that must never be exercised without trusted scope."""

    def bind(self, *_params: Any) -> "_FakeD1Statement":
        return self

    async def first(self) -> None:
        raise AssertionError("no D1 read may occur without a trusted scope")

    async def run(self) -> None:
        raise AssertionError("no D1 write may occur without a trusted scope")


class _FakeD1Binding:
    def prepare(self, _sql: str) -> _FakeD1Statement:
        return _FakeD1Statement()


@pytest.mark.parametrize(
    ("path", "expected_code"),
    [
        ("/internal/v1/execute", "b14_service_unavailable"),
        ("/internal/v1/stream", "b14_service_unavailable"),
        ("/internal/v1/orchestrate", "b14_service_unavailable"),
        ("/internal/v1/research", "b14_service_unavailable"),
        ("/internal/v1/memory/retrieve", "memory_binding_unavailable"),
        ("/internal/v1/memory/write", "memory_write_binding_unavailable"),
        ("/internal/v1/agent-skill/run", "agent_skill_runtime_unavailable"),
    ],
)
def test_canonical_entrypoint_preserves_existing_route_behavior(
    identity_modules, path: str, expected_code: str
) -> None:
    """E5A must not alter execute/stream/orchestration/research/memory/agent-skill."""

    _legacy, identity = identity_modules

    response = _fetch(identity, _identity_env(), _Request(path, body=_execute_body()))

    assert response.status == 503
    assert _body(response)["error"]["code"] == expected_code


def test_canonical_entrypoint_keeps_health_public_and_existing_auth_boundary(
    identity_modules,
) -> None:
    from app.service import HEALTH_PATH

    _legacy, identity = identity_modules

    health = _fetch(identity, _Env(), _Request(HEALTH_PATH, method="GET"))
    assert health.status == 200
    assert _body(health)["service_identity"] == "required_for_all_non_health_routes"

    unauthorized = _fetch(
        identity,
        _identity_env(),
        _Request("/internal/v1/execute", body=_execute_body(), authenticated=False),
    )
    assert unauthorized.status == 401
    assert _body(unauthorized)["error"]["code"] == "service_authentication_failed"


def test_multimodal_route_is_not_a_public_or_browser_surface(identity_modules) -> None:
    from app.contract_manifest import EngineFeatureState, current_engine_contract_manifest

    _legacy, identity = identity_modules

    manifest = current_engine_contract_manifest()
    assert manifest.feature_state("public_browser_api") is EngineFeatureState.UNAVAILABLE

    identity_source = (APP_ROOT / "worker_identity.py").read_text(encoding="utf-8")
    assert "Access-Control-Allow-Origin" not in identity_source
    assert "workers.dev" not in identity_source
    assert "MULTIMODAL_EXECUTE_PATH" in identity_source
    assert "_authenticate_non_health_request" in identity_source


def test_legacy_worker_is_not_widened_by_e5a(identity_modules) -> None:
    legacy, _identity = identity_modules
    legacy_source = (APP_ROOT / "worker.py").read_text(encoding="utf-8")

    assert "multimodal" not in legacy_source
    assert "MultimodalAttachmentEngineService" not in legacy_source
    assert "MULTIMODAL_EXECUTE_PATH" not in legacy_source

    assert asyncio.run(legacy._engine_services_for_env(_identity_env())).multimodal is None
    assert (
        asyncio.run(legacy._engine_services_for_env(_identity_env())).multimodal_streaming is None
    )


def test_canonical_composition_wires_multimodal_service_without_authorities(
    identity_modules,
) -> None:
    """Production composition has no trusted attachment authority in either shape."""

    from app.multimodal_attachment_service import (
        MultimodalAttachmentEngineService,
        MultimodalStreamingEngineService,
    )

    _legacy, identity = identity_modules

    for env in (_identity_env(), _identity_env(B14_SERVICE=object())):
        services = asyncio.run(identity._engine_services_for_env(env))
        assert isinstance(services.multimodal, MultimodalAttachmentEngineService)
        assert services.multimodal._image_byte_store is None
        assert services.multimodal._scope_authority is None
        assert isinstance(services.multimodal_streaming, MultimodalStreamingEngineService)
        assert services.multimodal_streaming._image_byte_store is None
        assert services.multimodal_streaming._scope_authority is None


def test_bound_image_store_composes_but_still_fails_closed_without_scope_authority(
    identity_modules,
) -> None:
    """#2182 S5: a bound ``ENGINE_IMAGE_STORE`` reaches the service; the missing
    Control Plane scope authority still fails the route closed.

    The store is composed for real, so this proves the binding seam works. The
    scope triple cannot be server-minted yet, so no resolver is built, no D1
    query runs and no Core/B14 execution is reached.
    """

    from app.attachment_byte_store import CloudflareD1ImageByteStore, ScopedImageByteStore

    _legacy, identity = identity_modules
    env = _identity_env(ENGINE_IMAGE_STORE=_FakeD1Binding())
    services = asyncio.run(identity._engine_services_for_env(env))
    store = services.multimodal._image_byte_store

    assert isinstance(store, ScopedImageByteStore)
    assert isinstance(store._port, CloudflareD1ImageByteStore)
    assert services.multimodal._scope_authority is None
    assert services.multimodal_streaming._scope_authority is None

    runtime_calls: list[str] = []
    original = services.multimodal._runtime_factory

    def counting_runtime_factory(app_id: str) -> Any:
        runtime_calls.append(app_id)
        return original(app_id)

    services.multimodal._runtime_factory = counting_runtime_factory

    def bound_factory(_env: Any) -> Any:
        async def _ready():
            return services

        return _ready()

    saved = identity.Default.engine_services_factory
    identity.Default.engine_services_factory = staticmethod(bound_factory)
    try:
        response = _fetch(
            identity, env, _Request(MULTIMODAL_PATH, body=_multimodal_payload())
        )
    finally:
        identity.Default.engine_services_factory = staticmethod(saved)

    assert response.status == 503
    assert _body(response)["error"]["code"] == "attachment_resolver_unavailable"
    assert runtime_calls == []


def test_malformed_image_store_binding_composes_no_store(identity_modules) -> None:
    """A present-but-unusable binding yields no store; it never fakes one."""

    _legacy, identity = identity_modules
    for malformed in (object(), "", 0, {"binding": "ENGINE_IMAGE_STORE"}, [], b"d1"):
        services = asyncio.run(
            identity._engine_services_for_env(
                _identity_env(ENGINE_IMAGE_STORE=malformed)
            )
        )
        assert services.multimodal._image_byte_store is None, repr(malformed)
        assert services.multimodal_streaming._image_byte_store is None, repr(malformed)


def test_connector_grants_binding_is_never_the_attachment_store(
    identity_modules,
) -> None:
    """#2181 correction: the grants D1 store must not be borrowed for bytes."""

    from app.connector_grants_d1 import CloudflareD1ConnectorGrantStore

    _legacy, identity = identity_modules
    services = asyncio.run(
        identity._engine_services_for_env(
            _identity_env(ENGINE_CONNECTOR_GRANTS=_FakeD1Binding())
        )
    )
    assert services.multimodal._image_byte_store is None
    assert services.multimodal_streaming._image_byte_store is None
    assert not isinstance(services.multimodal._image_byte_store, CloudflareD1ConnectorGrantStore)

    identity_source = (APP_ROOT / "worker_identity.py").read_text(encoding="utf-8")
    tree = ast.parse(identity_source)
    factory = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_image_byte_store_for_env"
    )
    factory_source = ast.get_source_segment(identity_source, factory) or ""
    assert "ENGINE_IMAGE_STORE" in factory_source
    assert "CONNECTOR_GRANTS" not in factory_source
    assert "ScopedImageByteStore" in factory_source
    assert "CloudflareD1ImageByteStore" in factory_source


def test_execute_and_stream_share_the_same_authority_composition(
    identity_modules,
) -> None:
    """One store object and one authority seam serve both multimodal routes."""

    _legacy, identity = identity_modules
    env = _identity_env(ENGINE_IMAGE_STORE=_FakeD1Binding())
    services = asyncio.run(identity._engine_services_for_env(env))

    assert services.multimodal._image_byte_store is services.multimodal_streaming._image_byte_store
    assert services.multimodal._scope_authority is services.multimodal_streaming._scope_authority
    assert services.multimodal._image_byte_store is not None
    assert services.multimodal._scope_authority is None


def test_multimodal_request_is_rejected_before_any_composition_or_resolution(
    identity_modules,
) -> None:
    """Service identity fails closed before the attachment composition is built.

    Reaching ``engine_services_factory`` at all would mean an unauthenticated
    caller touched attachment resolution or Core/B14 execution wiring.
    """

    _legacy, identity = identity_modules

    def forbidden_composition(env: Any) -> Any:
        async def _forbidden():
            raise AssertionError("attachment composition reached before service identity")

        return _forbidden()

    saved = identity.Default.engine_services_factory
    identity.Default.engine_services_factory = staticmethod(forbidden_composition)
    try:
        response = _fetch(
            identity,
            _identity_env(),
            _Request(MULTIMODAL_PATH, body=_multimodal_payload(), authenticated=False),
        )
    finally:
        identity.Default.engine_services_factory = staticmethod(saved)

    assert response.status == 401
    assert _body(response)["error"]["code"] == "service_authentication_failed"


def test_multimodal_stream_request_is_rejected_before_any_composition_or_resolution(
    identity_modules,
) -> None:
    """The stream route shares the execute route's auth gate and error shape.

    Reaching ``engine_services_factory`` at all would mean an unauthenticated
    caller touched attachment resolution or streaming composition.
    """

    _legacy, identity = identity_modules

    def forbidden_composition(env: Any) -> Any:
        async def _forbidden():
            raise AssertionError("stream composition reached before service identity")

        return _forbidden()

    saved = identity.Default.engine_services_factory
    identity.Default.engine_services_factory = staticmethod(forbidden_composition)
    try:
        response = _fetch(
            identity,
            _identity_env(),
            _Request(MULTIMODAL_STREAM_PATH, body=_multimodal_payload(), authenticated=False),
        )
    finally:
        identity.Default.engine_services_factory = staticmethod(saved)

    assert response.status == 401
    assert _body(response)["error"]["code"] == "service_authentication_failed"


@pytest.mark.parametrize("b14_bound", [False, True])
def test_valid_ref_fails_closed_through_canonical_fetch(
    identity_modules, b14_bound: bool
) -> None:
    """A syntactically valid opaque ref still fails closed at the canonical fetch.

    The runtime factory is instrumented to count invocations: zero calls plus
    the bounded 503 prove no resolver, storage or Core/B14 execution fallback.
    """

    _legacy, identity = identity_modules
    env = _identity_env(**({"B14_SERVICE": object()} if b14_bound else {}))
    runtime_calls: list[str] = []

    real_factory = identity.Default.engine_services_factory

    def spying_factory(composition_env: Any) -> Any:
        async def _spying():
            services = await real_factory(composition_env)
            assert services.multimodal is not None
            assert services.multimodal._image_byte_store is None
            assert services.multimodal._scope_authority is None
            original = services.multimodal._runtime_factory

            def counting_runtime_factory(app_id: str) -> Any:
                runtime_calls.append(app_id)
                return original(app_id)

            services.multimodal._runtime_factory = counting_runtime_factory
            return services

        return _spying()

    identity.Default.engine_services_factory = staticmethod(spying_factory)
    try:
        response = _fetch(
            identity, env, _Request(MULTIMODAL_PATH, body=_multimodal_payload())
        )
    finally:
        identity.Default.engine_services_factory = staticmethod(real_factory)

    assert response.status == 503
    payload = _body(response)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "attachment_resolver_unavailable"
    assert runtime_calls == []
    serialized = str(response.body)
    assert VALID_REF not in serialized
    assert "data:" not in serialized


@pytest.mark.parametrize("b14_bound", [False, True])
def test_valid_ref_stream_fails_closed_through_canonical_fetch(
    identity_modules, b14_bound: bool
) -> None:
    """A valid opaque ref on the stream route still fails closed before execution.

    The streaming runtime factory is instrumented to count invocations: zero
    calls plus the bounded 503 prove no resolver, storage or Core/B14 streaming
    fallback is reachable through the canonical fetch.
    """

    _legacy, identity = identity_modules
    env = _identity_env(**({"B14_SERVICE": object()} if b14_bound else {}))
    runtime_calls: list[str] = []

    real_factory = identity.Default.engine_services_factory

    def spying_factory(composition_env: Any) -> Any:
        async def _spying():
            services = await real_factory(composition_env)
            assert services.multimodal_streaming is not None
            assert services.multimodal_streaming._image_byte_store is None
            assert services.multimodal_streaming._scope_authority is None
            original = services.multimodal_streaming._runtime_factory

            def counting_runtime_factory(app_id: str) -> Any:
                runtime_calls.append(app_id)
                return original(app_id)

            services.multimodal_streaming._runtime_factory = counting_runtime_factory
            return services

        return _spying()

    identity.Default.engine_services_factory = staticmethod(spying_factory)
    try:
        response = _fetch(
            identity, env, _Request(MULTIMODAL_STREAM_PATH, body=_multimodal_payload())
        )
    finally:
        identity.Default.engine_services_factory = staticmethod(real_factory)

    assert response.status == 503
    payload = _body(response)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "attachment_resolver_unavailable"
    assert runtime_calls == []
    serialized = str(response.body)
    assert VALID_REF not in serialized
    assert "data:" not in serialized
