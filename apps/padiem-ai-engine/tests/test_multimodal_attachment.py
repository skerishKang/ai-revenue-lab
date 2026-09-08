"""Focused network-free conformance tests for Engine E5A (#1750).

The caller wire may carry only an opaque server-issued ``attachment_ref``. A
test-only in-memory trusted resolver stands in for the deployment-owned storage
authority; the existing Core ``MultimodalExecutionRequest`` /
``MultimodalExecutionRuntime`` contracts remain the sole image/media/model
execution authority. No provider, storage or filesystem network call may occur
in this suite.
"""

from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from padiem_ai_core import (
    B14RouteMetadata,
    ExecutionResult,
    RunMetadata,
    RunStatus,
    UsageMetadata,
)
from padiem_ai_core.b14_multimodal import MAX_B14_IMAGE_BYTES
from padiem_ai_core.multimodal_execution_runtime import MultimodalExecutionRequest

from app.attachment_authority import (
    EngineAttachmentAuthorityError,
    TrustedImageAttachment,
    require_opaque_attachment_ref,
)
from app.multimodal_attachment_service import (
    MULTIMODAL_EXECUTE_PATH,
    MultimodalAttachmentEngineService,
)

APP_ROOT = Path(__file__).resolve().parents[1]
APP_ID = "b62"
ATTACHMENT_REF = "att_" + "e5a" * 5 + "01"
PROVENANCE_ID = "prov_1750_0001"

# Test-authority-only private storage state. It is deliberately never returned
# by the resolver into Engine, so these strings can prove a zero-leak boundary.
PRIVATE_STORAGE_LOCATOR = "s3://padiem-private-attachments/b62/u-1/obj-1750"
PRIVATE_STORAGE_CREDENTIAL = "AKIA-SIMULATED-CREDENTIAL-1750"

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"e5a-png-payload"
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"e5a-jpeg-payload"
WEBP_BYTES = b"RIFF\x14\x00\x00\x00WEBP" + b"e5a-webp-payload"
UNTRUSTED_TEXT = b"caller-supplied-raw-bytes-1750"

APP_SCOPE_MISMATCH_REF = "att_" + "other" * 3 + "001"


def valid_payload(ref: str = ATTACHMENT_REF, app_id: str = APP_ID) -> dict[str, Any]:
    return {
        "app_id": app_id,
        "agent": {
            "id": "image-agent",
            "title": "Image",
            "description": "Bounded image description assistant.",
            "system_instruction": "Describe the image carefully.",
            "task_type": "general",
            "optimize_for": "korean",
            "max_tokens": 512,
            "required_capabilities": ["chat", "image"],
            "model_policy": {
                "model": "b14/auto",
                "allow_external_fallback": False,
                "max_attempts": 1,
            },
        },
        "messages": [{"role": "user", "content": "이 사진을 설명해줘"}],
        "attachment_ref": ref,
        "session_id": "session-mm-1750",
        "trace_id": "trace-mm-1750",
    }


def execution_result() -> ExecutionResult:
    return ExecutionResult(
        answer="사진 답변",
        route=B14RouteMetadata(
            selected_provider="provider-x",
            selected_model="provider-x/image",
            actual_response_model="provider-x/image",
            attempt_count=1,
            fallback_used=False,
        ),
        metadata=RunMetadata(
            trace_id="trace-mm-1750",
            app_id=APP_ID,
            agent_id="image-agent",
            session_id="session-mm-1750",
            status=RunStatus.COMPLETED,
            provider="provider-x",
            model="provider-x/image",
            duration_ms=12,
            usage=UsageMetadata(input_tokens=5, output_tokens=3, total_tokens=8),
        ),
    )


@dataclass
class FakeRuntime:
    """Records the Core request it received; performs no execution at all."""

    result: ExecutionResult | None = None
    error: Exception | None = None
    requests: list[Any] = field(default_factory=list)

    async def run(self, request: Any) -> ExecutionResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


class RuntimeFactory:
    def __init__(self, runtime: FakeRuntime) -> None:
        self.runtime = runtime
        self.app_ids: list[str] = []

    def __call__(self, app_id: str) -> FakeRuntime:
        self.app_ids.append(app_id)
        return self.runtime


