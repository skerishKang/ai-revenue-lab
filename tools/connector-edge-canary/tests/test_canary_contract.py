"""Fast offline proof: canary cannot grant authority, even when TLS is OK."""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class FakeResponse:
    def __init__(self, body, *, status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = headers or {}


async def fake_websocket(application, request):
    assert callable(application)
    assert request is not None
    return "SDK_TWO_ARG_WSS"


sdk = types.ModuleType("workers")
sdk.Response = FakeResponse
sdk.WorkerEntrypoint = object
sdk.asgi = types.SimpleNamespace(websocket=fake_websocket)
with patch.dict(sys.modules, {"workers": sdk}):
    spec = importlib.util.spec_from_file_location("isolated_connector_canary", ROOT / "worker.py")
    assert spec is not None and spec.loader is not None
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)


def request(url="https://canary.invalid/__padiem_canary/tls", *,
            version="TLSv1.3", cf=True, headers=None, method="GET"):
    r = types.SimpleNamespace(
        url=url, method=method, headers=headers or {},
    )
    if cf:
        r.cf = types.SimpleNamespace(tlsVersion=version)
    return r


class IsolatedCanaryContracts(unittest.TestCase):
    def call(self, req):
        with patch.dict(sys.modules, {"workers": sdk}):
            return asyncio.run(worker.Default().fetch(req))

    def test_tls_allowlisted_only(self):
        for v in ("TLSv1.2", "TLSv1.3"):
            result = self.call(request(version=v))
            self.assertEqual(result.status, 200)
            self.assertEqual(result.body, "TLS_OK")
            self.assertEqual(result.headers.get("cache-control"), "no-store")

    def test_cf_absent_fails_closed(self):
        self.assertEqual(self.call(request(cf=False)).status, 503)
        self.assertEqual(self.call(request(cf=False)).body, "CF_UNAVAILABLE")

    def test_missing_or_old_tls_fails_closed(self):
        for v in (None, "TLSv1.0", "TLSv1.1", "SSLv3", "", False):
            with self.subTest(v=v):
                self.assertEqual(self.call(request(version=v)).status, 503)

    def test_tampered_method_query_host_and_path(self):
        for bad in (
            request(method="POST"),
            request(url="https://canary.invalid/__padiem_canary/tls?token=leak"),
            request(url="https://canary.invalid/other"),
        ):
            self.assertEqual(self.call(bad).status, 404)

    def test_wss_requires_tls_before_upgrade(self):
        endpoint = "https://canary.invalid/__padiem_canary/wss"
        self.assertEqual(self.call(request(endpoint, cf=False)).status, 403)
        self.assertEqual(self.call(request(endpoint, version="TLSv1.0")).status, 403)
        self.assertEqual(self.call(request(endpoint)).status, 426)

    def test_wss_ignores_forwarded_tls_claim_and_refuses_browser_authority(self):
        endpoint = "https://canary.invalid/__padiem_canary/wss"
        for headers in (
            {"upgrade":"websocket","cookie":"signed-forged"},
            {"upgrade":"websocket","authorization":"Bearer forged"},
            {"upgrade":"websocket","origin":"https://attacker.invalid"},
            {"upgrade":"websocket","sec-websocket-protocol":"token"},
        ):
            self.assertEqual(self.call(request(endpoint, headers=headers)).status, 403)
        self.assertEqual(
            self.call(request(endpoint, cf=False, headers={
                "upgrade":"websocket", "x-forwarded-proto":"https"
            })).status, 403,
        )

    def test_strict_sdk_two_arg_websocket(self):
        endpoint = "https://canary.invalid/__padiem_canary/wss"
        value = self.call(request(endpoint, headers={"upgrade":"websocket"}))
        self.assertEqual(value, "SDK_TWO_ARG_WSS")

    def test_frame_roundtrip_without_credentials(self):
        received = iter((
            {"type":"websocket.connect"},
            {"type":"websocket.receive", "text":"PADIEM_CANARY_NO_SECRET_PING"},
        ))
        sent = []

        async def recv():
            return next(received)

        async def send(msg):
            sent.append(msg)

        asyncio.run(worker._socket_app(
            {"type":"websocket", "path":"/__padiem_canary/wss"}, recv, send
        ))
        self.assertEqual([x["type"] for x in sent], [
            "websocket.accept", "websocket.send", "websocket.send", "websocket.close",
        ])
        self.assertEqual(sent[2]["text"], "PADIEM_CANARY_PONG")
        self.assertNotIn("device", str(sent).lower())


if __name__ == "__main__":
    unittest.main()
