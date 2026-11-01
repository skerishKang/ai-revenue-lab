"""#6613 — what one TLS handshake per identity RPC costs, measured locally.

A password login issues six serial identity RPCs. Before this slice each one built
its own `httpx.AsyncClient`, so each paid a TCP+TLS handshake; the client is now
pooled per binding.

This starts one local HTTPS server (self-signed, loopback) and measures six serial
requests three ways:

* ``per-call client`` — the old shape: a fresh ``httpx.AsyncClient`` per request.
* ``pooled client``   — the new shape: one client, reused (what the binding does).
* ``HttpRpcBinding``  — the real binding, for the number that matters.

    python scripts/dev/benchmark_identity_rpc_keepalive_261102.py
"""
from __future__ import annotations

import asyncio
import datetime
import ipaddress
import json
import statistics
import ssl
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/padiem-chat"))

import httpx  # noqa: E402

SECRET = "benchmark-rpc-secret-0123456789abcdef"
RPCS = 6
RUNS = 5


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):                                     # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        self.rfile.read(length)
        body = json.dumps({"ok": True, "result": {"value": 1}}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):                           # keep the output clean
        pass


def _self_signed_cert(directory: Path) -> tuple[Path, Path]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName(
            [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
        .sign(key, hashes.SHA256())
    )
    key_path, cert_path = directory / "key.pem", directory / "cert.pem"
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return key_path, cert_path


def _serve(directory: Path):
    key_path, cert_path = _self_signed_cert(directory)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"https://127.0.0.1:{server.server_address[1]}"


async def per_call_client(origin: str) -> None:
    for _ in range(RPCS):
        async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
            await client.post(origin + "/internal/rpc/probe", json={})


async def pooled_client(origin: str) -> None:
    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        for _ in range(RPCS):
            await client.post(origin + "/internal/rpc/probe", json={})


async def real_binding(origin: str) -> None:
    from app.local_service_bridge import HttpRpcBinding
    binding = HttpRpcBinding(origin, SECRET, client=httpx.AsyncClient(
        timeout=30.0, follow_redirects=False, verify=False))
    for _ in range(RPCS):
        await binding.probe({})
    await binding.aclose()


def measure(label: str, shape, origin: str) -> str:
    samples = []
    for _ in range(RUNS):
        started = __import__("time").perf_counter()
        asyncio.run(shape(origin))
        samples.append((__import__("time").perf_counter() - started) * 1000.0)
    ordered = sorted(samples)
    return (f"{label:<20} {RPCS} rpc avg={statistics.fmean(samples):7.1f}ms "
            f"p50={statistics.median(samples):7.1f}ms max={ordered[-1]:7.1f}ms")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        server, origin = _serve(Path(tmp))
        try:
            before = measure("per-call client", per_call_client, origin)
            after = measure("pooled client", pooled_client, origin)
            real = measure("HttpRpcBinding", real_binding, origin)
        finally:
            server.shutdown()
    print("local TLS server, loopback, self-signed\n")
    print(before)
    print(after)
    print(real)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