class InMemoryTrustedAttachmentResolver:
    """Test-only deployment authority. Never wired into Production composition."""

    def __init__(
        self,
        *,
        attachments: dict[str, tuple[str, bytes]] | None = None,
        unknown_refs: tuple[str, ...] = (),
        expired_refs: tuple[str, ...] = (),
        app_scope_denials: tuple[str, ...] = (),
        return_wrong_ref: tuple[str, ...] = (),
        storage_locator: str = PRIVATE_STORAGE_LOCATOR,
        storage_credential: str = PRIVATE_STORAGE_CREDENTIAL,
    ) -> None:
        self._attachments = dict(attachments or {})
        self._unknown_refs = set(unknown_refs)
        self._expired_refs = set(expired_refs)
        self._app_scope_denials = set(app_scope_denials)
        self._return_wrong_ref = set(return_wrong_ref)
        # Private resolver state that must never cross the Engine boundary.
        self._storage_locator = storage_locator
        self._storage_credential = storage_credential
        self.calls: list[dict[str, str]] = []

    async def resolve_image(self, *, app_id: str, attachment_ref: str) -> TrustedImageAttachment:
        self.calls.append({"app_id": app_id, "attachment_ref": attachment_ref})
        if attachment_ref in self._unknown_refs:
            raise EngineAttachmentAuthorityError(
                "attachment_not_found",
                "Attachment reference is unknown.",
                status_code=404,
            )
        media_type, data = self._attachments.get(attachment_ref, ("image/png", PNG_BYTES))
        if attachment_ref in self._app_scope_denials:
            return TrustedImageAttachment(
                attachment_ref=attachment_ref,
                app_id="another-app",
                media_type=media_type,
                data=data,
                provenance_id=PROVENANCE_ID,
            )
        expires_at = (
            datetime.now(timezone.utc) - timedelta(seconds=30)
            if attachment_ref in self._expired_refs
            else None
        )
        return TrustedImageAttachment(
            attachment_ref=APP_SCOPE_MISMATCH_REF if attachment_ref in self._return_wrong_ref else attachment_ref,
            app_id=app_id,
            media_type=media_type,
            data=data,
            provenance_id=PROVENANCE_ID,
            expires_at=expires_at,
        )


def service_with(
    resolver: InMemoryTrustedAttachmentResolver | None,
    runtime: FakeRuntime | None = None,
) -> tuple[MultimodalAttachmentEngineService, FakeRuntime, RuntimeFactory]:
    fake = runtime or FakeRuntime(result=execution_result())
    factory = RuntimeFactory(fake)
    service = MultimodalAttachmentEngineService(
        runtime_factory=factory,
        attachment_resolver=resolver,
    )
    return service, fake, factory


def error_code(response: Any) -> str:
    return response.body["error"]["code"]


def assert_no_runtime_call(factory: RuntimeFactory) -> None:
    assert factory.app_ids == []
    assert factory.runtime.requests == []


def serialized(response: Any) -> str:
    return json.dumps(response.body, ensure_ascii=False)


# --- reference-only authority -------------------------------------------------


async def test_trusted_opaque_reference_resolves_and_projects_provenance_only() -> None:
    resolver = InMemoryTrustedAttachmentResolver(
        attachments={ATTACHMENT_REF: ("image/png", PNG_BYTES)}
    )
    service, runtime, factory = service_with(resolver)

    response = await service.execute_payload(valid_payload())

    assert response.status_code == 200
    assert response.body["ok"] is True
    assert resolver.calls == [{"app_id": APP_ID, "attachment_ref": ATTACHMENT_REF}]
    assert factory.app_ids == [APP_ID]
    assert len(runtime.requests) == 1
    assert isinstance(runtime.requests[0], MultimodalExecutionRequest)
    attachment = response.body["attachment"]
    assert attachment == {
        "kind": "image",
        "media_type": "image/png",
        "byte_size": len(PNG_BYTES),
        "provenance_id": PROVENANCE_ID,
    }


