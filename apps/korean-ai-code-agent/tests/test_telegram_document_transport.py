"""Hermetic sendDocument multipart transport tests (#3901 / #3580).

Patch the HTTPS connection before any invocation: no actual Telegram call, bot
token exchange, provider-side effect or Production SEND authority is exercised.
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from kagent.contracts import ContractError
from kagent.telegram_artifact_delivery import TelegramDocumentSendPort
from kagent.telegram_bot_runtime import MAX_BOT_API_RESPONSE_BYTES, TELEGRAM_API_HOST
from kagent.telegram_contracts import MAX_TELEGRAM_FILE_BYTES
from kagent.telegram_document_transport import (
    PRODUCTION_TELEGRAM_SEND_ACTIVATED,
    StdlibTelegramDocumentSendPort,
)


TOKEN = b"123456789:ABCDEFghijklmNOPQRstuvwx"
FILE_BYTES = b"%PDF-1.7\nfake printable document\n%%EOF\n"


class FakeResponse:
    def __init__(self, status=200, body=None, content_type="application/json"):
        self.status = status
        self.body = (json.dumps({"ok": True, "result": {"message_id": 23}}).encode("utf-8")
                     if body is None else body)
        self.content_type = content_type
        self.read_limits = []

    def read(self, max_bytes):
        self.read_limits.append(max_bytes)
        return self.body[:max_bytes]

    def getheader(self, name):
        assert name == "content-type"
        return self.content_type


class FakeConnection:
    def __init__(self, response=None, error=None):
        self.response = response or FakeResponse()
        self.error = error
        self.requests = []
        self.closed = False

    def request(self, method, path, body, headers):
        self.requests.append((method, path, body, headers))
        if self.error:
            raise self.error

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class TelegramDocumentTransportTests(unittest.TestCase):
    def setUp(self):
        self.port = StdlibTelegramDocumentSendPort()

    def invoke(self, conn, **overrides):
        values = dict(
            token=TOKEN, provider_chat_id=-1001234567890,
            document_bytes=FILE_BYTES, filename="견적서.pdf",
            mime_type="application/pdf", timeout_seconds=30,
        )
        values.update(overrides)
        with patch(
            "kagent.telegram_document_transport.http.client.HTTPSConnection",
            return_value=conn,
        ) as ctor, patch(
            "kagent.telegram_document_transport.ssl.create_default_context",
            return_value=object(),
        ):
            result = self.port.send_document(**values)
        return result, ctor

    def test_protocol_and_source_are_not_production_activation(self):
        self.assertIsInstance(self.port, TelegramDocumentSendPort)
        self.assertFalse(PRODUCTION_TELEGRAM_SEND_ACTIVATED)
        self.assertEqual(len(FakeConnection().requests), 0)

    def test_multipart_contains_exact_document_chat_id_and_utf8_filename(self):
        conn = FakeConnection()
        result, ctor = self.invoke(conn)
        self.assertTrue(result["ok"])
        ctor.assert_called_once()
        self.assertEqual(ctor.call_args.args[0], TELEGRAM_API_HOST)
        self.assertEqual(ctor.call_args.kwargs["port"], 443)
        self.assertEqual(ctor.call_args.kwargs["timeout"], 30)
        self.assertEqual(len(conn.requests), 1)
        method, path, body, headers = conn.requests[0]
        self.assertEqual(method, "POST")
        self.assertTrue(path.startswith("/bot") and path.endswith("/sendDocument"))
        self.assertIn(TOKEN.decode("ascii"), path)
        self.assertEqual(headers["accept"], "application/json")
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertEqual(headers["content-length"], str(len(body)))
        boundary = headers["content-type"].split("boundary=", 1)[1].encode("ascii")
        self.assertTrue(body.startswith(b"--" + boundary + b"\r\n"))
        self.assertTrue(body.endswith(b"\r\n--" + boundary + b"--\r\n"))
        self.assertIn(b'name="chat_id"\r\n\r\n-1001234567890\r\n', body)
        self.assertIn(b'name="document"; filename="' + "견적서.pdf".encode() + b'"', body)
        self.assertIn(b"Content-Type: application/pdf\r\n\r\n" + FILE_BYTES + b"\r\n--", body)
        self.assertEqual(body.count(FILE_BYTES), 1)
        self.assertTrue(conn.closed)
        self.assertEqual(conn.response.read_limits, [MAX_BOT_API_RESPONSE_BYTES + 1])

    def test_positive_and_negative_provider_chat_id_allowed(self):
        for chat_id in (123456789, -100222333444):
            conn = FakeConnection()
            result, _ = self.invoke(conn, provider_chat_id=chat_id)
            self.assertTrue(result["ok"])
            self.assertIn(str(chat_id).encode("ascii"), conn.requests[0][2])

    def test_provider_refusal_envelope_is_passed_to_existing_adapter(self):
        response = FakeResponse(
            status=429,
            body=json.dumps({"ok": False, "error_code": 429,
                             "description": "rate-limited",
                             "parameters": {"retry_after": 15}}).encode(),
        )
        result, _ = self.invoke(FakeConnection(response))
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], 429)
        self.assertEqual(result["parameters"]["retry_after"], 15)

    def test_bounded_non_json_503_returns_reusable_retryable_code(self):
        response = FakeResponse(status=503, body=b"<html>provider details</html>",
                                content_type="text/html")
        result, _ = self.invoke(FakeConnection(response))
        self.assertEqual(result, {"ok": False, "error_code": 503, "description": ""})
        self.assertNotIn("provider details", str(result))

    def test_invalid_json_500_returns_bounded_error_without_body(self):
        result, _ = self.invoke(FakeConnection(
            FakeResponse(status=500, body=b"{bad-provider-body}")
        ))
        self.assertEqual(result, {"ok": False, "error_code": 500, "description": ""})

    def test_redirect_never_followed_and_closes_socket(self):
        conn = FakeConnection(FakeResponse(status=302, body=b"moved"))
        with self.assertRaisesRegex(ContractError, "redirect"):
            self.invoke(conn)
        self.assertEqual(len(conn.requests), 1)
        self.assertTrue(conn.closed)

    def test_json_success_requires_valid_envelope(self):
        for body, content_type in (
            (b"{not-json", "application/json"),
            (b"[]", "application/json"),
            (b'{"ok":"true"}', "application/json"),
            (b"<html>not-json</html>", "text/html"),
        ):
            conn = FakeConnection(FakeResponse(body=body, content_type=content_type))
            with self.assertRaises(ContractError):
                self.invoke(conn)
            self.assertEqual(len(conn.requests), 1)
            self.assertTrue(conn.closed)

    def test_bounded_provider_response_refuses_oversized_bytes(self):
        conn = FakeConnection(FakeResponse(body=b"x" * (MAX_BOT_API_RESPONSE_BYTES + 10)))
        with self.assertRaisesRegex(ContractError, "exceeds source bound"):
            self.invoke(conn)
        self.assertTrue(conn.closed)

    def test_network_error_message_cannot_leak_token_or_provider_url(self):
        error = OSError("request to /botSECRET-TOKEN/sendDocument failed")
        conn = FakeConnection(error=error)
        with self.assertRaises(OSError) as ctx:
            self.invoke(conn)
        self.assertEqual(str(ctx.exception), "Telegram document transport unavailable")
        self.assertNotIn("SECRET-TOKEN", str(ctx.exception))
        self.assertEqual(len(conn.requests), 1)
        self.assertTrue(conn.closed)

    def test_filename_header_injection_path_and_unicode_invalid(self):
        for name in ("", "../quote.pdf", "dir\\quote.pdf", 'evil".pdf',
                     "quote\r\nX: injected.pdf", " x.pdf ", ".", "..",
                     "\ud800.pdf", "가" * 100):
            conn = FakeConnection()
            with self.assertRaises(ContractError, msg=repr(name)):
                self.invoke(conn, filename=name)
            self.assertEqual(conn.requests, [])
            self.assertFalse(conn.closed)

    def test_mime_header_injection_refused(self):
        for mime in ("", "application/pdf\r\nInjected: yes",
                     "application/pdf; charset=utf-8", "not-a-mime"):
            conn = FakeConnection()
            with self.assertRaises(ContractError):
                self.invoke(conn, mime_type=mime)
            self.assertEqual(conn.requests, [])

    def test_token_chat_timeout_and_document_shape_refused_pre_network(self):
        overrides = [
            {"token": b"x"}, {"token": "not-bytes"},
            {"provider_chat_id": True}, {"provider_chat_id": "123"},
            {"timeout_seconds": 0}, {"timeout_seconds": True},
            {"document_bytes": b""}, {"document_bytes": "not bytes"},
            {"document_bytes": b"x" * (MAX_TELEGRAM_FILE_BYTES + 1)},
        ]
        for opts in overrides:
            conn = FakeConnection()
            with self.assertRaises(ContractError, msg=str(opts.keys())):
                self.invoke(conn, **opts)
            self.assertEqual(conn.requests, [])

    def test_http_200_ok_true_conflicting_http_error_refused(self):
        conn = FakeConnection(FakeResponse(status=401))
        with self.assertRaisesRegex(ContractError, "disagree"):
            self.invoke(conn)
        self.assertTrue(conn.closed)

    def test_http_200_missing_result_is_refused_by_existing_adapter(self):
        # Transport preserves bounded provider envelope; the adapter owns the
        # result.message_id integrity validation, not this transport.
        result, _ = self.invoke(
            FakeConnection(FakeResponse(body=b'{"ok":true,"result":{}}'))
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"], {})


if __name__ == "__main__":
    unittest.main()
