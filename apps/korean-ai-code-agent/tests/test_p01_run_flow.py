from __future__ import annotations

import asyncio
import io
import json
import os
from pathlib import Path
import unittest
from unittest import mock
import urllib.error

from padiem_ai_engine_client import EngineTransportResponse

from kagent import cli
from kagent.p01_adapter import P01AdapterError
from kagent.p01_run_flow import (
    ENV_ENGINE_BASE_URL,
    ENV_ENGINE_CALLER_ID,
    ENV_ENGINE_CREDENTIAL,
    P01EngineRuntimeConfig,
    UrllibEngineTransport,
    build_p01_orchestration_adapter,
    p01_adapter_from_environment,
    p01_config_from_environment,
)

from test_p01_orchestration_client import (
    _FAKE_CREDENTIAL,
    _build_request,
    _ok_transport,
    _public_result,
)


_FULL_ENV = {
    ENV_ENGINE_BASE_URL: "https://engine.example.test:8787",
    ENV_ENGINE_CALLER_ID: "b54-kagent",
    ENV_ENGINE_CREDENTIAL: _FAKE_CREDENTIAL,
}


class _FakeHttpResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body
        self.headers: dict[str, str] = {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeHttpResponse":
        return self

    def __exit__(self, *args: object) -> bool:
        return False


class P01EngineRuntimeConfigTests(unittest.TestCase):
    def test_missing_configuration_fails_closed_without_demo_fallback(self) -> None:
        with self.assertRaises(P01AdapterError) as ctx:
            p01_config_from_environment({})
        self.assertEqual(ctx.exception.code, "p01_engine_not_configured")
        self.assertIn(ENV_ENGINE_BASE_URL, ctx.exception.safe_message)

    def test_partial_configuration_names_missing_settings(self) -> None:
        env = {ENV_ENGINE_BASE_URL: "https://engine.example.test"}
        with self.assertRaises(P01AdapterError) as ctx:
            p01_config_from_environment(env)
        self.assertEqual(ctx.exception.code, "p01_engine_misconfigured")
        self.assertIn(ENV_ENGINE_CREDENTIAL, ctx.exception.safe_message)
        self.assertNotIn(_FAKE_CREDENTIAL, ctx.exception.safe_message)

    def test_invalid_base_url_is_rejected(self) -> None:
        with self.assertRaises(P01AdapterError) as ctx:
            P01EngineRuntimeConfig(
                base_url="not a url",
                caller_id="b54-kagent",
                credential=_FAKE_CREDENTIAL,
            )
        self.assertEqual(ctx.exception.code, "p01_engine_misconfigured")

    def test_base_url_with_credentials_is_rejected(self) -> None:
        with self.assertRaises(P01AdapterError):
            P01EngineRuntimeConfig(
                base_url="https://user:pass@engine.example.test",
                caller_id="b54-kagent",
                credential=_FAKE_CREDENTIAL,
            )

    def test_short_credential_is_rejected_without_leaking_value(self) -> None:
        secret = "sh0rt-credential-value"
        with self.assertRaises(P01AdapterError) as ctx:
            P01EngineRuntimeConfig(
                base_url="https://engine.example.test",
                caller_id="b54-kagent",
                credential=secret,
            )
        self.assertEqual(ctx.exception.code, "p01_engine_misconfigured")
        self.assertNotIn(secret, ctx.exception.safe_message)

    def test_client_contract_rejection_is_wrapped_as_misconfigured(self) -> None:
        config = P01EngineRuntimeConfig(
            base_url="https://engine.example.test",
            caller_id="bad/caller/id/with/slash",
            credential=_FAKE_CREDENTIAL,
        )
        with self.assertRaises(P01AdapterError) as ctx:
            build_p01_orchestration_adapter(
                config, transport=_ok_transport({"ok": True})
            )
        self.assertEqual(ctx.exception.code, "p01_engine_misconfigured")


class UrllibEngineTransportTests(unittest.TestCase):
    def test_map_url_rewrites_internal_origin_to_configured_base(self) -> None:
        transport = UrllibEngineTransport("https://engine.example.test:8787/")
        self.assertEqual(
            transport.map_url("https://padiem-ai-engine.internal/internal/v1/orchestrate"),
            "https://engine.example.test:8787/internal/v1/orchestrate",
        )

    def test_map_url_refuses_foreign_origin(self) -> None:
        transport = UrllibEngineTransport("https://engine.example.test")
        with self.assertRaises(P01AdapterError) as ctx:
            transport.map_url("https://evil.example/internal/v1/orchestrate")
        self.assertEqual(ctx.exception.code, "p01_engine_url_invalid")

    def test_request_sends_to_mapped_url_with_headers(self) -> None:
        transport = UrllibEngineTransport("https://engine.example.test:8787")
        captured: dict = {}

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["method"] = request.method
            captured["headers"] = dict(request.headers)
            captured["body"] = request.data
            captured["timeout"] = timeout
            return _FakeHttpResponse(200, b'{"ok": true}')

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            response = asyncio.run(
                transport.request(
                    method="POST",
                    url="https://padiem-ai-engine.internal/internal/v1/orchestrate",
                    headers={"Content-Type": "application/json"},
                    body=b"{}",
                )
            )
        self.assertEqual(response.status, 200)
        self.assertEqual(response.body, b'{"ok": true}')
        self.assertEqual(
            captured["url"], "https://engine.example.test:8787/internal/v1/orchestrate"
        )
        self.assertEqual(captured["method"], "POST")

    def test_http_error_status_is_passed_through_for_the_client(self) -> None:
        transport = UrllibEngineTransport("https://engine.example.test")
        error = urllib.error.HTTPError(
            "https://engine.example.test/internal/v1/orchestrate",
            429,
            "Too Many Requests",
            {},  # type: ignore[arg-type]
            io.BytesIO(b'{"ok": false}'),
        )
        with mock.patch("urllib.request.urlopen", side_effect=error):
            response = asyncio.run(
                transport.request(
                    method="POST",
                    url="https://padiem-ai-engine.internal/internal/v1/orchestrate",
                    headers={},
                    body=b"{}",
                )
            )
        self.assertEqual(response.status, 429)
        self.assertEqual(response.body, b'{"ok": false}')

    def test_connection_failure_fails_closed_as_unreachable(self) -> None:
        transport = UrllibEngineTransport("https://engine.example.test")
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            with self.assertRaises(P01AdapterError) as ctx:
                asyncio.run(
                    transport.request(
                        method="POST",
                        url="https://padiem-ai-engine.internal/internal/v1/orchestrate",
                        headers={},
                        body=b"{}",
                    )
                )
        self.assertEqual(ctx.exception.code, "p01_engine_unreachable")


class P01CliRunFlowTests(unittest.TestCase):
    def test_cli_p01_run_fails_closed_without_configuration(self) -> None:
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch("sys.stdout", stdout), mock.patch("sys.stderr", stderr):
                code = cli.main([".", "p01-run", "P01 오케스트레이션 포트를 검증해줘"])
        self.assertEqual(code, 2)
        self.assertIn("p01_engine_not_configured", stderr.getvalue())
        self.assertNotIn("[B14 MOCK ADAPTER]", stdout.getvalue())

    def test_cli_p01_run_completes_over_the_engine_port(self) -> None:
        run, request = _build_request()
        transport = _ok_transport(_public_result(request))
        adapter = build_p01_orchestration_adapter(
            P01EngineRuntimeConfig(
                base_url="https://engine.example.test:8787",
                caller_id="b54-kagent",
                credential=_FAKE_CREDENTIAL,
            ),
            transport=transport,
        )
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdout", stdout), mock.patch("sys.stderr", stderr):
            code = cli.main(
                [
                    ".",
                    "p01-run",
                    "P01 오케스트레이션 포트를 검증해줘",
                    "--run-id",
                    run.run_id,
                ],
                adapter=adapter,
            )
        self.assertEqual(code, 0, stderr.getvalue())
        printed = stdout.getvalue()
        self.assertIn("[P01 ORCHESTRATION]", printed)
        self.assertIn("status=completed", printed)
        self.assertIn("완료 답변", printed)
        self.assertNotIn("[B14 MOCK ADAPTER]", printed)
        self.assertNotIn(_FAKE_CREDENTIAL, printed)
        self.assertEqual(
            transport.requests[0]["url"],
            "https://padiem-ai-engine.internal/internal/v1/orchestrate",
        )

    def test_adapter_from_environment_uses_settings_without_hardcoding(self) -> None:
        adapter = p01_adapter_from_environment(_FULL_ENV, transport=_ok_transport({}))
        self.assertIsNotNone(adapter)

    def test_explicit_run_id_must_use_run_prefix(self) -> None:
        stderr = io.StringIO()
        with mock.patch("sys.stderr", stderr):
            code = cli.main(
                [".", "p01-run", "작업", "--run-id", "oops"],
                adapter=p01_adapter_from_environment(_FULL_ENV, transport=_ok_transport({})),
            )
        self.assertEqual(code, 2)
        self.assertIn("p01_run_id_invalid", stderr.getvalue())

    def test_repository_default_is_current_directory(self) -> None:
        parsed = cli.parser().parse_args([".", "p01-run", "작업"])
        self.assertEqual(parsed.repository, ".")
        self.assertEqual(Path(parsed.repository).name or ".", ".")


if __name__ == "__main__":
    unittest.main()