@pytest.mark.parametrize(
    ("media_type", "data"),
    [
        ("image/png", PNG_BYTES),
        ("image/jpeg", JPEG_BYTES),
        ("image/webp", WEBP_BYTES),
    ],
)
async def test_valid_reference_reaches_core_multimodal_runtime(
    media_type: str, data: bytes
) -> None:
    resolver = InMemoryTrustedAttachmentResolver(attachments={ATTACHMENT_REF: (media_type, data)})
    service, runtime, _factory = service_with(resolver)

    response = await service.execute_payload(valid_payload())

    assert response.status_code == 200
    request = runtime.requests[0]
    assert isinstance(request, MultimodalExecutionRequest)
    content = request.messages[-1]["content"]
    assert content[0] == {"type": "text", "text": "이 사진을 설명해줘"}
    image_url = content[1]["image_url"]["url"]
    assert image_url.startswith(f"data:{media_type};base64,")
    assert base64.b64decode(image_url.split(",", 1)[1]) == data
    assert response.body["attachment"]["media_type"] == media_type


def test_opaque_reference_wire_shape_is_reference_only() -> None:
    assert require_opaque_attachment_ref(ATTACHMENT_REF) == ATTACHMENT_REF
    for forbidden in (
        "/tmp/cat.png",
        "C:\\Users\\me\\cat.png",
        "https://example.com/cat.png",
        "r2://bucket/key",
        "AKIAEXAMPLECREDENTIAL1750",
        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwAEhgD/AYE1G9EAAAAASUVORK5CYII=",
        "",
        "att_short",
        1234,
        None,
        b"att_e5ae5ae5ae5a01",
    ):
        with pytest.raises(EngineAttachmentAuthorityError) as info:
            require_opaque_attachment_ref(forbidden)
        assert info.value.code == "invalid_attachment_reference"


@pytest.mark.parametrize(
    "caller_authority",
    [
        "/tmp/cat.png",
        "C:\\Users\\me\\cat.png",
        "https://example.com/cat.png",
        "s3://padiem-private-attachments/b62/u-1/obj-1750",
        "r2://bucket/key",
        "AKIAEXAMPLECREDENTIAL1750",
        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwAEhgD/AYE1G9EAAAAASUVORK5CYII=",
    ],
)
async def test_caller_supplied_storage_authority_is_rejected_before_resolution(
    caller_authority: str,
) -> None:
    resolver = InMemoryTrustedAttachmentResolver()
    service, runtime, factory = service_with(resolver)

    response = await service.execute_payload(valid_payload(ref=caller_authority))

    assert response.status_code == 400
    assert error_code(response) == "invalid_attachment_reference"
    assert resolver.calls == []
    assert_no_runtime_call(factory)


@pytest.mark.parametrize(
    "inline_field",
    [
        "image_data",
        "file_path",
        "url",
        "storage_endpoint",
        "storage_credential",
        "data_url",
        "attachment_data",
    ],
)
async def test_inline_bytes_and_locator_fields_are_not_accepted(inline_field: str) -> None:
    resolver = InMemoryTrustedAttachmentResolver()
    service, runtime, factory = service_with(resolver)
    payload = valid_payload()
    payload[inline_field] = UNTRUSTED_TEXT if inline_field in {"image_data", "attachment_data", "data_url"} else "s3://private/key"

    response = await service.execute_payload(payload)

    assert response.status_code == 400
    assert error_code(response) == "invalid_request"
    assert resolver.calls == []
    assert_no_runtime_call(factory)


async def test_missing_trusted_resolver_fails_closed() -> None:
    service, _runtime, factory = service_with(None)

    response = await service.execute_payload(valid_payload())

    assert response.status_code == 503
    assert error_code(response) == "attachment_resolver_unavailable"
    assert_no_runtime_call(factory)


async def test_unknown_reference_fails_closed() -> None:
    resolver = InMemoryTrustedAttachmentResolver(unknown_refs=(ATTACHMENT_REF,))
    service, _runtime, factory = service_with(resolver)

    response = await service.execute_payload(valid_payload())

    assert response.status_code == 404
    assert error_code(response) == "attachment_not_found"
    assert_no_runtime_call(factory)


async def test_expired_reference_fails_closed() -> None:
    resolver = InMemoryTrustedAttachmentResolver(expired_refs=(ATTACHMENT_REF,))
    service, _runtime, factory = service_with(resolver)

    response = await service.execute_payload(valid_payload())

    assert response.status_code == 410
    assert error_code(response) == "attachment_expired"
    assert_no_runtime_call(factory)


