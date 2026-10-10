"""Fully offline tests for the single-call B14→local ExLab diagnostic."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "b14_exlab_direct_probe.py"
SPEC = importlib.util.spec_from_file_location("b14_exlab_direct_probe", MODULE_PATH)
assert SPEC and SPEC.loader
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)

SYNTH_KEY = "synthetic_test_abcdefghijklmnopqrstuvwxyz_12345678"


class Response:
    def __init__(self, status, data, headers=None):
        self.status_code = status
        self._data = data
        self.headers = headers or {}

    def json(self):
        return self._data


class FakeHttpx(types.ModuleType):
    class TimeoutException(Exception):
        pass

    class RequestError(Exception):
        pass

    def __init__(self, response=None, error=None):
        super().__init__("httpx")
        self.response = response
        self.error = error
        self.calls = []
        self.Timeout = lambda **kw: kw

    def Client(self, **kwargs):
        httpx = self

        class Client:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def post(self, url, *, headers, json):
                httpx.calls.append((url, headers, json))
                if httpx.error:
                    raise httpx.error
                return httpx.response

        return Client()


class ExlabProbeOfflineTests(unittest.TestCase):
    def test_dry_run_never_reads_key_or_sends(self):
        stdout = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), contextlib.redirect_stdout(stdout):
            exit_code = probe.main([])
        output = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(output["result"], "DRY_RUN_NO_NETWORK")
        self.assertEqual(output["calls_sent"], 0)

    def test_missing_credentials_stop_without_network(self):
        fake = FakeHttpx()
        with patch.dict(os.environ, {}, clear=True), patch.dict(sys.modules, {"httpx": fake}):
            result, code = probe.execute(True)
        self.assertEqual(code, 2)
        self.assertEqual(result["calls_sent"], 0)
        self.assertEqual(fake.calls, [])

    def test_success_is_single_call_with_exact_safe_payload_no_key_output(self):
        fake = FakeHttpx(Response(200, {
            "model": probe.MODEL,
            "choices": [{"message": {"content": "\nEXLAB_OK\n"}}],
        }))
        with patch.dict(os.environ, {probe.KEY_ENV: SYNTH_KEY}, clear=True), patch.dict(sys.modules, {"httpx": fake}):
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = probe.main(["--send"])
        result = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(result["result"], "PASS")
        self.assertEqual(result["calls_sent"], 1)
        self.assertEqual(result["retry_count"], 0)
        self.assertFalse(result["fallback_used"])
        self.assertEqual(len(fake.calls), 1)
        url, headers, payload = fake.calls[0]
        self.assertEqual(url, probe.URL)
        self.assertEqual(headers["Authorization"], "Bearer " + SYNTH_KEY)
        self.assertEqual(payload["model"], probe.MODEL)
        self.assertEqual(payload["messages"][0]["content"], probe.PROMPT)
        self.assertEqual(payload["max_tokens"], 32)
        self.assertFalse(payload["stream"])
        self.assertNotIn(SYNTH_KEY, stdout.getvalue())
        self.assertNotIn(probe.PROMPT, stdout.getvalue())

    def test_429_error_does_not_leak_vendor_body_or_key(self):
        fake = FakeHttpx(Response(
            429,
            {"error": {"code": "unavailable_route", "message": "internal " + SYNTH_KEY}},
            {"retry-after": "10"},
        ))
        with patch.dict(os.environ, {probe.KEY_ENV: SYNTH_KEY}, clear=True), patch.dict(sys.modules, {"httpx": fake}):
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = probe.main(["--send"])
        output = json.loads(stdout.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(output["classification"], "ROUTE_UNAVAILABLE")
        self.assertTrue(output["retry_after_present"])
        self.assertEqual(output["calls_sent"], 1)
        self.assertNotIn(SYNTH_KEY, stdout.getvalue())
        self.assertNotIn("internal", stdout.getvalue())
        self.assertNotIn("10", str(output.get("retry_after_present")))

    def test_503_deadline_exceeded_is_distinguished(self):
        fake = FakeHttpx(Response(503, {"error": {"code": "deadline_exceeded"}}))
        with patch.dict(os.environ, {probe.KEY_ENV: SYNTH_KEY}, clear=True), patch.dict(sys.modules, {"httpx": fake}):
            result, code = probe.execute(True)
        self.assertEqual(code, 1)
        self.assertEqual(result["http_status"], 503)
        self.assertEqual(result["vendor_code"], "deadline_exceeded")
        self.assertEqual(result["classification"], "PROVIDER_UNAVAILABLE_OR_DEADLINE")

    def test_transport_timeout_no_retry(self):
        fake = FakeHttpx(error=FakeHttpx.TimeoutException("private " + SYNTH_KEY))
        with patch.dict(os.environ, {probe.KEY_ENV: SYNTH_KEY}, clear=True), patch.dict(sys.modules, {"httpx": fake}):
            result, code = probe.execute(True)
        self.assertEqual(code, 1)
        self.assertEqual(result["result"], "UNKNOWN_DELIVERY_NO_AUTO_RETRY")
        self.assertEqual(len(fake.calls), 1)
        self.assertNotIn(SYNTH_KEY, str(result))

    def test_key_from_one_private_note_block_and_ambiguous_source(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "private-note.txt"
            path.write_text(
                "header\nhttps://platform.experientiallabs.ai/\n" + SYNTH_KEY + "\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {probe.NOTE_ENV: str(path)}, clear=True):
                self.assertEqual(probe._get_key(), SYNTH_KEY)
            with (patch.dict(os.environ, {probe.NOTE_ENV: str(path), probe.KEY_ENV: SYNTH_KEY}, clear=True),
                  self.assertRaises(probe.CredentialSourceError)):
                probe._get_key()
            path.write_text(
                "https://platform.experientiallabs.ai/\n" + SYNTH_KEY +
                "\nhttps://platform.experientiallabs.ai/\n" + SYNTH_KEY + "\n",
                encoding="utf-8",
            )
            with (patch.dict(os.environ, {probe.NOTE_ENV: str(path)}, clear=True),
                  self.assertRaises(probe.CredentialSourceError)):
                probe._get_key()


if __name__ == "__main__":
    unittest.main()
