"""#3580 Telegram SEND composition root tests.

Hermetic: the canonical sendDocument transport is bound to the existing
delivery adapter, and the HTTPS connection is patched so no Telegram call, bot
token exchange, provider-side effect or SEND authority is exercised.
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import test_telegram_artifact_delivery as tg

from kagent.artifact_delivery_execution_receipt import (
    ArtifactDeliveryReceipt, DeliveryTerminalStatus,
)
from kagent.telegram_document_send_composition import (
    LIVE_TELEGRAM_SEND_CANARY, PRODUCTION_ACTIVATION,
    TELEGRAM_DOCUMENT_SEND_COMPOSITION_ROOT_WIRED,
    TELEGRAM_SEND_COMPOSITION_CONTRACT_VERSION, TELEGRAM_SEND_COMPOSITION_PARAMETERS,
    TELEGRAM_SEND_COMPOSITION_CONSTRUCTION_PROVIDER_REQUESTS,
    TELEGRAM_SEND_COMPOSITION_CONSTRUCTION_TOKEN_RESOLUTIONS,
    TELEGRAM_SEND_GRANT_AUTHORIZED, TelegramDocumentSendComposition,
    TelegramSendCompositionError, build_telegram_document_send_composition,
)
from kagent.telegram_document_transport import StdlibTelegramDocumentSendPort


class FakeResponse:
    def __init__(self, status=200, body=None, content_type="application/json"):
        self.status = status
        self.body = (
            json.dumps({"ok": True, "result": {"message_id": 23}}).encode("utf-8")
            if body is None else body
        )
        self.content_type = content_type

    def read(self, max_bytes):
        return self.body[:max_bytes]

    def getheader(self, name):
        assert name == "content-type"
        return self.content_type


class FakeConnection:
    def __init__(self, response=None):
        self.response = response or FakeResponse()
        self.requests = []
        self.closed = False

    def request(self, method, path, body, headers):
        self.requests.append((method, path, body, headers))

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


def composition():
    return build_telegram_document_send_composition()


def delivery_adapter(built, **overrides):
    params = dict(
        scope=tg._scope(),
        trusted_binding=tg._FakeTrustedBinding(),
        artifact_material=tg._FakeMaterialResolver(tg._material()),
        channel_context=lambda: tg._context(),
        approval_authority=tg._FakeApprovalAuthority(),
        account_ref=tg.ACCOUNT_REF,
        actor_ref=tg.SENDER_REF,
        clock=lambda: tg.NOW,
    )
    params.update(overrides)
    return built.delivery_adapter(**params)


class TelegramDocumentSendCompositionTests(unittest.TestCase):
    def test_composition_root_is_wired_but_stays_unarmed(self):
        self.assertIs(TELEGRAM_DOCUMENT_SEND_COMPOSITION_ROOT_WIRED, True)
        built = composition()
        self.assertIs(built.armed, False)
        projection = built.safe_dict()
        self.assertEqual(projection["contract_version"],
                         TELEGRAM_SEND_COMPOSITION_CONTRACT_VERSION)
        self.assertIs(projection["armed"], False)
        self.assertIs(projection["production_claim"], False)
        self.assertIs(projection["telegram_send_grant_authorized"], False)
        self.assertIs(projection["live_telegram_send_canary"], False)
        self.assertEqual(projection["production_activation"], "BLOCKED")
        self.assertTrue(built.blocked_reasons)

    def test_blocked_reasons_name_the_actual_remaining_authority_gaps(self):
        reasons = " ".join(composition().blocked_reasons)
        self.assertIn("SEND grant is not authorized", reasons)
        self.assertIn("canary", reasons)
        self.assertIn("no production host", reasons)

    def test_construction_performs_no_provider_request_or_token_resolution(self):
        def _refuse(*args, **kwargs):  # pragma: no cover - must never run
            raise AssertionError("construction must not open a provider connection")

        with patch(
            "kagent.telegram_document_transport.http.client.HTTPSConnection", _refuse,
        ):
            built = build_telegram_document_send_composition()
        self.assertIsInstance(built.document_send, StdlibTelegramDocumentSendPort)
        self.assertEqual(TELEGRAM_SEND_COMPOSITION_CONSTRUCTION_PROVIDER_REQUESTS, 0)
        self.assertEqual(TELEGRAM_SEND_COMPOSITION_CONSTRUCTION_TOKEN_RESOLUTIONS, 0)

    def test_look_alike_transport_is_refused(self):
        with self.assertRaises(TelegramSendCompositionError):
            build_telegram_document_send_composition(document_send=object())
        with self.assertRaises(TelegramSendCompositionError):
            TelegramDocumentSendComposition(document_send=tg._FakeDocumentSend())

    def test_delivery_adapter_binds_the_canonical_composed_transport(self):
        built = composition()
        adapter = delivery_adapter(built)
        self.assertIs(adapter._document_send, built.document_send)

    def test_composed_canonical_transport_delivers_via_existing_adapter(self):
        built = composition()
        adapter = delivery_adapter(built)
        request = tg._request()
        conn = FakeConnection()

        with patch(
            "kagent.telegram_document_transport.http.client.HTTPSConnection",
            return_value=conn,
        ), patch(
            "kagent.telegram_document_transport.ssl.create_default_context",
            return_value=object(),
        ):
            receipt = adapter.deliver(request)

        self.assertIsInstance(receipt, ArtifactDeliveryReceipt)
        self.assertIs(receipt.terminal_status, DeliveryTerminalStatus.SUCCEEDED)
        self.assertEqual(receipt.external_side_effect_count, 1)
        self.assertEqual(receipt.retry_count, 0)
        self.assertTrue(receipt.correlates_with(request))

        # Exactly one physical sendDocument POST, carrying the canonical
        # artifact bytes and the resolved provider chat id.
        self.assertEqual(len(conn.requests), 1)
        method, path, body, headers = conn.requests[0]
        self.assertEqual(method, "POST")
        self.assertEqual(
            path, "/bot" + tg.PROVIDER_TOKEN.decode("ascii") + "/sendDocument",
        )
        self.assertIn("multipart/form-data; boundary=padiem", headers["content-type"])
        self.assertEqual(headers["content-length"], str(len(body)))
        self.assertIn(tg.DOCUMENT_BYTES, body)
        self.assertIn(b'filename="report.pdf"', body)
        self.assertIn(str(tg.PROVIDER_CHAT_ID).encode("ascii"), body)
        self.assertTrue(conn.closed)

    def test_projection_leaks_no_token_chat_id_or_artifact_bytes(self):
        rendered = json.dumps(composition().safe_dict(), ensure_ascii=False, sort_keys=True)
        self.assertNotIn(tg.PROVIDER_TOKEN.decode("ascii"), rendered)
        self.assertNotIn(str(tg.PROVIDER_CHAT_ID), rendered)
        self.assertNotIn(tg.DOCUMENT_BYTES.decode(), rendered)
        self.assertEqual(composition().safe_dict()["provider_host"], "api.telegram.org")
        self.assertEqual(composition().safe_dict()["document_send_port"],
                         "StdlibTelegramDocumentSendPort")

    def test_parameters_surface_is_pinned_as_data(self):
        self.assertEqual(TELEGRAM_SEND_COMPOSITION_PARAMETERS, ("document_send",))
        self.assertIs(TELEGRAM_SEND_GRANT_AUTHORIZED, False)
        self.assertIs(LIVE_TELEGRAM_SEND_CANARY, False)
        self.assertEqual(PRODUCTION_ACTIVATION, "BLOCKED")


if __name__ == "__main__":
    unittest.main()