async def test_app_scope_mismatch_fails_closed() -> None:
    resolver = InMemoryTrustedAttachmentResolver(app_scope_denials=(ATTACHMENT_REF,))
    service, _runtime, factory = service_with(resolver)

    response = await service.execute_payload(valid_payload())

    assert response.status_code == 403
    assert error_code(response) == "attachment_scope_mismatch"
    assert_no_runtime_call(factory)


async def test_returned_reference_identity_mismatch_fails_closed() -> None:
    resolver = InMemoryTrustedAttachmentResolver(return_wrong_ref=(ATTACHMENT_REF,))
    service, _runtime, factory = service_with(resolver)

    response = await service.execute_payload(valid_payload())

    assert response.status_code == 403
    assert error_code(response) == "attachment_scope_mismatch"
    assert_no_runtime_call(factory)


async def test_caller_cannot_select_subject_tenant_scope() -> None:
    """Subject/tenant scope is resolver-owned; the wire has no selector for it."""

    resolver = InMemoryTrustedAttachmentResolver()
    service, _runtime, factory = service_with(resolver)
    payload = valid_payload()
    payload["tenant_id"] = "tenant-x"
    payload["subject_id"] = "u-1"

    response = await service.execute_payload(payload)

    assert response.status_code == 400
    assert error_code(response) == "invalid_request"
    assert resolver.calls == []
    assert_no_runtime_call(factory)


async def test_resolver_returning_non_contract_value_fails_closed() -> None:
    class LeakyResolver:
        async def resolve_image(self, *, app_id: str, attachment_ref: str) -> Any:
            return {
                "attachment_ref": attachment_ref,
                "app_id": app_id,
                "media_type": "image/png",
                "data": PNG_BYTES,
                "provenance_id": PROVENANCE_ID,
                "storage_locator": PRIVATE_STORAGE_LOCATOR,
                "storage_credential": PRIVATE_STORAGE_CREDENTIAL,
            }

    service, _runtime, factory = service_with(LeakyResolver())  # type: ignore[arg-type]

    response = await service.execute_payload(valid_payload())

    assert response.status_code == 503
    assert error_code(response) == "attachment_resolver_unavailable"
    assert_no_runtime_call(factory)


# --- Core contract reuse ------------------------------------------------------


async def test_core_image_size_bound_is_reused_not_duplicated() -> None:
    assert MAX_B14_IMAGE_BYTES == 4 * 1024 * 1024
    oversized = b"\x89PNG\r\n\x1a\n" + b"x" * (MAX_B14_IMAGE_BYTES)
    resolver = InMemoryTrustedAttachmentResolver(
        attachments={ATTACHMENT_REF: ("image/png", oversized)}
    )
    service, _runtime, factory = service_with(resolver)

    response = await service.execute_payload(valid_payload())

    assert response.status_code == 413
    assert error_code(response) == "attachment_too_large"
    assert_no_runtime_call(factory)


async def test_core_media_magic_validation_is_reused() -> None:
    resolver = InMemoryTrustedAttachmentResolver(
        attachments={ATTACHMENT_REF: ("image/png", UNTRUSTED_TEXT)}
    )
    service, _runtime, factory = service_with(resolver)

    response = await service.execute_payload(valid_payload())

    assert response.status_code == 400
    assert error_code(response) == "invalid_multimodal_input"
    assert_no_runtime_call(factory)
    body = serialized(response)
    assert base64.b64encode(UNTRUSTED_TEXT).decode("ascii") not in body
    assert UNTRUSTED_TEXT.decode("ascii") not in body


@pytest.mark.parametrize("media_type", ["image/gif", "image/svg+xml", "application/pdf"])
async def test_unsupported_media_is_safe_deterministic_error(media_type: str) -> None:
    resolver = InMemoryTrustedAttachmentResolver(
        attachments={ATTACHMENT_REF: (media_type, PNG_BYTES)}
    )
    service, _runtime, factory = service_with(resolver)

    response = await service.execute_payload(valid_payload())

    assert response.status_code == 400
    assert error_code(response) == "invalid_multimodal_input"
    assert response.body["error"]["message"] == (
        "Resolved attachment is not valid for bounded multimodal execution."
    )
    assert response.body["error"]["retryable"] is False
    assert_no_runtime_call(factory)


