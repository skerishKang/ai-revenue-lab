"""Contract of the CPython-mode HTTPS stand-ins for Worker Service bindings.

What is load-bearing here:
* the proof binds method, path, time and the exact body — a replay against a
  different method/path/body cannot verify with the same header;
* the PDF stand-in speaks the exact same path and JSON key set as the Worker
  adapter, so the B66 renderer sees one contract whichever host calls it;
* a binding-mode B14 never gains a transport on CPython (it must fail closed,
  not silently call something).
"""
from __future__ import annotations

import hashlib
import hmac
import json

import httpx
import pytest

from app.local_service_bridge import (
    HttpRpcBinding,
    LocalB66PdfRendererClient,
    ServiceProofConfigError,
    compose_local_b14_transports,
    service_proof_headers,
)

SECRET = "local-service-secret-0123456789abcdef"


def _proof_expected(secret: str, method: str, path: str, at: int, body: bytes) -> str:
    signed = b"\n".join((b"v1", method.encode(), path.encode(), str(at).encode(), body))
    return "v1=" + hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()


def test_proof_binds_method_path_time_and_body():
    body = b'{"a":1}'
    headers = service_proof_headers(SECRET, method="POST", path="/internal/rpc/x", body=body, at=1000)
    assert headers["x-padiem-service-at"] == "1000"
    assert headers["x-padiem-service-proof"] == _proof_expected(SECRET, "POST", "/internal/rpc/x", 1000, body)

    # A proof for one (method, path, body, time) never verifies for another.
    for variant in (
        service_proof_headers(SECRET, method="PUT", path="/internal/rpc/x", body=body, at=1000),
        service_proof_headers(SECRET, method="POST", path="/internal/rpc/y", body=body, at=1000),
        service_proof_headers(SECRET, method="POST", path="/internal/rpc/x", body=b'{"a":2}', at=1000),
        service_proof_headers(SECRET, method="POST", path="/internal/rpc/x", body=body, at=1001),
    ):
        assert variant["x-padiem-service-proof"] != headers["x-padiem-service-proof"]
    assert SECRET not in json.dumps(headers)


@pytest.mark.asyncio
async def test_http_rpc_binding_posts_the_named_method_with_a_proof():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = request.content
        return httpx.Response(200, json={"ok": True, "link": {"product_user_id": "usr_1"}})

    binding = HttpRpcBinding(
        "https://identity.example", SECRET,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await binding.resolve_or_create_product_link({"product_id": "b62"})
    assert result["ok"] is True
    assert seen["url"] == "https://identity.example/internal/rpc/resolve_or_create_product_link"
    expected = _proof_expected(
        SECRET, "POST", "/internal/rpc/resolve_or_create_product_link",
        int(seen["headers"]["x-padiem-service-at"]), seen["body"],
    )
    assert seen["headers"]["x-padiem-service-proof"] == expected


@pytest.mark.asyncio
async def test_http_rpc_binding_refuses_bad_answers_and_private_names():
    def refused(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"ok": False})

    binding = HttpRpcBinding(
        "https://identity.example", SECRET,
        client=httpx.AsyncClient(transport=httpx.MockTransport(refused)),
    )
    with pytest.raises(RuntimeError):
        await binding.resolve_auth_session({"session_id": "x"})

    def non_object(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[1, 2, 3])

    bind = HttpRpcBinding(
        "https://identity.example", SECRET,
        client=httpx.AsyncClient(transport=httpx.MockTransport(non_object)),
    )
    with pytest.raises(RuntimeError):
        await bind.resolve_auth_session({"session_id": "x"})
    with pytest.raises(AttributeError):
        bind.__deepcopy__


@pytest.mark.asyncio
async def test_pdf_stand_in_speaks_the_worker_contract_exactly():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        seen["proof"] = request.headers.get("x-padiem-service-proof", "")
        return httpx.Response(200, content=b"%PDF-1.7", headers={"content-type": "application/pdf"})

    client = LocalB66PdfRendererClient(
        "https://pdf.example", SECRET,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    status, body, content_type = await client.render_pdf(
        saved_skill_id="skill_1", skill_fingerprint="a" * 64,
        profile_fingerprint="b" * 64, render_model={"derivedBy": "quote-core", "template": {}},
    )
    assert seen["url"] == "https://pdf.example/internal/v1/render"
    assert set(seen["body"]) == {
        "saved_skill_id", "skill_fingerprint", "profile_fingerprint", "render_model",
    }
    assert seen["proof"].startswith("v1=")
    assert (status, body, content_type) == (200, b"%PDF-1.7", "application/pdf")


@pytest.mark.asyncio
async def test_pdf_stand_in_keeps_the_response_ceiling_and_generic_errors():
    def huge(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * (33 * 1024 * 1024))

    client = LocalB66PdfRendererClient(
        "https://pdf.example", SECRET,
        client=httpx.AsyncClient(transport=httpx.MockTransport(huge)),
    )
    with pytest.raises(RuntimeError) as caught:
        await client.render_pdf(
            saved_skill_id="s", skill_fingerprint="a" * 64,
            profile_fingerprint="b" * 64, render_model={},
        )
    assert "pdf.example" not in str(caught.value)

    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    client = LocalB66PdfRendererClient(
        "https://pdf.example", SECRET,
        client=httpx.AsyncClient(transport=httpx.MockTransport(broken)),
    )
    with pytest.raises(RuntimeError):
        await client.render_pdf(
            saved_skill_id="s", skill_fingerprint="a" * 64,
            profile_fingerprint="b" * 64, render_model={},
        )


def test_origins_and_secrets_are_strict():
    for bad_origin in ("http://identity.example", "https://identity.example/path", ""):
        with pytest.raises(ServiceProofConfigError):
            HttpRpcBinding(bad_origin, SECRET)
    with pytest.raises(ServiceProofConfigError):
        HttpRpcBinding("https://identity.example", "short")


def test_b14_composition_never_falls_back_to_a_binding_on_cpython():
    class Settings:
        b14_upstream_mode = "binding"
        b14_base_url = "https://b14.example"

    assert compose_local_b14_transports(Settings(), SECRET) == (None, None)

    Settings.b14_upstream_mode = "https"
    completion, stream = compose_local_b14_transports(Settings(), SECRET)
    assert completion is not None and stream is not None
