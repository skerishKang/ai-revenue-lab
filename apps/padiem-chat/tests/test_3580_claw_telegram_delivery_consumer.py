"""#3580 Telegram artifact delivery consumer route tests.

Real SQLite migrations (026 + 036), real D1-style bindings, real Starlette
routing and session auth. Only the trusted host seams — the delivery adapter,
the request builder and the provider — are hermetic doubles. No Telegram call,
no token, no grant and no Production binding is exercised.
"""
from __future__ import annotations

import asyncio
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.claw_artifact_delivery_receipt_store import (
    D1ArtifactDeliveryReceiptStore, InMemoryArtifactDeliveryReceiptStore,
)
from app.history import D1HistoryStore
from kagent.artifact_delivery_execution_receipt import (
    ArtifactDeliveryExecutionRequest, DeliveryTerminalStatus, build_delivery_receipt,
)
from kagent.artifact_delivery_intent import DeliveryKind

from test_3929_claw_conversation_artifact_d1 import (
    CHAT, D1Sqlite, FOREIGN, FOREIGN_CHAT, MIGRATIONS, OTHER_WORKSPACE, OWNER,
    RUN, RUN2, WORKSPACE, canonical, setup_database,
)
import test_b54_claw_general_p01_routing as base

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
CHANNEL_REF = "tcr1_" + "9" * 64
BINDING_REF = "binding_telegram_consumer"
APPROVAL_REF = "approval_telegram_consumer"


class FakeAdapter:
    """Hermetic stand-in for the existing connector-owned delivery adapter."""

    def __init__(self, *, status=DeliveryTerminalStatus.SUCCEEDED, error=None):
        self.status = status
        self.error = error
        self.calls = []

    def deliver(self, request, *, now=None):
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return build_delivery_receipt(
            receipt_ref="tgdr" + "a" * 32, request=request,
            terminal_status=self.status, started_at=NOW, completed_at=NOW,
            external_side_effect_count=(
                1 if self.status is DeliveryTerminalStatus.SUCCEEDED else 0
            ),
        )


def request_for(artifact_ref, *, workspace=WORKSPACE, run=RUN):
    return ArtifactDeliveryExecutionRequest(
        attempt_ref="tgdlv" + "b" * 32, delivery_intent_id="tgint" + "c" * 32,
        artifact_ref=artifact_ref, delivery_kind=DeliveryKind.EXTERNAL_CONNECTOR,
        trusted_channel_ref=CHANNEL_REF, workspace_ref=workspace, run_ref=run,
        requested_at=NOW, channel_binding_ref=BINDING_REF,
        approval_ref=APPROVAL_REF,
    )


class _ConsumerHarness(unittest.TestCase):
    """Shared harness; concrete classes below keep pytest collection simple."""

    def setUp(self):
        self.db = setup_database()
        self.db.executescript(
            (MIGRATIONS / "036_claw_artifact_delivery_receipts.sql")
            .read_text(encoding="utf8")
        )
        self.db.commit()
        self.history = D1HistoryStore(D1Sqlite(self.db))
        self.record = canonical()
        self.store = D1ArtifactDeliveryReceiptStore(D1Sqlite(self.db))

    def tearDown(self):
        self.db.close()

    async def register(self, record=None):
        item = record if record is not None else self.record
        return await self.history.register_owner_conversation_artifact(
            user_id=OWNER, conversation_id=CHAT, workspace_ref=WORKSPACE,
            artifact=item,
        )

    def post(self, *, adapter, builder=None, store=None, owner=OWNER,
             conversation=CHAT, artifact=None, tenant=WORKSPACE, reader=True):
        async def canonical_workspace(_):
            return tenant

        if builder is None:
            builder = lambda **kwargs: request_for(kwargs["artifact_ref"])
        app = create_app(
            settings=base._settings(), history_store=self.history,
            claw_telegram_artifact_delivery=adapter,
            claw_artifact_delivery_receipt_store=(
                store if store is not None else self.store
            ),
            claw_telegram_delivery_request_builder=builder if reader else None,
        )
        with patch(
            "app.claw_telegram_delivery_routes._resolve_canonical_tenant",
            canonical_workspace,
        ):
            with TestClient(app, base_url="https://chat.example.test") as client:
                client.cookies.set(
                    SESSION_COOKIE,
                    create_session_token(base._settings(), owner),
                    domain="chat.example.test", path="/",
                )
                return client.post(
                    "/api/claw/conversations/"
                    f"{conversation}/artifacts/{artifact or self.record.artifact_id}"
                    "/telegram"
                )