# --- zero-leak and zero-side-effect conformance -------------------------------


def test_public_response_projects_no_private_storage_or_binary_bytes() -> None:
    service, runtime, factory = service_with(
        InMemoryTrustedAttachmentResolver(attachments={ATTACHMENT_REF: ("image/png", PNG_BYTES)})
    )
    response = asyncio.run(service.execute_payload(valid_payload()))

    assert response.status_code == 200
    body = serialized(response)
    assert PRIVATE_STORAGE_LOCATOR not in body
    assert PRIVATE_STORAGE_CREDENTIAL not in body
    assert base64.b64encode(PNG_BYTES).decode("ascii") not in body
    assert PNG_BYTES.decode("latin-1") not in body
    assert ATTACHMENT_REF not in body


def test_engine_has_no_second_image_runtime() -> None:
    authority_source = (APP_ROOT / "app" / "attachment_authority.py").read_text(encoding="utf-8")
    service_source = (APP_ROOT / "app" / "multimodal_attachment_service.py").read_text(encoding="utf-8")

    # The only byte ceiling comes from Core; no parallel image validator exists.
    assert "MAX_B14_IMAGE_BYTES" in authority_source
    assert "padiem_ai_core.b14_multimodal" in authority_source
    for module_source in (authority_source, service_source):
        assert "_image_magic" not in module_source
        assert "b64decode" not in module_source
        assert 'image/png"' not in module_source
        assert 'image/jpeg"' not in module_source
        assert 'image/webp"' not in module_source
        assert "\\x89PNG" not in module_source
        assert "\\xff\\xd8\\xff" not in module_source
        assert "RIFF" not in module_source
    assert "MultimodalExecutionRequest" in service_source
    assert "padiem_ai_core.multimodal_execution_runtime" in service_source


def test_engine_multimodal_modules_make_no_network_or_file_calls() -> None:
    forbidden_imports = {
        "httpx",
        "aiohttp",
        "requests",
        "urllib",
        "socket",
        "tempfile",
        "shutil",
        "ftplib",
        "s3",
        "boto3",
    }
    for name in ("attachment_authority.py", "multimodal_attachment_service.py"):
        source = (APP_ROOT / "app" / name).read_text(encoding="utf-8")
        for module in forbidden_imports:
            assert module not in source, f"{name} must not import {module}"
        assert ".write(" not in source
        assert "open(" not in source
        assert "Path(" not in source


def test_conformance_performs_no_network_or_persistence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The full E5A flow is offline and writes nothing to disk.

    Only outbound connection entry points are fenced. ``socket.socket`` itself
    stays intact because the platform event loop needs it for its self-pipe.
    """

    def deny(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("outbound network access attempted in E5A conformance")

    monkeypatch.setattr("socket.create_connection", deny)
    monkeypatch.setattr("socket.getaddrinfo", deny)
    monkeypatch.setattr("httpx.AsyncClient.send", deny)
    monkeypatch.setattr("httpx.Client.send", deny)
    monkeypatch.chdir(tmp_path)

    resolver = InMemoryTrustedAttachmentResolver(
        attachments={ATTACHMENT_REF: ("image/png", PNG_BYTES)}
    )
    service, runtime, factory = service_with(resolver)

    response = asyncio.run(service.execute_payload(valid_payload()))

    assert response.status_code == 200
    assert len(runtime.requests) == 1
    assert list(tmp_path.iterdir()) == []


async def test_http_envelope_fails_closed_without_private_echo() -> None:
    resolver = InMemoryTrustedAttachmentResolver()
    service, _runtime, _factory = service_with(resolver)

    response = await service.handle(
        method="POST",
        path=MULTIMODAL_EXECUTE_PATH,
        content_type="application/json",
        body=PRIVATE_STORAGE_CREDENTIAL.encode("ascii"),
    )

    assert response.status_code == 400
    assert error_code(response) == "invalid_json"
    assert PRIVATE_STORAGE_CREDENTIAL not in serialized(response)
