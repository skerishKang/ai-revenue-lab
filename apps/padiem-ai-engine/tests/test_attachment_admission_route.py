"""Canonical-entrypoint boundary proof for Engine E5C admission (#2727).

Mirrors the E5A boundary conventions: the new route shares the existing
body-read/service-auth boundary, composes only through the deployment-owned
authorities and fails closed whenever either authority is absent. No network,
filesystem or provider access; the fake D1 statement proves no byte-write can
be reached without a server-minted scope.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

CALLER_ID = "e5c-boundary-caller"
CALLER_SECRET = "e5c-boundary-secret-0123456789abcdef-0123456789abcdef"
ALLOWED_APP = "b62"
ADMISSION_PATH = "/internal/v1/multimodal/attachments"


class _FakeResponse:
    def __init__(self, body: Any = None, status: int = 200, headers: Any = None) -> None:
        self.body = body
        self.status = status
        self.headers = headers or {}


class _FakeWorkerEntrypoint:
    def __init__(self, ctx: Any = None, env: Any = None) -> None:
        self.ctx = ctx
        self.env = env


import types  # noqa: E402


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


def _admission_payload(**overrides) -> bytes:
    body = {
        "app_id": ALLOWED_APP,
        "session_id": "sess.0123456789abcdef",
        "media_type": "image/png",
        "image_base64": "iVBORw0KGgo=",
    }
    body.update(overrides)
    return json.dumps(body).encode("utf-8")


def _admission_payload_without_session() -> bytes:
    body = json.loads(_admission_payload())
    body.pop("session_id")
    return json.dumps(body).encode("utf-8")


class _FakeD1Statement:
    """D1-shaped statement that must never be exercised without trusted scope."""

    def bind(self, *_params: Any) -> "_FakeD1Statement":
        return self

    async def first(self) -> None:
        raise AssertionError("no D1 read may occur without a trusted scope")

    async def run(self) -> None:
        raise AssertionError("no D1 byte write may occur without a trusted scope")


class _FakeD1Binding:
    def prepare(self, _sql: str) -> _FakeD1Statement:
        return _FakeD1Statement()


def test_canonical_composition_wires_admission_service_without_authorities(
    identity_modules,
) -> None:
    from app.attachment_admission_service import AttachmentAdmissionEngineService

    _legacy, identity = identity_modules

    for env in (_identity_env(), _identity_env(B14_SERVICE=object())):
        services = asyncio.run(identity._engine_services_for_env(env))
        assert isinstance(services.attachment_admission, AttachmentAdmissionEngineService)
        assert services.attachment_admission._image_byte_store is None
        assert services.attachment_admission._scope_authority is None


def test_admission_service_shares_the_multimodal_authority_objects(identity_modules) -> None:
    from app.attachment_byte_store import CloudflareD1ImageByteStore, ScopedImageByteStore

    _legacy, identity = identity_modules
    env = _identity_env(ENGINE_IMAGE_STORE=_FakeD1Binding())
    services = asyncio.run(identity._engine_services_for_env(env))

    store = services.attachment_admission._image_byte_store
    assert isinstance(store, ScopedImageByteStore)
    assert isinstance(store._port, CloudflareD1ImageByteStore)
    assert store is services.multimodal._image_byte_store
    assert store is services.multimodal_streaming._image_byte_store
    assert services.attachment_admission._scope_authority is None
    assert services.attachment_admission._scope_authority is services.multimodal._scope_authority


def test_malformed_image_store_binding_composes_no_admission_store(identity_modules) -> None:
    _legacy, identity = identity_modules
    for malformed in (object(), "", 0, {"binding": "ENGINE_IMAGE_STORE"}, [], b"d1"):
        services = asyncio.run(
            identity._engine_services_for_env(_identity_env(ENGINE_IMAGE_STORE=malformed))
        )
        assert services.attachment_admission._image_byte_store is None, repr(malformed)


def test_legacy_worker_is_not_widened_by_e5c(identity_modules) -> None:
    legacy, _identity = identity_modules
    legacy_source = (APP_ROOT / "worker.py").read_text(encoding="utf-8")

    assert "attachment_admission" not in legacy_source
    assert "AttachmentAdmissionEngineService" not in legacy_source

    services = asyncio.run(legacy._engine_services_for_env(_identity_env()))
    assert services.attachment_admission is None


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
    """No binding means no store and no scope authority; the route never fakes one.

    The byte payload must not be written anywhere: with no D1 binding there is
    no storage to begin with, and the bounded 503 proves no local-buffer
    fallback and no attachment reference in the response.
    """

    _legacy, identity = identity_modules

    response = _fetch(identity, _identity_env(), _Request(ADMISSION_PATH, body=_admission_payload()))

    assert response.status == 503
    payload = _body(response)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "attachment_admission_unavailable"
    assert "att_" not in str(response.body)


def test_bound_store_admission_never_reaches_d1_without_server_scope(identity_modules) -> None:
    """A bound ENGINE_IMAGE_STORE alone must not admit: scope minting fails first.

    The fake D1 statement raises on any first()/run(), so a returned bounded
    503 also proves zero byte writes happened without a trusted scope.
    """

    _legacy, identity = identity_modules
    env = _identity_env(ENGINE_IMAGE_STORE=_FakeD1Binding())

    response = _fetch(identity, env, _Request(ADMISSION_PATH, body=_admission_payload()))

    assert response.status == 503
    assert _body(response)["error"]["code"] == "attachment_admission_unavailable"


def test_wire_validation_precedes_the_fail_closed_authority_gap(identity_modules) -> None:
    """Shape errors (client-asserted tenant, unknown fields) answer 400 first.

    This keeps admission semantics identical with and without deployment
    authority: the wire never hints which authority is missing for a
    syntactically invalid request.
    """

    _legacy, identity = identity_modules
    env = _identity_env(ENGINE_IMAGE_STORE=_FakeD1Binding())

    unknown = _fetch(
        identity,
        env,
        _Request(ADMISSION_PATH, body=_admission_payload(tenant_id="tenant.evil")),
    )
    assert unknown.status == 400
    assert _body(unknown)["error"]["code"] == "invalid_request"

    missing = _fetch(
        identity,
        env,
        _Request(ADMISSION_PATH, body=_admission_payload_without_session()),
    )
    assert missing.status == 400
    assert _body(missing)["error"]["code"] == "invalid_request"


def test_oversized_admission_body_is_bounded_on_the_wire(identity_modules) -> None:
    from app.attachment_admission_service import MAX_ADMISSION_REQUEST_BODY_BYTES

    _legacy, identity = identity_modules
    env = _identity_env(ENGINE_IMAGE_STORE=_FakeD1Binding())
    huge = b'{"app_id": "' + ALLOWED_APP.encode() + b'", "filler": "'
    huge += b"x" * (MAX_ADMISSION_REQUEST_BODY_BYTES + 1)
    huge += b'"}'

    response = _fetch(identity, env, _Request(ADMISSION_PATH, body=huge))

    assert response.status == 413
    assert _body(response)["error"]["code"] == "request_too_large"


def test_admission_route_method_and_content_type_match_existing_boundaries(
    identity_modules,
) -> None:
    """Non-POST requests die at the shared auth gate, before route semantics.

    The body-boundary method/content-type grammar itself is the fail-closed
    admission service's job (proven per-shape in test_attachment_admission_service).
    """

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


def test_admission_wiring_stays_internal_only() -> None:
    identity_source = (APP_ROOT / "worker_identity.py").read_text(encoding="utf-8")
    assert "ATTACHMENT_ADMISSION_PATH" in identity_source
    assert "_fetch_attachment_admission" in identity_source
    assert "Access-Control-Allow-Origin" not in identity_source
    assert "workers.dev" not in identity_source