class TestTelegramDeliveryConsumerRoute(_ConsumerHarness):
    def test_unauthenticated_is_refused(self):
        adapter = FakeAdapter()
        app = create_app(
            settings=base._settings(), history_store=self.history,
            claw_telegram_artifact_delivery=adapter,
        )
        with TestClient(app, base_url="https://chat.example.test") as client:
            response = client.post(
                "/api/claw/conversations/"
                f"{CHAT}/artifacts/{self.record.artifact_id}/telegram"
            )
        assert response.status_code == 401
        assert adapter.calls == []

    def test_invalid_conversation_or_artifact_id_is_refused(self):
        adapter = FakeAdapter()
        assert self.post(
            adapter=adapter, conversation="not-a-conversation"
        ).status_code == 400
        assert self.post(adapter=adapter, artifact="!!bad!!").status_code == 400
        assert adapter.calls == []

    def test_no_trusted_seam_refuses_without_any_provider_path(self):
        adapter = FakeAdapter()
        assert self.post(adapter=None).status_code == 403
        assert self.post(adapter=adapter, reader=False).status_code == 403
        assert self.post(
            adapter=adapter, store=object()
        ).status_code == 403
        assert adapter.calls == []

    def test_foreign_owner_cannot_select_the_artifact(self):
        assert asyncio.run(self.register()) is True
        adapter = FakeAdapter()
        response = self.post(adapter=adapter, owner=FOREIGN, conversation=FOREIGN_CHAT)
        assert response.status_code == 404
        assert adapter.calls == []

    def test_wrong_workspace_cannot_select_the_artifact(self):
        assert asyncio.run(self.register()) is True
        adapter = FakeAdapter()
        response = self.post(adapter=adapter, tenant=OTHER_WORKSPACE)
        assert response.status_code == 404
        assert adapter.calls == []

    def test_unregistered_artifact_is_not_found(self):
        adapter = FakeAdapter()
        assert self.post(adapter=adapter).status_code == 404
        assert adapter.calls == []

    def test_index_cannot_hold_a_non_deliverable_artifact(self):
        # The existing index constraint is the primary guard; the route's own
        # allowlist is defence in depth and must match it exactly.
        import sqlite3

        import pytest as _pytest

        from app.claw_telegram_delivery_routes import (
            _DELIVERABLE_MEDIA_TYPES, _PDF, _XLSX,
        )

        with _pytest.raises(sqlite3.IntegrityError):
            self.db.execute(
                "INSERT INTO claw_conversation_artifact_index "
                "(artifact_id, user_id, conversation_id, workspace_ref, source_run_ref, "
                "filename, media_type, size_bytes, integrity_ref, location_kind, "
                "location_ref, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                ("artifact_text_consumer", OWNER, CHAT, WORKSPACE, RUN, "note.txt",
                 "text/plain", 10, "a" * 64, "google_drive", "ref", "2026-10-11"),
            )
        assert set(_DELIVERABLE_MEDIA_TYPES) == {_PDF, _XLSX}

    def test_missing_send_approval_is_refused_without_adapter_call(self):
        assert asyncio.run(self.register()) is True
        adapter = FakeAdapter()
        response = self.post(adapter=adapter, builder=lambda **kwargs: None)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "send_approval_unavailable"
        assert adapter.calls == []

    def test_successful_delivery_records_receipt_and_never_sends_twice(self):
        assert asyncio.run(self.register()) is True
        adapter = FakeAdapter()
        first = self.post(adapter=adapter)
        assert first.status_code == 200, first.text
        body = first.json()
        assert body["ok"] is True
        assert body["delivered"] is True
        assert body["receipt"]["terminal_status"] == "succeeded"
        assert body["receipt"]["external_side_effect_count"] == 1
        assert CHANNEL_REF not in first.text
        assert len(adapter.calls) == 1

        second = self.post(adapter=adapter)
        assert second.status_code == 200
        assert second.json()["delivered"] is False
        assert second.json()["reason"] == "already_delivered"
        assert len(adapter.calls) == 1

    def test_failed_delivery_is_truthful_and_never_retried(self):
        assert asyncio.run(self.register()) is True
        adapter = FakeAdapter(status=DeliveryTerminalStatus.FAILED_TERMINAL)
        first = self.post(adapter=adapter)
        assert first.status_code == 502
        assert first.json()["ok"] is False
        assert first.json()["delivered"] is False
        assert first.json()["error"]["code"] == "delivery_not_completed"
        assert len(adapter.calls) == 1
        second = self.post(adapter=adapter)
        assert second.json()["reason"] == "already_delivered"
        assert len(adapter.calls) == 1

    def test_refused_delivery_is_reported_as_a_refusal(self):
        assert asyncio.run(self.register()) is True
        adapter = FakeAdapter(status=DeliveryTerminalStatus.REFUSED)
        response = self.post(adapter=adapter)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "delivery_refused"
        assert response.json()["receipt"]["terminal_class"] == "refusal"

    def test_adapter_exception_records_terminal_failure_without_false_success(self):
        assert asyncio.run(self.register()) is True
        adapter = FakeAdapter(error=RuntimeError("token=leaked-material"))
        first = self.post(adapter=adapter)
        assert first.status_code == 502
        assert first.json()["delivered"] is False
        assert "leaked-material" not in first.text
        assert len(adapter.calls) == 1
        second = self.post(adapter=adapter)
        assert second.json()["reason"] == "already_delivered"
        assert len(adapter.calls) == 1

    def test_in_flight_reservation_is_refused(self):
        assert asyncio.run(self.register()) is True
        adapter = FakeAdapter()

        async def reserve_pending():
            return await self.store.reserve(
                owner_id=OWNER, conversation_id=CHAT, workspace_ref=WORKSPACE,
                source_run_ref=RUN, artifact_id=self.record.artifact_id,
                artifact_integrity_ref=self.record.integrity_ref,
                delivery_kind="external_connector", connector_id="telegram",
                delivery_intent_id="tgint" + "d" * 32,
                attempt_ref="tgdlv" + "d" * 32, now=NOW,
            )


        reservation = asyncio.run(reserve_pending())
        assert reservation.disposition == "new"
        response = self.post(adapter=adapter)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "delivery_in_progress"
        assert adapter.calls == []

    def test_route_creates_no_new_write_send_authority(self):
        import app.claw_telegram_delivery_routes as routes

        assert routes.CONSUMER_ROUTE_IMPLEMENTED is True
        assert routes.NEW_WRITE_SEND_AUTHORITY is False
        assert routes.DESTINATION_FROM_REQUEST is False
        assert routes.APPROVAL_MINTED_BY_ROUTE is False
        assert routes.RESERVATION_RELEASE_SUPPORTED is False
        source = routes.__file__
        with open(source, encoding="utf-8") as handle:
            text = handle.read()
        for forbidden in ("send_document", "bot_token", "api.telegram.org",
                          "provider_chat_id"):
            assert forbidden not in text


