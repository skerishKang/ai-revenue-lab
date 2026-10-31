"""Contract of the CPython-mode HTTPS stand-ins for Worker Service bindings.

What is load-bearing here:
* the v2 proof binds method, path, time, the request id and the exact body — a
  captured request cannot be re-signed under another id, and the same bytes
  under a new id are a different request;
* every attempt names itself with a fresh id, and a replay refusal is retried
  with a new id up to a cap, never forever;
* the PDF stand-in speaks the exact same path and JSON key set as the Worker
  adapter, so the B66 renderer sees one contract whichever host calls it;
* a binding-mode B14 never gains a transport on CPython (it must fail closed,
  not silently call something).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re

import httpx
import pytest

from app.local_service_bridge import (
    HttpRpcBinding,
    LocalB66PdfRendererClient,
    RPC_MAX_ATTEMPTS,
    ServiceProofConfigError,
    compose_local_b14_transports,
    new_service_id,
    service_proof_headers,
)

SECRET = "local-service-secret-0123456789abcdef"
REPLAY_STATUS = 409


def _proof_expected_v2(
    secret: str, method: str, path: str, at: int, service_id: str, body: bytes
) -> str:
    signed = b"\n".join(
        (b"v2", method.encode(), path.encode(), str(at).encode(), service_id.encode(), body)
    )
    return "v2=" + hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()


def _proof_expected_v1(secret: str, method: str, path: str, at: int, body: bytes) -> str:
    signed = b"\n".join((b"v1", method.encode(), path.encode(), str(at).encode(), body))
    return "v1=" + hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()


def test_proof_binds_method_path_time_id_and_body():
    body = b'{"a":1}'
    service_id = new_service_id()
    headers = service_proof_headers(
        SECRET, method="POST", path="/internal/rpc/x", body=body, at=1000,
        service_id=service_id,
    )
    assert headers["x-padiem-service-at"] == "1000"
    assert headers["x-padiem-service-id"] == service_id
    assert headers["x-padiem-service-proof"] == _proof_expected_v2(
        SECRET, "POST", "/internal/rpc/x", 1000, service_id, body
    )

    # A proof for one (method, path, body, time, id) never verifies for another.
    for variant in (
        service_proof_headers(SECRET, method="PUT", path="/internal/rpc/x", body=body,
                              at=1000, service_id=service_id),
        service_proof_headers(SECRET, method="POST", path="/internal/rpc/y", body=body,
                              at=1000, service_id=service_id),
        service_proof_headers(SECRET, method="POST", path="/internal/rpc/x", body=b'{"a":2}',
                              at=1000, service_id=service_id),
        service_proof_headers(SECRET, method="POST", path="/internal/rpc/x", body=body,
                              at=1001, service_id=service_id),
        # The id is what the replay defence consumes, so it is bound too.
        service_proof_headers(SECRET, method="POST", path="/internal/rpc/x", body=body,
                              at=1000, service_id=new_service_id()),
    ):
        assert variant["x-padiem-service-proof"] != headers["x-padiem-service-proof"]
    assert SECRET not in json.dumps(headers)


def test_service_id_is_fresh_and_shaped_for_the_ingress():
    ingress_shape = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{15,127}$")
    ids = {new_service_id() for _ in range(200)}
    assert len(ids) == 200
    for service_id in ids:
        assert ingress_shape.fullmatch(service_id)


def test_the_pdf_lane_keeps_the_v1_proof_its_renderer_verifies():
    # /internal/v1/render is not the RPC ingress; it has no v2 verifier yet.
    headers = service_proof_headers(
        SECRET, method="POST", path="/internal/v1/render", body=b"{}", at=1000
    )
    assert headers["x-padiem-service-proof"].startswith("v1=")
    assert "x-padiem-service-id" not in headers


@pytest.mark.asyncio
async def test_http_rpc_binding_posts_the_named_method_with_a_signed_id():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.setdefault("ids", []).append(request.headers.get("x-padiem-service-id", ""))
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
    service_id = seen["ids"][0]
    expected = _proof_expected_v2(
        SECRET, "POST", "/internal/rpc/resolve_or_create_product_link",
        int(seen["headers"]["x-padiem-service-at"]), service_id, seen["body"],
    )
    assert seen["headers"]["x-padiem-service-proof"] == expected

    # Two calls are two requests, so they never arrive naming themselves alike.
    await binding.resolve_or_create_product_link({"product_id": "b62"})
    assert seen["ids"][0] != seen["ids"][1]


@pytest.mark.asyncio
async def test_http_rpc_binding_replays_a_refusal_under_a_new_id():
    seen: dict = {"ids": []}

    def handler(request: httpx.Request) -> httpx.Response:
        service_id = request.headers.get("x-padiem-service-id", "")
        seen["ids"].append(service_id)
        seen["bodies"] = seen.get("bodies", [])
        seen["bodies"].append(request.content)
        if len(seen["ids"]) == 1:
            return httpx.Response(
                REPLAY_STATUS, json={"ok": False, "error": {"code": "rpc_replay_detected"}}
            )
        return httpx.Response(200, json={"ok": True})

    binding = HttpRpcBinding(
        "https://identity.example", SECRET,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await binding.resolve_auth_session({"session_id": "x"})
    assert result["ok"] is True
    assert len(seen["ids"]) == 2
    assert seen["ids"][0] != seen["ids"][1]
    # Only the id changes between the attempts, so the retry is the same call.
    assert seen["bodies"][0] == seen["bodies"][1]


@pytest.mark.asyncio
async def test_http_rpc_binding_caps_a_target_that_keeps_refusing():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.headers.get("x-padiem-service-id", ""))
        return httpx.Response(
            REPLAY_STATUS, json={"ok": False, "error": {"code": "rpc_replay_detected"}}
        )

    binding = HttpRpcBinding(
        "https://identity.example", SECRET,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(RuntimeError):
        await binding.resolve_auth_session({"session_id": "x"})
    assert len(calls) == RPC_MAX_ATTEMPTS
    assert len(set(calls)) == len(calls)


@pytest.mark.asyncio
async def test_a_target_without_a_replay_guard_keeps_the_v1_proof():
    seen: dict = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["calls"] += 1
        seen["headers"] = dict(request.headers)
        seen["body"] = request.content
        return httpx.Response(
            REPLAY_STATUS, json={"ok": False, "error": {"code": "rpc_replay_detected"}}
        )

    binding = HttpRpcBinding(
        "https://broker.example", SECRET, sign_request_id=False,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(RuntimeError):
        await binding.get_enrollment_binding({"challenge_id": "x"})
    # No id is signed, so there is nothing a new attempt could change.
    assert seen["calls"] == 1
    assert "x-padiem-service-id" not in seen["headers"]
    assert seen["headers"]["x-padiem-service-proof"] == _proof_expected_v1(
        SECRET, "POST", "/internal/rpc/get_enrollment_binding",
        int(seen["headers"]["x-padiem-service-at"]), seen["body"],
    )


@pytest.mark.asyncio
async def test_http_rpc_binding_does_not_retry_a_plain_failure():
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503, json={"ok": False})

    binding = HttpRpcBinding(
        "https://identity.example", SECRET,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(RuntimeError):
        await binding.resolve_auth_session({"session_id": "x"})
    assert calls == [1]


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
