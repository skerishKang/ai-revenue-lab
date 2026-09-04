"""Runtime-level canonical composition-root proof for #1792 R2A.

Exercises the real ``worker_identity.Default`` fetch entrypoint (with the
Cloudflare ``workers`` runtime surface stubbed) and proves that every Engine
route family is composed by name through one explicit ``EngineServices``
bundle: no positional-tuple contract and no module-global monkey-patch.
"""

from __future__ import annotations

import asyncio
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

CALLER_ID = "r2a-test-caller"
CALLER_SECRET = "r2a-test-secret-0123456789abcdef-0123456789abcdef"  # >=32 bytes per service_identity contract
ALLOWED_APP = "b62"


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
        name: sys.modules.get(name)
        for name in ("workers", "worker", "worker_identity")
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


def _entry(identity: Any, env: Any) -> Any:
    return identity.Default(ctx=None, env=env)


def _fetch(identity: Any, env: Any, request: Any) -> Any:
    return asyncio.run(_entry(identity, env).fetch(request))


def _body(response: Any) -> dict:
    return json.loads(str(response.body))


def test_canonical_entrypoint_overrides_named_bundle_factory_without_monkey_patch(
    identity_modules,
) -> None:
    legacy, identity = identity_modules

    assert issubclass(identity.Default, legacy.Default)
    assert legacy.Default.engine_services_factory is legacy._engine_services_for_env
    assert identity.Default.engine_services_factory is identity._engine_services_for_env
    assert legacy._engine_services_for_env is not identity._engine_services_for_env

    source = (APP_ROOT / "worker_identity.py").read_text(encoding="utf-8")
    assert "legacy_worker._engine_services_for_env =" not in source
    assert "legacy_worker.Default =" not in source


def test_both_entrypoints_compose_full_named_bundle_never_tuples(identity_modules) -> None:
    legacy, identity = identity_modules
    from app.engine_composition import EngineServices
    from app.orchestration_idempotency_service import (
        CanonicalIdempotencyOrchestrationEngineService,
    )
    from app.memory_service import MemoryRetrievalEngineService
    from app.service import EngineService
    from app.streaming_service import StreamingEngineService
    from app.web_research_service import WebResearchEngineService

    unbound_env = _identity_env()

    for factory in (legacy._engine_services_for_env, identity._engine_services_for_env):
        services = factory(unbound_env)
        assert isinstance(services, EngineServices)
        assert not isinstance(services, tuple)
        assert isinstance(services.completed, EngineService)
        assert isinstance(services.streaming, StreamingEngineService)
        assert isinstance(services.research, WebResearchEngineService)
        assert isinstance(services.memory, MemoryRetrievalEngineService)
        assert services.memory.bound_app_ids == ()
        assert services.memory.write_bound_app_ids == ()

    legacy_services = legacy._engine_services_for_env(unbound_env)
    identity_services = identity._engine_services_for_env(unbound_env)
    from app.orchestration_service import OrchestrationEngineService

    assert isinstance(legacy_services.orchestration, OrchestrationEngineService)
    assert not isinstance(
        legacy_services.orchestration, CanonicalIdempotencyOrchestrationEngineService
    )
    assert isinstance(
        identity_services.orchestration, CanonicalIdempotencyOrchestrationEngineService
    )

    bound_services = identity._engine_services_for_env(_identity_env(B14_SERVICE=object()))
    assert isinstance(
        bound_services.orchestration, CanonicalIdempotencyOrchestrationEngineService
    )
    assert isinstance(bound_services.research, WebResearchEngineService)
    assert bound_services.completed._b14_service_bound is True


def test_health_route_serves_without_caller_credential(identity_modules) -> None:
    from app.service import HEALTH_PATH

    _legacy, identity = identity_modules
    response = _fetch(identity, _Env(), _Request(HEALTH_PATH, method="GET"))

    assert response.status == 200
    body = _body(response)
    assert body["status"] == "ok"
    assert body["service_identity"] == "required_for_all_non_health_routes"


@pytest.mark.parametrize(
    ("path", "error_code"),
    [
        ("/internal/v1/execute", "b14_service_unavailable"),
        ("/internal/v1/research", "b14_service_unavailable"),
        ("/internal/v1/orchestrate", "b14_service_unavailable"),
        ("/internal/v1/memory/retrieve", "memory_binding_unavailable"),
        ("/internal/v1/memory/write", "memory_write_binding_unavailable"),
    ],
)
def test_authenticated_routes_reach_named_services_without_arity_failure(
    identity_modules, path, error_code
) -> None:
    _legacy, identity = identity_modules
    env = _identity_env()
    body = json.dumps({"app_id": ALLOWED_APP}).encode("utf-8")

    response = _fetch(identity, env, _Request(path, body=body))

    assert response.status == 503
    payload = _body(response)
    assert payload["ok"] is False
    assert payload["error"]["code"] == error_code


def test_unauthenticated_non_health_route_still_fails_closed(identity_modules) -> None:
    _legacy, identity = identity_modules
    body = json.dumps({"app_id": ALLOWED_APP}).encode("utf-8")

    response = _fetch(
        identity,
        _identity_env(),
        _Request("/internal/v1/execute", body=body, authenticated=False),
    )

    assert response.status == 401
    assert _body(response)["error"]["code"] == "service_authentication_failed"


