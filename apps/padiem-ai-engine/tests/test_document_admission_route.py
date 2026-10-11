"""Canonical-entrypoint boundary proof for the composed Engine document admission (#2764).

Mirrors the E5C attachment-admission boundary conventions: the route shares the
existing body-read/service-auth boundary, the only document composition path
runs through the deployment-owned ENGINE_DOCUMENT_STORE lineage and the Control
Plane auth-session authority, and every boundary fails closed whenever either
authority is absent. No network, filesystem or provider access; the hostile D1
fake proves no byte write can be reached without a server-minted scope, while
the honest D1 fake proves admission and document context consume one store.
"""

from __future__ import annotations

import asyncio
import base64
import importlib
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from tests.test_document_byte_store import _FakeD1  # noqa: E402

CALLER_ID = "e8c-boundary-caller"
CALLER_SECRET = "e8c-boundary-secret-0123456789abcdef-0123456789abcdef"
ALLOWED_APP = "b62"
ADMISSION_PATH = "/internal/v1/documents"
SESSION_ID = "sess.local1-0123456789abcdef"
SUBJECT_ID = "user_local1_boundary"
TENANT_ID = "tenant_local1"


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


def _document_b64(text: str = "quarterly revenue projections for beta-corp") -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _admission_payload(**overrides) -> bytes:
    body = {
        "app_id": ALLOWED_APP,
        "session_id": SESSION_ID,
        "media_type": "text/plain",
        "document_base64": _document_b64(),
    }
    body.update(overrides)
    return json.dumps(body).encode("utf-8")


def _admission_payload_without_session() -> bytes:
    body = json.loads(_admission_payload())
    body.pop("session_id")
    return json.dumps(body).encode("utf-8")


class _HostileD1Statement:
    def bind(self, *_params: Any) -> "_HostileD1Statement":
        return self

    async def first(self) -> None:
        raise AssertionError("no D1 read may occur without a trusted scope")

    async def run(self) -> None:
        raise AssertionError("no D1 byte write may occur without a trusted scope")


class _HostileD1Binding:
    def prepare(self, _sql: str) -> _HostileD1Statement:
        return _HostileD1Statement()