class TestTelegramDeliveryReceiptStore(_ConsumerHarness):
    def test_reservation_is_one_attempt_per_artifact(self):
        async def scenario():
            store = InMemoryArtifactDeliveryReceiptStore()
            params = dict(
                owner_id=OWNER, conversation_id=CHAT, workspace_ref=WORKSPACE,
                source_run_ref=RUN, artifact_id=self.record.artifact_id,
                artifact_integrity_ref=self.record.integrity_ref,
                delivery_kind="external_connector", connector_id="telegram",
                delivery_intent_id="tgint" + "e" * 32,
                attempt_ref="tgdlv" + "e" * 32, now=NOW,
            )
            first = await store.reserve(**params)
            second = await store.reserve(**params)
            return first, second

        first, second = asyncio.run(scenario())
        assert first.may_deliver is True
        assert second.disposition == "existing"
        assert second.may_deliver is False
        assert second.receipt["terminal_status"] == "pending"

    def test_d1_reservation_requires_the_completed_owner_run(self):
        async def scenario():
            return await self.store.reserve(
                owner_id=OWNER, conversation_id=CHAT, workspace_ref=WORKSPACE,
                source_run_ref=RUN2, artifact_id=self.record.artifact_id,
                artifact_integrity_ref=self.record.integrity_ref,
                delivery_kind="external_connector", connector_id="telegram",
                delivery_intent_id="tgint" + "f" * 32,
                attempt_ref="tgdlv" + "f" * 32, now=NOW,
            )

        # RUN2 is not completed, so no receipt row can be created.
        reservation = asyncio.run(scenario())
        assert reservation.disposition == "refused"
        assert self.db.execute(
            "SELECT COUNT(*) FROM claw_artifact_delivery_receipts"
        ).fetchone()[0] == 0

    def test_receipt_projection_hides_channel_and_provider_material(self):
        from app.claw_artifact_delivery_receipt_store import receipt_public_projection

        rendered = json.dumps(receipt_public_projection({
            "artifact_id": "artifact_x", "artifact_integrity_ref": "a" * 64,
            "connector_id": "telegram", "delivery_kind": "external_connector",
            "terminal_status": "succeeded", "terminal_class": "success",
            "external_side_effect_count": 1, "retry_count": 0,
            "receipt_ref": "tgdr1", "provider_error_kind": None,
            "provider_error_retryable": None, "started_at": None,
            "completed_at": None, "trusted_channel_ref": CHANNEL_REF,
        }), ensure_ascii=False, sort_keys=True)
        assert CHANNEL_REF not in rendered
        assert "trusted_channel_ref" not in rendered