def test_unauthorized_app_for_authenticated_caller_fails_closed(identity_modules) -> None:
    _legacy, identity = identity_modules
    body = json.dumps({"app_id": "not-authorized-app"}).encode("utf-8")

    response = _fetch(identity, _identity_env(), _Request("/internal/v1/execute", body=body))

    assert response.status == 403
    assert _body(response)["error"]["code"] == "service_app_not_authorized"


def test_memory_route_serves_from_bound_service_in_canonical_entrypoint(identity_modules) -> None:
    from dataclasses import replace

    from padiem_ai_core.memory import MemoryNamespace, MemoryScope
    from padiem_ai_core.memory_read import MemoryReadAuthorization
    from padiem_ai_core.retrieval import RetrievedItem

    from app.memory_service import EngineMemoryBinding, MemoryRetrievalEngineService

    _legacy, identity = identity_modules

    class _Provider:
        async def retrieve(self, request: Any) -> Any:
            return (
                RetrievedItem(
                    id="m-1",
                    namespace=request.namespaces[0],
                    source_type="user_note",
                    provider="fixture-store",
                    source_ref="private-ref-1",
                    content="stored preference",
                ),
            )

    namespace = MemoryNamespace(app_id=ALLOWED_APP, scope=MemoryScope.USER, subject_id="u-1")
    memory = MemoryRetrievalEngineService(
        bindings={
            ALLOWED_APP: EngineMemoryBinding(
                authorization=MemoryReadAuthorization(
                    app_id=ALLOWED_APP, readable_namespaces=(namespace,)
                ),
                provider=_Provider(),
            )
        }
    )
    env = _identity_env()
    base = identity._engine_services_for_env(env)
    entry = _entry(identity, env)
    entry.engine_services_factory = lambda _env: replace(base, memory=memory)

    body = json.dumps(
        {
            "app_id": ALLOWED_APP,
            "query": "what does the user prefer?",
            "namespaces": [{"scope": "user", "subject_id": "u-1"}],
        }
    ).encode("utf-8")
    response = asyncio.run(entry.fetch(_Request("/internal/v1/memory/retrieve", body=body)))

    assert response.status == 200
    payload = _body(response)
    assert payload["ok"] is True
    assert payload["trust"] == "untrusted_reference"
    assert payload["retrieval"]["item_count"] == 1
    assert "private-ref-1" not in json.dumps(payload)
    assert "stored preference" not in json.dumps(payload)


def test_memory_write_route_serves_from_bound_write_service_in_canonical_entrypoint(
    identity_modules,
) -> None:
    from dataclasses import replace

    from padiem_ai_core.memory import (
        MemoryNamespace,
        MemoryProvenance,
        MemoryScope,
        MemoryWriteAuthorization,
        MemoryWriteOrigin,
    )
    from padiem_ai_core.memory_receipt import (
        MemoryWriteDisposition,
        MemoryWriteReceipt,
    )

    from app.memory_service import (
        EngineMemoryWriteBinding,
        MemoryRetrievalEngineService,
        MemoryWriteClassification,
    )

    _legacy, identity = identity_modules

    calls: list[Any] = []

    class _WriteAdapter:
        async def write(self, prepared: Any) -> Any:
            calls.append(prepared)
            request = prepared.request
            return MemoryWriteReceipt(
                memory_id=request.memory_id,
                namespace_key=request.namespace.key,
                idempotency_scope=request.idempotency_scope,
                disposition=MemoryWriteDisposition.CREATED,
                adapter_id="fixture-store",
                storage_ref="private-storage-1",
            )

    def classifier(candidate: Any) -> MemoryWriteClassification:
        return MemoryWriteClassification(
            origin=MemoryWriteOrigin.USER_EXPLICIT,
            provenance=MemoryProvenance(
                source_type="attested_action",
                source_ref="private-server-ref-1",
                trace_id=candidate.trace_id,
            ),
        )

    namespace = MemoryNamespace(app_id=ALLOWED_APP, scope=MemoryScope.USER, subject_id="u-1")
    memory = MemoryRetrievalEngineService(
        write_bindings={
            ALLOWED_APP: EngineMemoryWriteBinding(
                authorization=MemoryWriteAuthorization(
                    app_id=ALLOWED_APP, writable_namespaces=(namespace.key,)
                ),
                adapter=_WriteAdapter(),
                classifier=classifier,
            )
        }
    )
    assert memory.write_bound_app_ids == (ALLOWED_APP,)

    env = _identity_env()
    base = identity._engine_services_for_env(env)
    entry = _entry(identity, env)
    entry.engine_services_factory = lambda _env: replace(base, memory=memory)

    body = json.dumps(
        {
            "app_id": ALLOWED_APP,
            "memory_id": "m-w-1",
            "namespace": {"scope": "user", "subject_id": "u-1"},
            "content": "remember project baseline",
            "idempotency_key": "idem-1",
            "trace_id": "trace-1",
        }
    ).encode("utf-8")
    response = asyncio.run(entry.fetch(_Request("/internal/v1/memory/write", body=body)))

    assert response.status == 200
    payload = _body(response)
    assert payload["ok"] is True
    assert payload["receipt"]["memory_id"] == "m-w-1"
    assert payload["receipt"]["disposition"] == "created"
    assert payload["receipt"]["adapter_id"] == "fixture-store"
    assert len(calls) == 1
    assert "private-storage-1" not in json.dumps(payload)
    assert "private-server-ref-1" not in json.dumps(payload)
    assert "remember project baseline" not in json.dumps(payload)
