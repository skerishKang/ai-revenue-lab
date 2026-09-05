"""Trusted document context route acceptance matrix for #1750 E5B-S4.

Proves the S4 through-line mount: the fail-closed composition seam (B), the
anonymous/mismatch identity gate ahead of every trusted port (C), the
reference-only wire grammar (D), the S3 bounded preview contract (E), the
zero-leak response surface (F) and the untouched S2/S3 canaries (G), plus the
canonical composition-root boundary mirroring E5A (fetch-level tests). Matrix
H (manifest truth) is not required: S4 leaves the contract manifest untouched
and the capability stays DEFERRED until a Production authority is injected.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import sys
import types
from typing import Any

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.document_context_service import (  # noqa: E402
    DOCUMENT_CONTEXT_PATH,
    DocumentAuthorityError,
    DocumentContextEngineService,
    TrustedCallerScope,
)
from app.document_evidence_projection import (  # noqa: E402
    EvidenceStorageProjection,
    InMemoryEvidenceStoragePort,
)
from app.engine_composition import EngineServices  # noqa: E402
from app.trusted_document_resolver import (  # noqa: E402
    InMemoryStoragePort,
    ResolvedDocumentMeta,
    TrustedDocumentResolver,
)

CALLER_ID = "e5b-route-caller"
CALLER_SECRET = "e5b-route-secret-0123456789abcdef-0123456789abcdef"
DOC_REF = "att_e5bRoutefixture01"
DOC_LOCATOR = "opaque-document-locator-e5b"
BODY_SHORT = "quarterly revenue projections for beta-corp"
SECRET_TAIL = "TAILNEVERMOUNTEDINCONTEXT-88091"
SCOPE = {"app_id": "app.revenue", "subject_id": "user.42", "tenant_id": "tenant.a"}

MULTIMODAL_PATH = "/internal/v1/multimodal/execute"


def _document_text() -> str:
    filler = "revenue projection line with realistic narrative content pad "
    joined = "\n".join(filler + f"L{index:03d}" for index in range(120))
    return joined + "\n" + SECRET_TAIL


def _meta(**overrides: object) -> ResolvedDocumentMeta:
    values: dict[str, object] = {"media_type": "text/plain", "name": "notes.txt"}
    values.update(SCOPE)
    values.update(overrides)
    return ResolvedDocumentMeta(**values)  # type: ignore[arg-type]


class _RecordingResolver(TrustedDocumentResolver):
    def __init__(self, text: str) -> None:
        storage = InMemoryStoragePort()
        payload = text.encode("utf-8")
        storage.store(DOC_LOCATOR, payload, _meta(byte_size=len(payload)))
        super().__init__(storage=storage)
        self.register(DOC_REF, DOC_LOCATOR)
        self.calls: list[Any] = []

    def resolve(self, att_ref: object, **scope: str):
        self.calls.append((att_ref, scope))
        return super().resolve(att_ref, **scope)


class _RecordingEvidencePort(InMemoryEvidenceStoragePort):
    def __init__(self) -> None:
        super().__init__()
        self.stored: list[str] = []

    def store(self, projection: EvidenceStorageProjection) -> str:
        self.stored.append(projection.evidence_id)
        return super().store(projection)


class _FakeScopeAuthority:
    """Stands in for the deployment-owned authority; never fed by wire data."""

    def __init__(
        self,
        scope: TrustedCallerScope | None = None,
        *,
        reject: DocumentAuthorityError | None = None,
    ) -> None:
        self._scope = scope if scope is not None else TrustedCallerScope(**SCOPE)
        self._reject = reject
        self.calls: list[tuple[str, str]] = []

    def scope_for_caller(
        self, *, caller_id: str, credential: str
    ) -> TrustedCallerScope:
        self.calls.append((caller_id, credential))
        if self._reject is not None:
            raise self._reject
        if caller_id != CALLER_ID or credential != CALLER_SECRET:
            raise DocumentAuthorityError(
                "caller_not_bound_to_session",
                "Caller is not bound to a trusted document session.",
                status_code=401,
            )
        return self._scope


def _service(
    *,
    text: str | None = None,
    authority: _FakeScopeAuthority | None = None,
    omit: str | None = None,
):
    resolver = _RecordingResolver(BODY_SHORT if text is None else text)
    port = _RecordingEvidencePort()
    scope_authority = _FakeScopeAuthority() if authority is None else authority
    service = DocumentContextEngineService(
        scope_authority=None if omit == "authority" else scope_authority,
        document_resolver=None if omit == "resolver" else resolver,
        evidence_storage=None if omit == "storage" else port,
    )
    return service, resolver, port, scope_authority


def _request_body(**fields: object) -> bytes:
    payload: dict[str, object] = {"document_ref": DOC_REF}
    payload.update(fields)
    return json.dumps(payload).encode("utf-8")


def _handle(
    service: DocumentContextEngineService,
    body: bytes,
    *,
    caller: str = CALLER_ID,
    credential: str = CALLER_SECRET,
    method: str = "POST",
    ctype: str | None = "application/json",
    path: str = DOCUMENT_CONTEXT_PATH,
) -> Any:
    return asyncio.run(
        service.handle(
            method=method,
            path=path,
            content_type=ctype,
            body=body,
            caller_id=caller,
            credential=credential,
        )
    )


# --- A: positive through-line -------------------------------------------------


def test_a_trusted_scope_and_valid_reference_return_bounded_projection() -> None:
    service, resolver, port, authority = _service()

    response = _handle(service, _request_body())

    assert response.status_code == 200
    body = response.body
    assert body["ok"] is True
    assert body["document"] == {
        "kind": "text",
        "name": "notes.txt",
        "media_type": "text/plain",
        "byte_size": len(BODY_SHORT.encode("utf-8")),
        "text_chars": len(BODY_SHORT),
        "segment_count": 1,
        "status": "complete",
        "content_trust_class": "untrusted_reference_data",
        "truncated_text_preview": BODY_SHORT,
    }
    evidence_id = body["evidence"]["evidence_id"]
    assert 16 <= len(evidence_id) <= 64
    retained = port.retrieve(evidence_id)
    assert retained.normalized_document.text == BODY_SHORT
    assert retained.att_ref == DOC_REF
    assert retained.storage_locator == f"evidence://{DOC_REF}"
    assert port.stored == [evidence_id]
    assert authority.calls == [(CALLER_ID, CALLER_SECRET)]
    assert [call[1] for call in resolver.calls] == [SCOPE, SCOPE]
    assert "document_ref" not in json.dumps(body)


# --- B: fail-closed seams -----------------------------------------------------


@pytest.mark.parametrize("omit", ["authority", "resolver", "storage"])
def test_b_each_missing_trusted_port_fails_closed_without_calls(omit: str) -> None:
    service, resolver, port, _ = _service(omit=omit)

    response = _handle(service, _request_body())

    assert response.status_code == 503
    assert response.body["error"]["code"] == {
        "authority": "document_authority_unavailable",
        "resolver": "document_resolver_unavailable",
        "storage": "evidence_storage_unavailable",
    }[omit]
    assert response.body["error"]["retryable"] is False
    assert resolver.calls == []
    assert port.stored == []


def test_b_canonical_composition_leaves_documents_seam_uninjected(
    identity_modules,
) -> None:
    _legacy, identity = identity_modules

    for env in (_identity_env(), _identity_env(B14_SERVICE=object())):
        services = identity._engine_services_for_env(env)
        assert isinstance(services, EngineServices)
        assert services.documents is None
        with pytest.raises(ValueError, match="'documents'"):
            dataclasses.replace(services, documents=object())
        injected = DocumentContextEngineService()
        assert dataclasses.replace(services, documents=injected).documents is injected


# --- C: identity before any trusted port --------------------------------------


@pytest.mark.parametrize(
    ("caller", "credential"),
    [("", CALLER_SECRET), (CALLER_ID, ""), ("   ", CALLER_SECRET)],
)
def test_c_anonymous_caller_is_rejected_before_any_port(
    caller: str, credential: str
) -> None:
    service, resolver, port, _ = _service()

    response = _handle(
        service, _request_body(), caller=caller, credential=credential
    )

    assert response.status_code == 401
    assert response.body["error"]["code"] == "service_authentication_failed"
    assert resolver.calls == []
    assert port.stored == []


def test_c_mismatched_caller_rejected_by_authority_without_port_touch() -> None:
    service, resolver, port, authority = _service()

    response = _handle(
        service,
        _request_body(),
        caller="attacker-caller",
        credential=CALLER_SECRET,
    )

    assert response.status_code == 401
    assert response.body["error"]["code"] == "caller_not_bound_to_session"
    assert authority.calls == [("attacker-caller", CALLER_SECRET)]
    assert resolver.calls == []
    assert port.stored == []


def test_c_authority_failure_never_reflects_session_internals() -> None:
    authority = _FakeScopeAuthority(
        reject=Exception("session table connection leaked internal id 991")
    )
    service, resolver, port, _ = _service(authority=authority)

    response = _handle(service, _request_body())

    assert response.status_code == 503
    assert response.body["error"]["code"] == "document_authority_unavailable"
    assert "991" not in json.dumps(response.body)
    assert resolver.calls == []
    assert port.stored == []


# --- D: reference-only wire grammar -------------------------------------------


@pytest.mark.parametrize(
    "bad_ref",
    [
        "att_short",
        f"att_{'x' * 200}",
        "../att_traversal",
        "file:///E/secrets/notes.txt",
        f"http://storage.internal/bucket/{'att_pad' * 10}",
        "evidence://att_e5bRoutefixture01",
        DOC_REF.upper(),
        "",
    ],
)
def test_d_invalid_references_are_rejected(bad_ref: object) -> None:
    service, resolver, port, _ = _service()

    response = _handle(service, _request_body(document_ref=bad_ref))

    assert response.status_code == 400
    assert response.body["error"]["code"] == "invalid_reference"
    assert port.stored == []
    if isinstance(bad_ref, str) and bad_ref:
        assert bad_ref not in json.dumps(response.body)


@pytest.mark.parametrize("scope_field", ["app_id", "subject_id", "tenant_id"])
def test_d_scope_fields_are_never_request_inputs(scope_field: str) -> None:
    service, resolver, port, _ = _service()

    response = _handle(service, _request_body(**{scope_field: "app.selfasserted"}))

    assert response.status_code == 400
    assert response.body["error"]["code"] == "invalid_request"
    assert "selfasserted" not in json.dumps(response.body)
    assert resolver.calls == []
    assert port.stored == []


def test_d_missing_reference_field_is_invalid_request() -> None:
    service, resolver, port, _ = _service()

    response = _handle(service, json.dumps({}).encode("utf-8"))

    assert response.status_code == 400
    assert response.body["error"]["code"] == "invalid_request"
    assert resolver.calls == []
    assert port.stored == []


def test_d_cross_scope_triple_is_unauthorized_and_never_retained() -> None:
    foreign = TrustedCallerScope(
        app_id=SCOPE["app_id"], subject_id="user.99", tenant_id=SCOPE["tenant_id"]
    )
    service, resolver, port, _ = _service(authority=_FakeScopeAuthority(foreign))

    response = _handle(service, _request_body())

    assert response.status_code == 403
    assert response.body["error"]["code"] == "unauthorized"
    assert port.stored == []
    assert "user.99" not in json.dumps(response.body)
    assert "user.42" not in json.dumps(response.body)


def test_d_unknown_but_well_formed_reference_is_not_found() -> None:
    service, resolver, port, _ = _service()

    response = _handle(service, _request_body(document_ref="att_neverminted0001"))

    assert response.status_code == 404
    assert response.body["error"]["code"] == "not_found"
    assert port.stored == []


# --- E: bounded preview with honest metadata ----------------------------------


def test_e_oversized_document_truncates_preview_and_reports_honest_bounds() -> None:
    text = _document_text()
    service, _resolver, port, _ = _service(text=text)

    response = _handle(service, _request_body())

    assert response.status_code == 200
    document = response.body["document"]
    assert document["text_chars"] == len(text)
    assert document["byte_size"] == len(text.encode("utf-8"))
    assert document["segment_count"] == 1
    preview = document["truncated_text_preview"]
    dropped = len(text) - 4000
    marker = f"... [truncated {dropped} chars]"
    assert preview.startswith(text[:4000])
    assert preview.endswith(marker)
    assert len(preview) == 4000 + len(marker)
    assert SECRET_TAIL not in preview
    retained = port.retrieve(response.body["evidence"]["evidence_id"])
    assert retained.normalized_document.text == text
    assert SECRET_TAIL in retained.normalized_document.text


# --- F: zero-leak response surface --------------------------------------------


def test_f_serialized_response_leaks_no_reference_locator_body_or_scope() -> None:
    text = _document_text()
    service, _resolver, _port, _ = _service(text=text)

    serialized = json.dumps(_handle(service, _request_body()).body).lower()

    assert "att_" not in serialized
    assert "locator" not in serialized
    assert "evidence://" not in serialized
    assert DOC_REF.lower() not in serialized
    assert DOC_LOCATOR.lower() not in serialized
    assert SECRET_TAIL.lower() not in serialized
    assert "app.revenue" not in serialized
    assert "user.42" not in serialized
    assert "tenant.a" not in serialized


def test_f_error_responses_are_safe_constants_only() -> None:
    foreign = TrustedCallerScope(
        app_id=SCOPE["app_id"], subject_id="user.77", tenant_id="tenant.z"
    )
    service, _resolver, _port, _ = _service(authority=_FakeScopeAuthority(foreign))

    response = _handle(service, json.dumps("scalar").encode("utf-8"))
    assert response.status_code == 400
    assert response.body["error"]["code"] == "invalid_request"

    response = _handle(service, _request_body(), ctype="text/plain")
    assert response.status_code == 415

    response = _handle(service, _request_body(), method="GET", ctype=None)
    assert response.status_code == 405

    response = _handle(service, _request_body(), path="/internal/v1/elsewhere")
    assert response.status_code == 404


# --- G: frozen canaries still hold ---------------------------------------------


@pytest.mark.parametrize(
    "module_name",
    [
        "test_trusted_document_resolver",
        "test_context_evidence_projection",
    ],
)
def test_g_frozen_canary_pins_still_hold(module_name: str) -> None:
    path = APP_ROOT / "tests" / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(f"s4_replay_{module_name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        pinned: dict[Path, str] = module.PINNED_SHA256
        assert pinned
        for target, expected in pinned.items():
            actual = hashlib.sha256(Path(target).read_bytes()).hexdigest()
            assert actual == expected, f"{Path(target).name} drifted from its pin"
    finally:
        sys.modules.pop(spec.name, None)


# --- canonical composition-root boundary (E5A pattern) ------------------------


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
        caller_id: str | None = CALLER_ID,
        credential: str | None = CALLER_SECRET,
    ) -> None:
        self.url = f"https://engine.internal{path}"
        self.method = method
        headers: dict[str, str] = {"content-type": "application/json"}
        if caller_id is not None:
            headers["x-padiem-engine-caller"] = caller_id
        if credential is not None:
            headers["x-padiem-engine-credential"] = credential
        self.headers = headers
        self._text = body.decode("utf-8")

    async def text(self) -> str:
        return self._text


def _identity_env(**extra: Any) -> _Env:
    return _Env(
        PADIEM_ENGINE_CALLER_ID=CALLER_ID,
        PADIEM_ENGINE_CALLER_SECRET=CALLER_SECRET,
        PADIEM_ENGINE_ALLOWED_APPS="b62",
        **extra,
    )


def _fetch(identity: Any, env: Any, request: Any) -> Any:
    return asyncio.run(identity.Default(ctx=None, env=env).fetch(request))


def _body(response: Any) -> dict:
    return json.loads(str(response.body))


@pytest.mark.parametrize("b14_bound", [False, True])
def test_document_route_fails_closed_on_canonical_fetch(
    identity_modules, b14_bound: bool
) -> None:
    _legacy, identity = identity_modules

    response = _fetch(
        identity,
        _identity_env(**({"B14_SERVICE": object()} if b14_bound else {})),
        _Request(DOCUMENT_CONTEXT_PATH, body=_request_body()),
    )

    assert response.status == 503
    payload = _body(response)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "document_context_unavailable"
    assert DOC_REF not in str(response.body)


def test_injected_documents_service_serves_trusted_caller(
    identity_modules,
) -> None:
    _legacy, identity = identity_modules
    service, resolver, port, authority = _service()
    real_factory = identity.Default.engine_services_factory

    def spying_factory(env: Any) -> Any:
        return dataclasses.replace(real_factory(env), documents=service)

    identity.Default.engine_services_factory = staticmethod(spying_factory)
    try:
        response = _fetch(
            identity,
            _identity_env(),
            _Request(
                DOCUMENT_CONTEXT_PATH,
                body=_request_body(),
                caller_id=CALLER_ID,
                credential=CALLER_SECRET,
            ),
        )
        assert response.status == 200
        assert _body(response)["ok"] is True
        assert authority.calls[-1] == (CALLER_ID, CALLER_SECRET)
        assert len(port.stored) == 1
        # One successful through-line = two resolver.resolve calls (bridge
        # double-resolve known debt, explicitly NOT fixed in S4).
        assert len(resolver.calls) == 2

        anonymous = _fetch(
            identity,
            _identity_env(),
            _Request(
                DOCUMENT_CONTEXT_PATH,
                body=_request_body(),
                caller_id=None,
                credential=None,
            ),
        )
        assert anonymous.status == 401
        assert _body(anonymous)["error"]["code"] == "service_authentication_failed"
        assert port.stored == [port.stored[0]]
        assert len(resolver.calls) == 2
    finally:
        identity.Default.engine_services_factory = staticmethod(real_factory)


def test_document_route_does_not_widen_existing_routes(identity_modules) -> None:
    _legacy, identity = identity_modules

    multimodal = _fetch(
        identity,
        _identity_env(),
        _Request(
            MULTIMODAL_PATH,
            body=json.dumps(
                {
                    "app_id": "b62",
                    "agent": {
                        "id": "vision-assistant",
                        "title": "Vision Assistant",
                        "description": "Bounded image-aware assistant fixture.",
                        "system_instruction": "Describe the attached image factually.",
                        "task_type": "general",
                        "optimize_for": "balanced",
                        "max_tokens": 256,
                    },
                    "messages": [{"role": "user", "content": "What is in this image?"}],
                    "attachment_ref": "att_F1xture-Ref_000123",
                }
            ).encode("utf-8"),
        ),
    )
    assert multimodal.status == 503
    assert _body(multimodal)["error"]["code"] == "attachment_resolver_unavailable"

    execute = _fetch(
        identity,
        _identity_env(),
        _Request("/internal/v1/execute", body=json.dumps({"app_id": "b62"}).encode()),
    )
    assert execute.status == 503
    assert _body(execute)["error"]["code"] == "b14_service_unavailable"


def test_legacy_worker_is_not_widened_by_e5b(identity_modules) -> None:
    legacy, _identity = identity_modules
    legacy_source = (APP_ROOT / "worker.py").read_text(encoding="utf-8")

    assert "DOCUMENT_CONTEXT_PATH" not in legacy_source
    assert "DocumentContextEngineService" not in legacy_source
    assert "document_context" not in legacy_source
    assert legacy._engine_services_for_env(_identity_env()).documents is None


def test_document_route_is_not_a_public_or_browser_surface(
    identity_modules,
) -> None:
    from app.contract_manifest import (
        EngineFeatureState,
        current_engine_contract_manifest,
    )

    _legacy, identity = identity_modules

    manifest = current_engine_contract_manifest()
    assert manifest.feature_state("public_browser_api") is EngineFeatureState.UNAVAILABLE
    assert (
        manifest.feature_state("document_projection")
        is EngineFeatureState.DEFERRED
    )

    identity_source = (APP_ROOT / "worker_identity.py").read_text(encoding="utf-8")
    assert "Access-Control-Allow-Origin" not in identity_source
    assert "workers.dev" not in identity_source
    assert "DOCUMENT_CONTEXT_PATH" in identity_source
    assert "_fetch_document_context" in identity_source
