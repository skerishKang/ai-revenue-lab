"""COM2 -> fake authority HTTP and hard fail on local authority configuration."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import httpx
import pytest

from com2_identity_do_proxy import (
    RPC_MAX_ATTEMPTS,
    IdentityDoProxy,
    IdentityRpcReplayRefused,
)
from com2_identity_entrypoint import build_app
from com2_identity_rpc_ingress import COM2_IDENTITY_RPC_METHODS, create_app
from internal_rpc_ingress import SERVICE_ID_HEADER, proof_for, proof_for_v2

SECRET = "synthetic-" + "s" * 32


@pytest.mark.asyncio
async def test_all_identity_methods_relay_to_fake_server_with_signed_payload():
    observed = []
    service_ids = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["content-length"]))
            at = int(self.headers["x-padiem-service-at"])
            service_id = self.headers[SERVICE_ID_HEADER]
            service_ids.append(service_id)
            assert self.headers["x-padiem-service-proof"] == proof_for_v2(
                SECRET, method="POST", path=self.path, at=at,
                service_id=service_id, body=body,
            )
            observed.append(self.path)
            response = json.dumps({"ok": True, "echo": json.loads(body)}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)
        def log_message(self, *args): pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def send_to_local_fake(url, body, headers):
        path = urlsplit(url).path
        request = Request(f"http://127.0.0.1:{server.server_port}" + path,
                          data=body, headers=headers, method="POST")
        with urlopen(request, timeout=3) as response:
            return json.load(response)
    try:
        proxy = IdentityDoProxy("https://identity.invalid", SECRET, sender=send_to_local_fake)
        app = create_app(authority=proxy, secret=SECRET)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
            for method in sorted(COM2_IDENTITY_RPC_METHODS):
                path = "/internal/rpc/" + method
                body = b'{"sample":"synthetic"}'
                at = 1900000000
                # ingress time is verified using the actual system clock
                import time
                at = int(time.time())
                proof = proof_for(SECRET, method="POST", path=path, at=at, body=body)
                result = await client.post(path, content=body, headers={
                    "x-padiem-service-at": str(at), "x-padiem-service-proof": proof,
                })
                assert result.status_code == 200, method
                assert result.json() == {"ok": True, "echo": {"sample": "synthetic"}}
        assert len(observed) == 23 and len(set(observed)) == 23
        # Every relayed call names itself, and never reuses the name.
        assert len(service_ids) == 23 and len(set(service_ids)) == 23
        with pytest.raises(AttributeError):
            proxy.unapproved_method
    finally:
        server.shutdown()
        thread.join(3)
        server.server_close()


def test_local_sqlite_factory_and_database_configuration_cannot_start(monkeypatch, tmp_path):
    secret_file = tmp_path / "secret"
    secret_file.write_text(SECRET)
    monkeypatch.setenv("COM2_IDENTITY_RPC_SECRET_FILE", str(secret_file))
    monkeypatch.setenv("COM2_IDENTITY_AUTHORITY_FACTORY", "authority_factory:create_authority")
    with pytest.raises(RuntimeError):
        build_app()
    monkeypatch.setenv("COM2_IDENTITY_AUTHORITY_FACTORY", "com2_identity_do_proxy:create_authority")
    monkeypatch.setenv("COM2_IDENTITY_DB_PATH", str(tmp_path / "identity.sqlite"))
    with pytest.raises(RuntimeError):
        build_app()
    assert not (tmp_path / "identity.sqlite").exists()


def test_upstream_requires_https():
    for origin in ("http://identity.invalid", "https://user@identity.invalid", "https://identity.invalid/path"):
        with pytest.raises(ValueError):
            IdentityDoProxy(origin, SECRET)


@pytest.mark.asyncio
async def test_a_replay_refusal_is_retried_under_a_new_id():
    ids: list[str] = []

    def sender(url, body, headers):
        ids.append(headers[SERVICE_ID_HEADER])
        if len(ids) == 1:
            raise IdentityRpcReplayRefused("refused")
        return {"ok": True}

    proxy = IdentityDoProxy("https://identity.invalid", SECRET, sender=sender)
    assert await proxy.resolve_auth_session({"session_id": "synthetic"}) == {"ok": True}
    assert len(ids) == 2
    assert len(set(ids)) == 2


@pytest.mark.asyncio
async def test_a_target_that_keeps_refusing_is_bounded():
    ids: list[str] = []

    def sender(url, body, headers):
        ids.append(headers[SERVICE_ID_HEADER])
        raise IdentityRpcReplayRefused("refused")

    proxy = IdentityDoProxy("https://identity.invalid", SECRET, sender=sender)
    with pytest.raises(RuntimeError):
        await proxy.resolve_auth_session({"session_id": "synthetic"})
    assert len(ids) == RPC_MAX_ATTEMPTS
    assert len(set(ids)) == RPC_MAX_ATTEMPTS


@pytest.mark.parametrize(("status", "expected"), [(409, IdentityRpcReplayRefused), (500, RuntimeError)])
def test_only_a_replay_refusal_is_the_typed_error(status, expected):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/internal/rpc/resolve_auth_session"
        with pytest.raises(expected) as refused:
            IdentityDoProxy._send(url, b"{}", {})
        if status == 409:
            assert type(refused.value) is IdentityRpcReplayRefused
        else:
            # A plain failure is not a refusal: it must never be retried.
            assert type(refused.value) is RuntimeError
    finally:
        server.shutdown()
        thread.join(3)
        server.server_close()
