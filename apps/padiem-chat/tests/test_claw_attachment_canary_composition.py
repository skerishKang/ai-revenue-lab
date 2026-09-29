"""A6 server-only image attachment canary seam tests (#3210).

Proves the Padiem Chat leg of the seam on plain env objects only:

  EXISTING_WORKER_ENGINE_CALLER_REUSED = YES
  EXISTING_B54_PRODUCER_RESULT_REUSED  = YES
  NO_OS_ENVIRON_CALLER_SECRET_PATH     = YES
  NO_PUBLIC_ROUTE                      = YES
  NO_DISPATCH_SUPPLIED_SESSION_ID      = YES
  ENGINE_CALLER_SECRET_OUTPUT          = 0
  CANONICAL_SESSION_ID_BROWSER_OUTPUT  = 0
  SECOND_IDENTITY_AUTHORITY            = 0
  SECOND_SESSION_STORE                 = 0
  SECOND_CALLER_AUTHORITY              = 0
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from padiem_ai_engine_client import (
    ENGINE_INTERNAL_ORIGIN,
    ENGINE_MULTIMODAL_ATTACHMENTS_PATH,
    ENGINE_ORCHESTRATE_PATH,
)
from padiem_control_plane import (
    AuthSessionSnapshot,
    AuthSessionState,
    IdentityLinkState,
    ProductIdentityLink,
)
from padiem_control_plane.b54_identity_bridge import B54_PRODUCT_ID

from app.b54_canonical_session import (
    B54CanonicalSessionProducer,
    B54ServerAuthenticatedOwner,
)
from app.claw_attachment_canary_composition import (
    ClawAttachmentCanary,
    ClawAttachmentCanaryError,
    build_claw_attachment_canary,
    build_claw_attachment_canary_with_diagnostic,
)
from app.worker_config import (
    P01_DIAG_ENGINE_SERVICE_MISSING,
    P01_ENGINE_SERVICE_BINDING_NAME,
)
from app.worker_orchestration import (
    CloudflareEngineServiceTransport,
    _MAX_ATTACHMENT_REQUEST_BYTES,
)

from kagent.p01_adapter import P01_APP_ID

VALID_CALLER = "b54-p01-overlay-20260914-a1"
VALID_CREDENTIAL = "c" * 48
TENANT = "tenant_0123456789abcdef0123456789abcdef"
ATTACHMENT_REF = "att_" + "Ab3_-9" * 4
IMAGE_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQ"
    "AAAABJRU5ErkJggg=="
)
BRIDGED_AT = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


class _FakeWorkerRequest:
    created: list["_FakeWorkerRequest"] = []

    def __init__(self, url: str, **options: object) -> None:
        self.url = url
        self.options = options
        self.js_object = self
        self.__class__.created.append(self)


class _FakeEngineResponse:
    def __init__(self, body: str, status: int = 200) -> None:
        self.status = status
        self.headers = {"content-type": "application/json"}
        self._body = body

    async def text(self) -> str:
        return self._body


def _attachment_response_body(**overrides: object) -> str:
    attachment = {
        "attachment_ref": ATTACHMENT_REF,
        "media_type": "image/png",
        "byte_size": 68,
        "expires_at": None,
    }
    attachment.update(overrides)
    return json.dumps({"ok": True, "attachment": attachment}, ensure_ascii=False)


class _FakeEngineServiceBinding:
    def __init__(self, response_body: str | None = None) -> None:
        self.calls: list[_FakeWorkerRequest] = []
        self._response_body = response_body or _attachment_response_body()

    async def fetch(self, request: _FakeWorkerRequest) -> _FakeEngineResponse:
        self.calls.append(request)
        return _FakeEngineResponse(self._response_body)


class _FakeB54Authority:
    """The single test-owned identity/session authority, mirroring the deployed one."""

    def resolve_or_create_product_link(self, **kwargs: object) -> ProductIdentityLink:
        return ProductIdentityLink(
            product_id=kwargs["product_id"],
            product_user_id=kwargs["product_user_id"],
            canonical_subject_id=f"subject:{kwargs['product_id']}:{kwargs['product_user_id']}",
            state=IdentityLinkState.ACTIVE,
        )

    def resolve_active_memberships(self, *, canonical_subject_id: str):
        return (TENANT,)

    def establish_auth_session(self, **kwargs: object) -> AuthSessionSnapshot:
        subject = kwargs["subject"]
        return AuthSessionSnapshot(
            session_id=f"sess_{subject.subject_id}",
            product_id=kwargs["product_id"],
            subject=subject,
            issued_at=kwargs["authenticated_at"],
            expires_at=kwargs["not_after"],
            state=AuthSessionState.ACTIVE,
            revision=1,
            tenant_id=TENANT,
        )


async def _bridged_session():
    producer = B54CanonicalSessionProducer(
        authority=_FakeB54Authority(),
        session_max_age_seconds=3600,
        clock=lambda: BRIDGED_AT,
    )
    return await producer.establish(
        B54ServerAuthenticatedOwner(
            product_user_id="usr_canary", provider_subject="canary.owner"
        )
    )


def _env(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        P01_ENGINE_SERVICE_BINDING_NAME: SimpleNamespace(name="engine-service"),
        "P01_ENGINE_CALLER_ID": VALID_CALLER,
        "P01_ENGINE_CREDENTIAL": VALID_CREDENTIAL,
    }
    values.update(overrides)
    return values


def _request_factory(url: str, **kwargs: object) -> object:  # pragma: no cover - never called
    raise AssertionError("composition must not perform network transport")


def test_missing_worker_bindings_fail_closed_with_the_existing_diagnostics():
    canary, diagnostic = build_claw_attachment_canary_with_diagnostic(
        {}, request_factory=_request_factory
    )
    assert canary is None
    assert diagnostic == P01_DIAG_ENGINE_SERVICE_MISSING
    assert build_claw_attachment_canary({}, request_factory=_request_factory) is None


def test_composition_reuses_the_existing_worker_engine_binding_and_caller():
    binding = SimpleNamespace(name="engine-service")
    env = _env(**{P01_ENGINE_SERVICE_BINDING_NAME: binding})
    canary = build_claw_attachment_canary(env, request_factory=_request_factory)
    assert isinstance(canary, ClawAttachmentCanary)
    client = canary._client
    assert client.app_id == P01_APP_ID
    assert client.caller_id == VALID_CALLER
    assert client._transport._binding is binding


@pytest.mark.asyncio
async def test_admission_uses_the_server_session_id_and_fixed_internal_route():
    binding = _FakeEngineServiceBinding()
    canary = build_claw_attachment_canary(
        _env(**{P01_ENGINE_SERVICE_BINDING_NAME: binding}),
        request_factory=_FakeWorkerRequest,
    )
    session = await _bridged_session()
    assert session.auth_session.session_id == f"sess_subject:{B54_PRODUCT_ID}:usr_canary"

    result = await canary.admit_image_attachment(
        session, media_type="image/png", image_base64=IMAGE_B64, trace_id="trace_a6_0001"
    )

    assert result == {
        "attachment_ref": ATTACHMENT_REF,
        "media_type": "image/png",
        "byte_size": 68,
        "expires_at": None,
    }
    assert set(result) == {"attachment_ref", "media_type", "byte_size", "expires_at"}
    assert len(binding.calls) == 1
    request = binding.calls[0]
    assert request.url == f"{ENGINE_INTERNAL_ORIGIN}/internal/v1/multimodal/attachments"
    assert request.options["method"] == "POST"
    headers = request.options["headers"]
    assert headers["X-Padiem-Engine-Caller"] == VALID_CALLER
    assert headers["X-Padiem-Engine-Credential"] == VALID_CREDENTIAL
    payload = json.loads(str(request.options["body"]))
    assert payload["app_id"] == P01_APP_ID
    assert payload["session_id"] == session.auth_session.session_id
    assert payload["media_type"] == "image/png"
    assert payload["image_base64"] == IMAGE_B64
    assert payload["trace_id"] == "trace_a6_0001"
    serialized = json.dumps(payload, ensure_ascii=False)
    assert VALID_CREDENTIAL not in serialized
    assert session.auth_session.session_id not in json.dumps(result, ensure_ascii=False)


@pytest.mark.asyncio
async def test_dispatch_cannot_supply_any_session_identity():
    binding = _FakeEngineServiceBinding()
    canary = build_claw_attachment_canary(
        _env(**{P01_ENGINE_SERVICE_BINDING_NAME: binding}),
        request_factory=_FakeWorkerRequest,
    )
    session = await _bridged_session()

    with pytest.raises(TypeError):
        await canary.admit_image_attachment(
            session,
            media_type="image/png",
            image_base64=IMAGE_B64,
            session_id="sess_forged",
        )
    with pytest.raises(ClawAttachmentCanaryError) as raised:
        await canary.admit_image_attachment(
            "sess_forged", media_type="image/png", image_base64=IMAGE_B64
        )
    assert raised.value.code == "invalid_canary_session"
    assert binding.calls == []


@pytest.mark.asyncio
async def test_client_side_rejections_are_bounded_and_secret_free():
    binding = _FakeEngineServiceBinding()
    canary = build_claw_attachment_canary(
        _env(**{P01_ENGINE_SERVICE_BINDING_NAME: binding}),
        request_factory=_FakeWorkerRequest,
    )
    session = await _bridged_session()

    with pytest.raises(ClawAttachmentCanaryError) as raised:
        await canary.admit_image_attachment(
            session, media_type="image/gif", image_base64=IMAGE_B64
        )
    assert raised.value.code == "invalid_engine_request"
    assert VALID_CREDENTIAL not in str(raised.value)
    assert binding.calls == []


@pytest.mark.asyncio
async def test_engine_error_codes_survive_with_fixed_safe_messages():
    binding = _FakeEngineServiceBinding(
        json.dumps(
            {
                "ok": False,
                "error": {
                    "code": "attachment_too_large",
                    "message": "raw engine detail",
                    "retryable": False,
                    "metadata": None,
                },
            }
        )
    )
    canary = build_claw_attachment_canary(
        _env(**{P01_ENGINE_SERVICE_BINDING_NAME: binding}),
        request_factory=_FakeWorkerRequest,
    )
    session = await _bridged_session()

    with pytest.raises(ClawAttachmentCanaryError) as raised:
        await canary.admit_image_attachment(
            session, media_type="image/png", image_base64=IMAGE_B64
        )
    assert raised.value.code == "attachment_too_large"
    assert "raw engine detail" not in str(raised.value)


@pytest.mark.asyncio
async def test_malformed_engine_attachment_response_fails_closed_in_the_seam():
    binding = _FakeEngineServiceBinding(_attachment_response_body(locator="s3://private/locator"))
    canary = build_claw_attachment_canary(
        _env(**{P01_ENGINE_SERVICE_BINDING_NAME: binding}),
        request_factory=_FakeWorkerRequest,
    )
    session = await _bridged_session()

    with pytest.raises(ClawAttachmentCanaryError) as raised:
        await canary.admit_image_attachment(
            session, media_type="image/png", image_base64=IMAGE_B64
        )
    assert raised.value.code == "invalid_engine_response"
    assert "s3://private" not in str(raised.value)


def test_seam_module_never_reads_os_environ_or_mints_identity():
    root = Path(__file__).resolve().parents[1]
    source = (root / "app" / "claw_attachment_canary_composition.py").read_text(
        encoding="utf-8"
    )
    assert "import os" not in source
    assert "os.environ[" not in source
    assert "os.environ.get" not in source
    assert "import secrets" not in source
    assert "secrets." not in source
    assert "uuid" not in source


def test_seam_imports_only_the_existing_authorities():
    root = Path(__file__).resolve().parents[1]
    source = (root / "app" / "claw_attachment_canary_composition.py").read_text(
        encoding="utf-8"
    )
    import_lines = [
        line.strip()
        for line in source.splitlines()
        if line.strip().startswith(("from ", "import "))
    ]
    assert import_lines
    allowed_prefixes = (
        "from __future__ import",
        "from typing import",
        "from padiem_ai_engine_client import",
        "from padiem_control_plane import",
        "from padiem_control_plane.b54_identity_bridge import",
        "from .claw_p01_composition import",
    )
    for line in import_lines:
        assert line.startswith(allowed_prefixes), line


def test_seam_is_not_wired_to_any_public_route():
    root = Path(__file__).resolve().parents[1]
    module_name = "claw_attachment_canary_composition"
    for relative in ("worker.py", "app/app_factory.py", "app/claw_routes.py"):
        source = (root / relative).read_text(encoding="utf-8")
        assert module_name not in source, relative
    seam = (root / "app" / f"{module_name}.py").read_text(encoding="utf-8")
    assert "/api/" not in seam
    assert "add_route" not in seam
    assert "from starlette" not in seam
    assert "from fastapi" not in seam


@pytest.mark.asyncio
async def test_transport_route_allowlist_enables_only_the_fixed_attachment_route():
    binding = _FakeEngineServiceBinding()
    transport = CloudflareEngineServiceTransport(binding, request_factory=_FakeWorkerRequest)
    response = await transport.request(
        method="POST",
        url=f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_MULTIMODAL_ATTACHMENTS_PATH}",
        headers={},
        body=b"{}",
    )
    assert response.status == 200
    assert len(binding.calls) == 1
    assert binding.calls[0].url == (
        f"{ENGINE_INTERNAL_ORIGIN}/internal/v1/multimodal/attachments"
    )

    with pytest.raises(ValueError):
        await transport.request(
            method="POST",
            url=f"{ENGINE_INTERNAL_ORIGIN}/internal/v1/unknown",
            headers={},
            body=b"{}",
        )
    with pytest.raises(ValueError):
        await transport.request(
            method="GET",
            url=f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_MULTIMODAL_ATTACHMENTS_PATH}",
            headers={},
            body=None,
        )


@pytest.mark.asyncio
async def test_transport_request_bounds_are_route_specific():
    binding = _FakeEngineServiceBinding()
    transport = CloudflareEngineServiceTransport(binding, request_factory=_FakeWorkerRequest)

    at_limit = b"x" * _MAX_ATTACHMENT_REQUEST_BYTES
    await transport.request(
        method="POST",
        url=f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_MULTIMODAL_ATTACHMENTS_PATH}",
        headers={},
        body=at_limit,
    )
    assert len(binding.calls) == 1

    with pytest.raises(ValueError):
        await transport.request(
            method="POST",
            url=f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_MULTIMODAL_ATTACHMENTS_PATH}",
            headers={},
            body=b"x" * (_MAX_ATTACHMENT_REQUEST_BYTES + 1),
        )
    # The existing text/reference routes keep their 256 KiB bound.
    with pytest.raises(ValueError):
        await transport.request(
            method="POST",
            url=f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_ORCHESTRATE_PATH}",
            headers={},
            body=b"x" * (256 * 1024 + 1),
        )