class _FakeCpBinding:
    """D1-of-Control-Plane: an honest auth-session RPC fake with a valid view."""

    def __init__(self, *, mismatch_session: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.mismatch_session = mismatch_session

    async def resolve_auth_session(self, arg: dict) -> dict:
        self.calls.append(dict(arg))
        now = datetime.now(timezone.utc)
        session = {
            "session_id": "sess.other-session-00000000" if self.mismatch_session else SESSION_ID,
            "product_id": ALLOWED_APP,
            "subject": {"subject_type": "user", "subject_id": SUBJECT_ID},
            "issued_at": (now - timedelta(hours=1)).isoformat(),
            "expires_at": (now + timedelta(hours=1)).isoformat(),
            "state": "active",
            "revision": 2,
            "tenant_id": TENANT_ID,
        }
        return {"ok": True, "session": session}


def _trusted_env(**extra: Any) -> tuple[_Env, _FakeD1, _FakeCpBinding]:
    db = _FakeD1()
    cp = _FakeCpBinding()
    return _identity_env(ENGINE_DOCUMENT_STORE=db, CONTROL_PLANE_IDENTITY=cp, **extra), db, cp


# --- canonical composition ---------------------------------------------------


def test_canonical_composition_wires_document_services_without_authorities(
    identity_modules,
) -> None:
    from app.document_admission_service import DocumentAdmissionEngineService

    _legacy, identity = identity_modules

    for env in (_identity_env(), _identity_env(B14_SERVICE=object())):
        services = asyncio.run(identity._engine_services_for_env(env))
        assert isinstance(services.document_admission, DocumentAdmissionEngineService)
        assert services.document_admission._document_byte_store is None
        assert services.document_admission._scope_authority is None


def test_document_store_lineage_is_shared_and_resolvable(identity_modules) -> None:
    """Configured binding composes D1 store -> scoped store -> port -> resolver.

    The admission service and the document context resolver must receive the
    very same scoped store object; there is no second registry.
    """
    from app.document_byte_store import CloudflareD1DocumentByteStore, ScopedDocumentByteStore

    _legacy, identity = identity_modules
    env = _identity_env(ENGINE_DOCUMENT_STORE=_FakeD1())
    services = asyncio.run(identity._engine_services_for_env(env))

    store = services.document_admission._document_byte_store
    assert isinstance(store, ScopedDocumentByteStore)
    assert isinstance(store._port, CloudflareD1DocumentByteStore)
    resolver = services.documents._document_resolver
    assert resolver is not None
    assert resolver._storage._store is store


def test_malformed_document_store_binding_composes_no_lineage(identity_modules) -> None:
    _legacy, identity = identity_modules
    for malformed in (object(), "", 0, {"binding": "ENGINE_DOCUMENT_STORE"}, [], b"d1"):
        services = asyncio.run(
            identity._engine_services_for_env(_identity_env(ENGINE_DOCUMENT_STORE=malformed))
        )
        assert services.document_admission._document_byte_store is None, repr(malformed)
        assert services.documents._document_resolver is None, repr(malformed)


def test_legacy_worker_is_not_widened_by_e8c(identity_modules) -> None:
    legacy, _identity = identity_modules
    legacy_source = (APP_ROOT / "worker.py").read_text(encoding="utf-8")

    assert "document_admission" not in legacy_source
    assert "DocumentAdmissionEngineService" not in legacy_source

    services = asyncio.run(legacy._engine_services_for_env(_identity_env()))
    assert services.document_admission is None


# --- fail-closed boundaries ----------------------------------------------------


def test_admission_route_is_rejected_before_any_composition(identity_modules) -> None:
    _legacy, identity = identity_modules

    def forbidden_composition(env: Any) -> Any:
        async def _forbidden():
            raise AssertionError("admission composition reached before service identity")

        return _forbidden()

    saved = identity.Default.engine_services_factory
    identity.Default.engine_services_factory = staticmethod(forbidden_composition)
    try:
        response = _fetch(
            identity,
            _identity_env(),
            _Request(ADMISSION_PATH, body=_admission_payload(), authenticated=False),
        )
    finally:
        identity.Default.engine_services_factory = staticmethod(saved)

    assert response.status == 401
    assert _body(response)["error"]["code"] == "service_authentication_failed"


def test_valid_admission_shape_still_fails_closed_without_authorities(identity_modules) -> None:
    """No binding means no store and no scope authority; the route never fakes one."""

    _legacy, identity = identity_modules

    response = _fetch(
        identity, _identity_env(), _Request(ADMISSION_PATH, body=_admission_payload())
    )

    assert response.status == 503
    payload = _body(response)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "document_admission_unavailable"
    assert "doc_" not in str(response.body)
    assert "att_" not in str(response.body)


def test_bound_store_admission_never_reaches_d1_without_server_scope(identity_modules) -> None:
    """A bound ENGINE_DOCUMENT_STORE alone must not admit: scope minting fails first."""

    _legacy, identity = identity_modules
    env = _identity_env(ENGINE_DOCUMENT_STORE=_HostileD1Binding())

    response = _fetch(
        identity, env, _Request(ADMISSION_PATH, body=_admission_payload())
    )

    assert response.status == 503
    assert _body(response)["error"]["code"] == "document_admission_unavailable"


def test_cp_authority_gap_fails_closed_when_store_bound(identity_modules) -> None:
    """ENGINE_DOCUMENT_STORE present, CONTROL_PLANE_IDENTITY absent: no admit.

    The hostile statement fake asserts on any first()/run(), so the bounded
    503 also proves the scope-authority gap is reached before any D1 access.
    """

    _legacy, identity = identity_modules
    env = _identity_env(ENGINE_DOCUMENT_STORE=_HostileD1Binding())

    response = _fetch(
        identity, env, _Request(ADMISSION_PATH, body=_admission_payload())
    )
    assert response.status == 503
    assert _body(response)["error"]["code"] == "document_admission_unavailable"


def test_wire_validation_precedes_the_fail_closed_authority_gap(identity_modules) -> None:
    """Shape errors (caller-supplied identity fields, unknown fields) answer 400 first."""

    _legacy, identity = identity_modules
    env = _identity_env(ENGINE_DOCUMENT_STORE=_HostileD1Binding())

    for extra, label in (
        ({"tenant_id": "tenant.evil"}, "tenant"),
        ({"subject_id": "user.evil"}, "subject"),
        ({"workspace_id": "ws.evil"}, "workspace"),
        ({"trace_id": "trace.evil"}, "trace"),
        ({"expires_at": "2999-01-01T00:00:00Z"}, "expiry"),
        ({"locator": "opaque.locator"}, "locator"),
    ):
        widening = json.loads(_admission_payload())
        widening.update(extra)
        response = _fetch(
            identity, env, _Request(ADMISSION_PATH, body=json.dumps(widening).encode("utf-8"))
        )
        assert response.status == 400, label
        assert _body(response)["error"]["code"] == "invalid_request", label

    missing = _fetch(
        identity,
        env,
        _Request(ADMISSION_PATH, body=_admission_payload_without_session()),
    )
    assert missing.status == 400
    assert _body(missing)["error"]["code"] == "invalid_request"


def test_oversized_admission_body_is_bounded_on_the_wire(identity_modules) -> None:
    from app.document_admission_service import MAX_DOCUMENT_ADMISSION_REQUEST_BODY_BYTES

    _legacy, identity = identity_modules
    env = _identity_env(ENGINE_DOCUMENT_STORE=_HostileD1Binding())
    huge = b'{"app_id": "' + ALLOWED_APP.encode() + b'", "filler": "'
    huge += b"x" * (MAX_DOCUMENT_ADMISSION_REQUEST_BODY_BYTES + 1)
    huge += b'"}'

    response = _fetch(identity, env, _Request(ADMISSION_PATH, body=huge))

    assert response.status == 413
    assert _body(response)["error"]["code"] == "request_too_large"


def test_admission_route_method_and_content_type_match_existing_boundaries(
    identity_modules,
) -> None:
    _legacy, identity = identity_modules

    get = _fetch(identity, _identity_env(), _Request(ADMISSION_PATH, method="GET"))
    assert get.status == 401
    assert _body(get)["error"]["code"] == "service_authentication_failed"

    text = _fetch(
        identity,
        _identity_env(),
        _Request(ADMISSION_PATH, body=_admission_payload()),
    )
    assert text.status == 503  # authenticated JSON POST reaches the fail-closed seam


# --- honest E2E over the composed lineage --------------------------------------


def test_admission_admits_once_and_context_resolves_through_same_lineage(
    identity_modules,
) -> None:
    _legacy, identity = identity_modules
    env, db, cp = _trusted_env()

    response = _fetch(
        identity, env, _Request(ADMISSION_PATH, body=_admission_payload())
    )

    assert response.status == 200
    payload = _body(response)
    assert payload["ok"] is True
    doc = payload["document"]
    assert set(doc) == {"document_ref", "media_type", "byte_size", "expires_at"}
    assert doc["document_ref"].startswith("doc_")
    assert doc["media_type"] == "text/plain"
    assert doc["byte_size"] == len("quarterly revenue projections for beta-corp")
    # the auth-session RPC received only the opaque session id
    assert cp.calls == [{"session_id": SESSION_ID}]
    # raw bytes and storage internals never project
    assert _document_b64() not in str(response.body)
    assert "payload_base64" not in str(response.body)

    # document context's composed resolver reads the very same D1 rows
    services = asyncio.run(identity._engine_services_for_env(env))
    resolver = services.documents._document_resolver
    assert resolver is not None
    assert resolver._storage._store is services.document_admission._document_byte_store

    async def read_back() -> None:
        raw, meta = await resolver.resolve(
            doc["document_ref"],
            app_id=ALLOWED_APP,
            subject_id=SUBJECT_ID,
            tenant_id=TENANT_ID,
        )
        assert raw == "quarterly revenue projections for beta-corp".encode("utf-8")
        assert meta.name == "document.txt"
        assert meta.media_type == "text/plain"

    asyncio.run(read_back())


def test_context_scope_mismatch_never_admits_second_ref(identity_modules) -> None:
    """A session whose id does not match is refused with the bounded code."""

    _legacy, identity = identity_modules
    db = _FakeD1()
    cp = _FakeCpBinding(mismatch_session=True)
    env = _identity_env(ENGINE_DOCUMENT_STORE=db, CONTROL_PLANE_IDENTITY=cp)

    response = _fetch(
        identity, env, _Request(ADMISSION_PATH, body=_admission_payload())
    )
    assert response.status == 403
    assert _body(response)["error"]["code"] == "auth_scope_mismatch"
    assert db.rows == {}


def test_att_reference_never_resolves_on_the_document_lane(identity_modules) -> None:
    from app.trusted_document_resolver import DocumentResolutionError

    _legacy, identity = identity_modules
    env, _db, _cp = _trusted_env()
    services = asyncio.run(identity._engine_services_for_env(env))
    resolver = services.documents._document_resolver

    async def scenario() -> None:
        with pytest.raises(DocumentResolutionError) as info:
            await resolver.resolve(
                "att_e8cboundary0000000",
                app_id=ALLOWED_APP,
                subject_id=SUBJECT_ID,
                tenant_id=TENANT_ID,
            )
        assert info.value.code == "invalid_reference"

    asyncio.run(scenario())


# --- wiring hygiene -------------------------------------------------------------


def test_admission_wiring_stays_internal_only() -> None:
    identity_source = (APP_ROOT / "worker_identity.py").read_text(encoding="utf-8")
    assert "DOCUMENT_ADMISSION_PATH" in identity_source
    assert "_fetch_document_admission" in identity_source
    assert "InMemoryDocumentByteStore" not in identity_source
    assert "Access-Control-Allow-Origin" not in identity_source
    assert "workers.dev" not in identity_source
