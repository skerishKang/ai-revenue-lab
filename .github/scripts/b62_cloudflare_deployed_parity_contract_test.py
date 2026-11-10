#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import b62_cloudflare_deployed_parity as parity

_REPO_ROOT = Path(__file__).resolve().parents[2]


class MethodAwareParityTest(unittest.TestCase):
    def test_every_shipped_chat_module_is_a_parity_asset(self) -> None:
        """R5 0단계(0-2): static의 chat-*-module.js는 전부 일치 검사 대상이다."""
        public_paths = {public_path for _, public_path, _ in parity.ASSETS}
        modules = sorted((_REPO_ROOT / "apps/padiem-chat/static").glob("chat-*-module.js"))
        assert modules, "chat-*-module.js 자산이 static에 있어야 한다"
        for module in modules:
            assert f"/{module.name}" in public_paths, module.name

    def test_invalid_post_422_proves_b62_route(self) -> None:
        calls: list[str] = []

        def poster(url: str) -> parity.HTTPResult:
            calls.append(url)
            return parity.HTTPResult(
                422,
                {"content-type": "application/json"},
                json.dumps({"error": {"code": "invalid_request", "message": "bad request"}}).encode(),
            )

        present, status, code = parity.stream_route_probe(
            base_url="https://padiem-chat.example.workers.dev",
            poster=poster,
        )
        self.assertTrue(present)
        self.assertEqual(status, 422)
        self.assertEqual(code, "invalid_request")
        self.assertEqual(len(calls), 1)

    def test_wrong_422_signature_is_rejected(self) -> None:
        def poster(url: str) -> parity.HTTPResult:
            return parity.HTTPResult(
                422,
                {"content-type": "application/json"},
                json.dumps({"error": {"code": "streaming_unsupported"}}).encode(),
            )

        with self.assertRaises(parity.AuditError):
            parity.stream_route_probe(
                base_url="https://padiem-chat.example.workers.dev",
                poster=poster,
            )

    def test_audit_is_ready_with_b62_get_404_and_invalid_post_422(self) -> None:
        # R5 0단계(0-2): 분리 모듈(chat-*-module.js)도 자산 일치 대상이다.
        bodies = {
            "/app.js": b"app",
            "/search-sources.js": b"search",
            "/rich-response.js": b"rich",
            **{
                public_path: f"module:{public_path}".encode()
                for _, public_path, _ in parity.ASSETS
                if public_path.startswith("/chat-")
            },
        }

        def fetcher(url: str) -> parity.HTTPResult:
            for suffix, body in bodies.items():
                if url.endswith(suffix):
                    return parity.HTTPResult(200, {}, body)
            if url.endswith(parity.B62_STREAM_PATH):
                return parity.HTTPResult(404, {}, b"")
            # The retired Cloudflare B14 Worker is no longer probed: any other
            # GET is unexpected.
            raise AssertionError(f"unexpected GET {url}")

        def poster(url: str) -> parity.HTTPResult:
            self.assertTrue(url.endswith(parity.B62_STREAM_PATH))
            return parity.HTTPResult(
                422,
                {"content-type": "application/json"},
                b'{"error":{"code":"invalid_request","message":"bad request"}}',
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for _, public_path, relative_path in parity.ASSETS:
                target = root / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(bodies[public_path])

            result = parity.audit(
                base_url="https://padiem-chat.example.workers.dev",
                repo_root=root,
                fetcher=fetcher,
                poster=poster,
            )

        self.assertEqual(result.stream_get_status, 404)
        self.assertEqual(result.stream_probe_status, 422)
        self.assertEqual(result.stream_probe_error_code, "invalid_request")
        self.assertTrue(result.stream_route_present)
        self.assertTrue(result.b62_ready)
        self.assertTrue(result.ready)

    def test_post_404_keeps_surface_on_hold(self) -> None:
        def poster(url: str) -> parity.HTTPResult:
            return parity.HTTPResult(404, {}, b"")

        present, status, code = parity.stream_route_probe(
            base_url="https://padiem-chat.example.workers.dev",
            poster=poster,
        )
        self.assertFalse(present)
        self.assertEqual(status, 404)
        self.assertIsNone(code)


if __name__ == "__main__":
    unittest.main()
