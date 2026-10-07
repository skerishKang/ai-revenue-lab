"""#3666 trusted Telegram document-delivery adapter tests (parent #3580).

Hermetic: network-free, model-free, provider-free, live-send-free. Every
collaborator (binding authority, document-send port, artifact-material lookup,
trusted channel context, approval evidence) is a deterministic fake; the
adapter core is exercised end to end without a single socket.

Pins:

1. trusted current Telegram channel + paired chat + canonical artifact +
   existing approval evidence -> SUCCEEDED receipt with exactly one external
   side effect and exactly one provider call;
2. the trusted channel reference is re-resolved per execution: a forged,
   wrong-account, wrong-workspace, revoked/expired-binding or stale-context
   attempt fails closed before any provider interaction;
3. the destination is never an input: the request schema and the adapter
   surface have no chat-id/destination field or parameter at all
   (unrepresentable, not merely rejected), and the provider chat id comes only
   from the existing trusted binding authority;
4. the bot token is never an input either: it is resolved inside the adapter
   through the existing ``TelegramTrustedBindingPort`` and appears in no
   receipt, projection or error reference;
5. a noncanonical or integrity-mismatched artifact reference fails closed
   before any provider interaction — canonical material is verified against
   the #3594 record;
6. duplicate/replayed attempts fail closed (reused
   ``InMemoryDeliveryAttemptRegistry`` vocabulary) and never produce a second
   send;
7. provider results normalize into the reused
   ``ConnectorProviderError``/``ConnectorProviderErrorKind`` taxonomy, with
   the ``retryable`` flag selecting FAILED_RETRYABLE vs FAILED_TERMINAL, and
   the raw provider error body never surfaced;
8. missing/unresolvable approval evidence produces a REFUSED receipt with
   zero side effects, while mismatched approval evidence fails closed;
9. receipt correlation is copied from the request by #3631's
   ``build_delivery_receipt`` — a receipt can never be pointed at another
   attempt, and no second receipt authority exists;
10. no raw secret, raw destination id or raw artifact byte reaches any
    projection; the adapter module contains no network import or endpoint
    literal (external network calls in test = 0).
"""

from __future__ import annotations

import dataclasses
import hashlib
import inspect
import json
import pathlib
import re
import unittest
from datetime import datetime, timedelta, timezone

import kagent.telegram_artifact_delivery as tad
from kagent.artifact_delivery_execution_receipt import (
    ArtifactDeliveryAdapterPort,
    ArtifactDeliveryExecutionError,
    ArtifactDeliveryExecutionRequest,
    ArtifactDeliveryReceipt,
    DeliveryTerminalStatus,
    declare_delivery_execution_request,
)
from kagent.artifact_delivery_intent import DeliveryKind
from kagent.artifact_lineage import LineageArtifactRef
from kagent.artifact_registration import MAX_ARTIFACT_SIZE_BYTES, register_canonical_artifact
from kagent.connector_trust import (
    ConnectorBindingProjection,
    ConnectorBindingState,
    ConnectorProviderErrorKind,
)
from kagent.contracts import ContractError
from kagent.telegram_artifact_delivery import (
    TelegramArtifactDeliveryAdapter,
    TelegramArtifactDeliveryError,
    TelegramArtifactDeliveryRefusal,
    TelegramArtifactMaterial,
    document_material_fingerprint,
)
from kagent.telegram_contracts import (
    TelegramBotScope,
    TelegramChatKind,
    TelegramOutboundApproval,
    TelegramPairedChat,
)
from kagent.trusted_channel_reference import (
    MAX_CONTEXT_AGE,
    TrustedChannelClass,
    TrustedChannelReferenceError,
    TrustedCurrentChannelContext,
    bind_delivery_intent,
    resolve_trusted_channel_reference,
)

NOW = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)
ACCOUNT_REF = "acct-alpha"
WORKSPACE_REF = "ws-alpha"
BINDING_REF = "binding-alpha"
BOT_REF = "bot-alpha"
CHAT_REF = "chat-alpha"
SENDER_REF = "user-alpha"
RUN_REF = "run-alpha"
INTENT_ID = "intent-alpha-1"
ATTEMPT_REF = "attempt-alpha-1"
APPROVAL_REF = "approval-alpha-1"
EVIDENCE_REF = "approval-evidence:alpha-1"
CONNECTOR_ID = "telegram"
ARTIFACT_ID = "artifact-report-1"
PROVIDER_CHAT_ID = 987_654_321
PROVIDER_TOKEN = b"123456:AAfixtureTokenMaterial01"
DOCUMENT_BYTES = b"%PDF-1.4 telegram document delivery fixture bytes"
_FORBIDDEN_NETWORK_TOKENS = (
    "http.client",
    "urllib",
    "socket",
    "api.telegram.org",
    "https://",
    "requests.get",
    "requests.post",
)


def _record():
    return register_canonical_artifact(
        artifact_id=ARTIFACT_ID,
        artifact_kind="claw.document",
        filename="report.pdf",
        media_type="application/pdf",
        size_bytes=len(DOCUMENT_BYTES),
        integrity_ref=hashlib.sha256(DOCUMENT_BYTES).hexdigest(),
        workspace_ref=WORKSPACE_REF,
        run_ref=RUN_REF,
    )


def _artifact_ref(record=None):
    record = record or _record()
    return LineageArtifactRef(artifact_id=record.artifact_id, integrity_ref=record.integrity_ref)


def _binding(
    *,
    account=ACCOUNT_REF,
    workspace=WORKSPACE_REF,
    state=ConnectorBindingState.ACTIVE,
    revoked_at=None,
    expires_at=NOW + timedelta(hours=1),
):
    return ConnectorBindingProjection(
        binding_ref=BINDING_REF,
        connector_id=CONNECTOR_ID,
        actor_ref=SENDER_REF,
        account_ref=account,
        workspace_ref=workspace,
        granted_scopes=("telegram.outbound",),
        granted_capabilities=("telegram.send_document",),
        issued_at=NOW - timedelta(hours=1),
        updated_at=NOW - timedelta(hours=1),
        expires_at=expires_at,
        revoked_at=revoked_at,
        state=state,
    )


def _scope():
    return TelegramBotScope(
        binding_ref=BINDING_REF,
        workspace_ref=WORKSPACE_REF,
        bot_ref=BOT_REF,
        telegram_bot_user_ref="tg-bot-user-1",
        paired_chats=(
            TelegramPairedChat(
                chat_ref=CHAT_REF,
                telegram_chat_id_ref="tg-chat-987654321",
                kind=TelegramChatKind.PRIVATE,
                allowed_sender_refs=(SENDER_REF,),
            ),
        ),
    )


def _context(*, binding=None, account=ACCOUNT_REF, workspace=WORKSPACE_REF, conversation=CHAT_REF, observed_at=NOW):
    return TrustedCurrentChannelContext(
        account_ref=account,
        workspace_ref=workspace,
        conversation_ref=conversation,
        channel_class=TrustedChannelClass.EXTERNAL_CONNECTOR,
        observed_at=observed_at,
        binding=binding or _binding(),
    )


def _reference(context):
    return resolve_trusted_channel_reference(
        context,
        now=NOW,
        expected_account_ref=ACCOUNT_REF,
        expected_workspace_ref=WORKSPACE_REF,
        supported_connector_ids=(CONNECTOR_ID,),
    )


def _request(
    *,
    context=None,
    reference=None,
    record=None,
    attempt_ref=ATTEMPT_REF,
    intent_id=INTENT_ID,
    approval_ref=APPROVAL_REF,
    artifact_ref_override=None,
):
    context = context or _context()
    reference = reference or _reference(context)
    intent = bind_delivery_intent(
        delivery_intent_id=intent_id,
        artifact_ref=artifact_ref_override if artifact_ref_override is not None else _artifact_ref(record),
        reference=reference,
        workspace_ref=WORKSPACE_REF,
        run_ref=RUN_REF,
        created_at=NOW,
        approval_ref=approval_ref,
    )
    return declare_delivery_execution_request(
        attempt_ref=attempt_ref,
        intent=intent,
        reference=reference,
        context=context,
        now=NOW,
        expected_account_ref=ACCOUNT_REF,
        expected_workspace_ref=WORKSPACE_REF,
        supported_connector_ids=(CONNECTOR_ID,),
    )


def _material(record=None, data=DOCUMENT_BYTES):
    return TelegramArtifactMaterial(record=record or _record(), document_bytes=data)


def _approval(record=None, *, fingerprint=None, approval_ref=APPROVAL_REF):
    if fingerprint is None:
        fingerprint = document_material_fingerprint(
            record or _record(),
            binding_ref=BINDING_REF,
            workspace_ref=WORKSPACE_REF,
            bot_ref=BOT_REF,
            chat_ref=CHAT_REF,
        )
    return TelegramOutboundApproval(
        approval_ref=approval_ref,
        evidence_ref=EVIDENCE_REF,
        material_fingerprint=fingerprint,
        approved_at=NOW - timedelta(minutes=5),
    )


class _FakeTrustedBinding:
    def __init__(self, *, chat_id=PROVIDER_CHAT_ID, token=PROVIDER_TOKEN):
        self.chat_id = chat_id
        self.token = token
        self.token_calls = 0
        self.chat_id_calls = 0

    def resolve_bot_token(self, *, binding_ref, bot_ref):
        self.token_calls += 1
        return self.token

    def provider_chat_id(self, *, binding_ref, bot_ref, chat_ref):
        self.chat_id_calls += 1
        return self.chat_id


class _FakeDocumentSend:
    def __init__(self, envelope=None, error=None):
        self.calls = []
        self._envelope = (
            envelope if envelope is not None else {"ok": True, "result": {"message_id": 77}}
        )
        self._error = error

    def send_document(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._envelope


class _FakeMaterialResolver:
    def __init__(self, material):
        self.material = material
        self.calls = []

    def resolve_artifact_material(self, artifact_ref):
        self.calls.append(artifact_ref)
        return self.material


def _adapter(
    *,
    context=None,
    material=None,
    approval=None,
    approval_lookup=None,
    send=None,
    binding=None,
    account_ref=ACCOUNT_REF,
    actor_ref=SENDER_REF,
    clock=None,
):
    record = _record()
    material = material if material is not None else _material(record)
    binding = binding or _binding()
    context = context if context is not None else _context(binding=binding)
    if approval is None:
        approval = _approval(record)
    lookup = approval_lookup if approval_lookup is not None else {APPROVAL_REF: approval}
    send = send if send is not None else _FakeDocumentSend()
    trusted_binding = _FakeTrustedBinding()
    adapter = TelegramArtifactDeliveryAdapter(
        scope=_scope(),
        trusted_binding=trusted_binding,
        document_send=send,
        artifact_material=_FakeMaterialResolver(material),
        channel_context=lambda: context,
        approval_evidence=lambda ref: lookup.get(ref),
        account_ref=account_ref,
        actor_ref=actor_ref,
        clock=clock or (lambda: NOW),
    )
    return adapter, send, trusted_binding, material


class TelegramArtifactDeliveryAdapterTests(unittest.TestCase):
    # 1. trusted current channel -> document adapter PASS (10. SUCCEEDED)
    def test_trusted_current_channel_document_delivery_succeeds(self):
        adapter, send, trusted_binding, material = _adapter()
        request = _request()

        receipt = adapter.deliver(request)

        self.assertIsInstance(receipt, ArtifactDeliveryReceipt)
        self.assertIs(receipt.terminal_status, DeliveryTerminalStatus.SUCCEEDED)
        self.assertEqual(receipt.terminal_class.value, "success")
        self.assertEqual(receipt.external_side_effect_count, 1)
        self.assertEqual(receipt.retry_count, 0)
        self.assertIsNone(receipt.provider_error)
        self.assertTrue(receipt.correlates_with(request))
        self.assertEqual(receipt.started_at, NOW)
        self.assertEqual(receipt.completed_at, NOW)

        self.assertEqual(len(send.calls), 1)
        call = send.calls[0]
        self.assertEqual(call["provider_chat_id"], PROVIDER_CHAT_ID)
        self.assertEqual(call["document_bytes"], DOCUMENT_BYTES)
        self.assertEqual(call["filename"], "report.pdf")
        self.assertEqual(call["mime_type"], "application/pdf")
        self.assertEqual(call["token"], PROVIDER_TOKEN)
        self.assertEqual(call["timeout_seconds"], tad._MAX_DOCUMENT_SEND_TIMEOUT_SECONDS)
        self.assertEqual(trusted_binding.token_calls, 1)
        self.assertEqual(trusted_binding.chat_id_calls, 1)

    def test_adapter_conforms_to_the_existing_port_protocol(self):
        adapter, _, _, _ = _adapter()
        self.assertIsInstance(adapter, ArtifactDeliveryAdapterPort)

    # 2-5. re-resolution failures fail closed before any provider interaction
    def test_forged_trusted_channel_ref_fails_closed(self):
        adapter, send, _, _ = _adapter()
        forged = "tcr1_" + hashlib.sha256(b"forged").hexdigest()
        forged_request = dataclasses.replace(_request(), trusted_channel_ref=forged)

        with self.assertRaises(TrustedChannelReferenceError):
            adapter.deliver(forged_request)
        self.assertEqual(send.calls, [])

    def test_wrong_account_fails_closed(self):
        adapter, send, _, _ = _adapter(context=_context(account="acct-other", binding=_binding(account="acct-other")))

        with self.assertRaises(TrustedChannelReferenceError):
            adapter.deliver(_request())
        self.assertEqual(send.calls, [])

    def test_wrong_workspace_fails_closed(self):
        adapter, send, _, _ = _adapter(
            context=_context(workspace="ws-other", binding=_binding(workspace="ws-other"))
        )

        with self.assertRaises(TrustedChannelReferenceError):
            adapter.deliver(_request())
        self.assertEqual(send.calls, [])

    def test_revoked_binding_fails_closed(self):
        revoked = _binding(
            state=ConnectorBindingState.REVOKED, revoked_at=NOW - timedelta(minutes=1)
        )
        adapter, send, _, _ = _adapter(context=_context(binding=revoked))

        with self.assertRaises(TrustedChannelReferenceError):
            adapter.deliver(_request())
        self.assertEqual(send.calls, [])

    def test_expired_binding_fails_closed(self):
        expired = _binding(expires_at=NOW - timedelta(seconds=30))
        adapter, send, _, _ = _adapter(context=_context(binding=expired))

        with self.assertRaises(TrustedChannelReferenceError):
            adapter.deliver(_request())
        self.assertEqual(send.calls, [])

    def test_stale_trusted_context_fails_closed(self):
        stale = _context(observed_at=NOW - MAX_CONTEXT_AGE - timedelta(seconds=1))
        adapter, send, _, _ = _adapter(context=stale)

        with self.assertRaises(TrustedChannelReferenceError):
            adapter.deliver(_request())
        self.assertEqual(send.calls, [])

    # 6-7. destination / token are unrepresentable, not merely rejected
    def test_request_body_chat_id_is_unrepresentable(self):
        deliver_params = set(inspect.signature(TelegramArtifactDeliveryAdapter.deliver).parameters)
        self.assertEqual(deliver_params, {"self", "request", "now"})
        init_params = set(
            inspect.signature(TelegramArtifactDeliveryAdapter.__init__).parameters
        )
        for forbidden in ("chat_id", "destination", "destination_ref", "telegram_chat_id"):
            self.assertNotIn(forbidden, deliver_params | init_params)

        request_fields = {f.name for f in dataclasses.fields(ArtifactDeliveryExecutionRequest)}
        for forbidden in ("chat_id", "destination", "telegram_chat_id", "recipient"):
            self.assertNotIn(forbidden, request_fields)

        projection = _request().public_projection()
        self.assertFalse(projection["raw_destination_in_projection"])
        forbidden_keys = {"destination", "chat_id", "telegram_chat_id", "destination_ref", "recipient"}
        self.assertEqual(forbidden_keys & set(projection), set())

        with self.assertRaises(ContractError):
            declare_delivery_execution_request(
                attempt_ref="attempt-injected-chat",
                intent=bind_delivery_intent(
                    delivery_intent_id="intent-injected-chat",
                    artifact_ref=_artifact_ref(),
                    reference=_reference(_context()),
                    workspace_ref=WORKSPACE_REF,
                    run_ref=RUN_REF,
                    created_at=NOW,
                ),
                reference=_reference(_context()),
                context=_context(),
                now=NOW,
                expected_account_ref=ACCOUNT_REF,
                expected_workspace_ref=WORKSPACE_REF,
                supported_connector_ids=(CONNECTOR_ID,),
                caller_destination="987654321",
            )

    def test_request_body_bot_token_is_unrepresentable(self):
        deliver_params = set(inspect.signature(TelegramArtifactDeliveryAdapter.deliver).parameters)
        init_params = set(inspect.signature(TelegramArtifactDeliveryAdapter.__init__).parameters)
        for forbidden in ("token", "bot_token", "secret", "credential", "api_key"):
            self.assertNotIn(forbidden, deliver_params | init_params)

        self.assertFalse(tad.TELEGRAM_BOT_TOKEN_IN_MODEL_CONTEXT)
        self.assertFalse(tad.RAW_CONNECTOR_SECRET_IN_TASK_CONTEXT)
        self.assertFalse(tad.TOKEN_STRING_IS_AUTHORITY)

        adapter, send, _, _ = _adapter()
        receipt = adapter.deliver(_request())
        token_text = PROVIDER_TOKEN.decode("ascii")
        receipt_text = json.dumps(receipt.public_projection()) + repr(receipt)
        self.assertNotIn(token_text, receipt_text)
        self.assertEqual(send.calls[0]["token"], PROVIDER_TOKEN)

    # 8. noncanonical / integrity-mismatched artifact fails closed
    def test_unresolvable_artifact_ref_fails_closed(self):
        adapter, send, _, _ = _adapter(material=None)
        adapter._material.material = None

        with self.assertRaises(TelegramArtifactDeliveryError):
            adapter.deliver(_request())
        self.assertEqual(send.calls, [])

    def test_fabricated_artifact_ref_fails_closed(self):
        fabricated = LineageArtifactRef(
            artifact_id="artifact-fabricated", integrity_ref=hashlib.sha256(b"x").hexdigest()
        )
        adapter, send, _, _ = _adapter(material=None)
        adapter._material.material = None
        request = _request(artifact_ref_override=fabricated)

        with self.assertRaises(TelegramArtifactDeliveryError):
            adapter.deliver(request)
        self.assertEqual(send.calls, [])

    def test_integrity_mismatched_material_fails_closed(self):
        tampered = _material(data=DOCUMENT_BYTES + b"tampered")
        adapter, send, _, _ = _adapter(material=tampered)

        with self.assertRaises(TelegramArtifactDeliveryError):
            adapter.deliver(_request())
        self.assertEqual(send.calls, [])

    def test_record_identity_mismatched_material_fails_closed(self):
        other_record = register_canonical_artifact(
            artifact_id="artifact-other",
            artifact_kind="claw.document",
            filename="other.pdf",
            media_type="application/pdf",
            size_bytes=len(DOCUMENT_BYTES),
            integrity_ref=hashlib.sha256(DOCUMENT_BYTES).hexdigest(),
            workspace_ref=WORKSPACE_REF,
            run_ref=RUN_REF,
        )
        adapter, send, _, _ = _adapter(material=TelegramArtifactMaterial(record=other_record, document_bytes=DOCUMENT_BYTES))

        with self.assertRaises(TelegramArtifactDeliveryError):
            adapter.deliver(_request())
        self.assertEqual(send.calls, [])

    def test_empty_material_bytes_are_rejected_at_construction(self):
        with self.assertRaises(TelegramArtifactDeliveryError):
            TelegramArtifactMaterial(record=_record(), document_bytes=b"")

    # 9. duplicate / replay fail closed
    def test_duplicate_delivery_fails_closed(self):
        adapter, send, _, _ = _adapter()
        request = _request()

        adapter.deliver(request)
        with self.assertRaises(ArtifactDeliveryExecutionError):
            adapter.deliver(request)
        self.assertEqual(len(send.calls), 1)

    def test_conflicting_attempt_ref_fails_closed(self):
        adapter, send, _, _ = _adapter()
        adapter.deliver(_request())

        conflicting = _request(intent_id="intent-alpha-2")
        with self.assertRaises(ArtifactDeliveryExecutionError):
            adapter.deliver(conflicting)
        self.assertEqual(len(send.calls), 1)

    # 10-12. provider outcomes normalize into the existing taxonomy
    def test_provider_retryable_rate_limit_failure(self):
        send = _FakeDocumentSend(
            envelope={
                "ok": False,
                "error_code": 429,
                "description": "Too Many Requests: retry later (raw body must stay internal)",
                "parameters": {"retry_after": 30},
            }
        )
        adapter, send, _, _ = _adapter(send=send)

        receipt = adapter.deliver(_request())

        self.assertIs(receipt.terminal_status, DeliveryTerminalStatus.FAILED_RETRYABLE)
        self.assertEqual(receipt.terminal_class.value, "failure")
        self.assertEqual(receipt.external_side_effect_count, 0)
        self.assertTrue(receipt.correlates_with(_request()))
        error = receipt.provider_error
        self.assertIs(error.kind, ConnectorProviderErrorKind.RATE_LIMITED)
        self.assertTrue(error.retryable)
        self.assertEqual(error.rate_limit.retry_after_seconds, 30)
        self.assertNotIn("Too Many Requests", json.dumps(receipt.public_projection()))
        self.assertNotIn("Too Many Requests", repr(receipt))

    def test_provider_unavailable_5xx_maps_to_retryable(self):
        send = _FakeDocumentSend(envelope={"ok": False, "error_code": 502, "description": "Bad Gateway"})
        adapter, send, _, _ = _adapter(send=send)

        receipt = adapter.deliver(_request())

        self.assertIs(receipt.terminal_status, DeliveryTerminalStatus.FAILED_RETRYABLE)
        self.assertIs(receipt.provider_error.kind, ConnectorProviderErrorKind.UNAVAILABLE)
        self.assertTrue(receipt.provider_error.retryable)

    def test_provider_terminal_failures_map_to_failed_terminal(self):
        expectations = {
            400: ConnectorProviderErrorKind.INVALID_REQUEST,
            401: ConnectorProviderErrorKind.AUTHORIZATION,
            403: ConnectorProviderErrorKind.AUTHORIZATION,
            404: ConnectorProviderErrorKind.NOT_FOUND,
            409: ConnectorProviderErrorKind.CONFLICT,
        }
        for code, expected_kind in expectations.items():
            with self.subTest(error_code=code):
                send = _FakeDocumentSend(envelope={"ok": False, "error_code": code, "description": "rejected"})
                adapter, _, _, _ = _adapter(send=send)
                receipt = adapter.deliver(_request(attempt_ref=f"attempt-code-{code}"))
                self.assertIs(receipt.terminal_status, DeliveryTerminalStatus.FAILED_TERMINAL)
                self.assertIs(receipt.provider_error.kind, expected_kind)
                self.assertFalse(receipt.provider_error.retryable)

    def test_transport_unavailable_maps_to_retryable_receipt(self):
        send = _FakeDocumentSend(error=OSError("connection refused"))
        adapter, _, _, _ = _adapter(send=send)

        receipt = adapter.deliver(_request())

        self.assertIs(receipt.terminal_status, DeliveryTerminalStatus.FAILED_RETRYABLE)
        self.assertIs(receipt.provider_error.kind, ConnectorProviderErrorKind.UNAVAILABLE)
        self.assertTrue(receipt.provider_error.retryable)
        self.assertEqual(receipt.external_side_effect_count, 0)

    def test_malformed_provider_envelope_fails_closed(self):
        for envelope in ({"ok": "yes"}, {"ok": True}, {"ok": True, "result": "not-a-dict"}):
            with self.subTest(envelope=envelope):
                send = _FakeDocumentSend(envelope=envelope)
                adapter, _, _, _ = _adapter(send=send)
                with self.assertRaises(ContractError):
                    adapter.deliver(_request(attempt_ref=f"attempt-envelope-{len(str(envelope))}"))

    # 13. correlation is impossible to point elsewhere
    def test_receipt_correlation_is_copied_from_the_request(self):
        adapter, _, _, _ = _adapter()
        request = _request()
        receipt = adapter.deliver(request)
        self.assertTrue(receipt.correlates_with(request))

        retry_send = _FakeDocumentSend(envelope={"ok": False, "error_code": 403, "description": "x"})
        adapter2, _, _, _ = _adapter(send=retry_send)
        request2 = _request(attempt_ref="attempt-alpha-2")
        receipt2 = adapter2.deliver(request2)
        self.assertTrue(receipt2.correlates_with(request2))
        self.assertFalse(receipt2.correlates_with(request))

        self.assertRegex(receipt.receipt_ref, r"^tgdr[0-9a-f]{32}$")
        self.assertNotEqual(receipt.receipt_ref, receipt2.receipt_ref)

    # 14-15. no raw secret / destination id output
    def test_raw_secret_output_is_zero(self):
        adapter, _, _, _ = _adapter()
        receipt = adapter.deliver(_request())
        serialized = json.dumps(receipt.public_projection()) + repr(receipt)
        self.assertNotIn(PROVIDER_TOKEN.decode("ascii"), serialized)
        self.assertEqual(tad.RAW_BOT_TOKEN_IN_LOG, 0)
        projection = receipt.public_projection()
        self.assertFalse(projection["connector_secret_in_projection"])
        self.assertFalse(projection["raw_provider_error_in_projection"])

    def test_raw_destination_id_output_is_zero(self):
        adapter, _, _, _ = _adapter()
        receipt = adapter.deliver(_request())
        serialized = json.dumps(receipt.public_projection()) + repr(receipt)
        self.assertNotIn(str(PROVIDER_CHAT_ID), serialized)
        self.assertNotIn("tg-chat-", serialized)
        self.assertEqual(tad.RAW_CHAT_ID_IN_RECEIPT, 0)
        self.assertFalse(receipt.public_projection()["raw_destination_in_projection"])

    def test_raw_artifact_bytes_in_receipt_is_zero(self):
        adapter, _, _, _ = _adapter()
        receipt = adapter.deliver(_request())
        serialized = json.dumps(receipt.public_projection()) + repr(receipt)
        self.assertNotIn(DOCUMENT_BYTES.decode("utf-8", errors="ignore"), serialized)
        self.assertEqual(tad.RAW_ARTIFACT_BYTES_IN_RECEIPT, 0)
        self.assertFalse(receipt.public_projection()["artifact_bytes_in_projection"])

    # approval evidence: consumed, never minted
    def test_missing_approval_ref_yields_refused_receipt(self):
        adapter, send, _, _ = _adapter()
        request = _request(approval_ref=None)

        receipt = adapter.deliver(request)

        self.assertIs(receipt.terminal_status, DeliveryTerminalStatus.REFUSED)
        self.assertEqual(receipt.terminal_class.value, "refusal")
        self.assertEqual(receipt.external_side_effect_count, 0)
        self.assertIsNone(receipt.provider_error)
        self.assertTrue(receipt.correlates_with(request))
        self.assertEqual(send.calls, [])

    def test_unresolvable_approval_evidence_yields_refused_receipt(self):
        adapter, send, _, _ = _adapter(approval_lookup={})

        receipt = adapter.deliver(_request())

        self.assertIs(receipt.terminal_status, DeliveryTerminalStatus.REFUSED)
        self.assertEqual(send.calls, [])

    def test_mismatched_approval_fingerprint_fails_closed(self):
        adapter, send, _, _ = _adapter(
            approval=_approval(fingerprint=hashlib.sha256(b"other-material").hexdigest())
        )

        with self.assertRaises(TelegramArtifactDeliveryError):
            adapter.deliver(_request())
        self.assertEqual(send.calls, [])

    def test_approval_for_another_chat_fails_closed(self):
        fingerprint = document_material_fingerprint(
            _record(),
            binding_ref=BINDING_REF,
            workspace_ref=WORKSPACE_REF,
            bot_ref=BOT_REF,
            chat_ref="chat-somewhere-else",
        )
        adapter, send, _, _ = _adapter(approval=_approval(fingerprint=fingerprint))

        with self.assertRaises(TelegramArtifactDeliveryError):
            adapter.deliver(_request())
        self.assertEqual(send.calls, [])

    def test_refusal_type_is_a_fail_closed_error(self):
        self.assertTrue(issubclass(TelegramArtifactDeliveryRefusal, TelegramArtifactDeliveryError))

    # scope / pairing authority
    def test_unpaired_conversation_fails_closed(self):
        context = _context(conversation="chat-unpaired", binding=_binding())
        reference = _reference(context)
        adapter, send, _, _ = _adapter(context=context)

        with self.assertRaises(TelegramArtifactDeliveryError):
            adapter.deliver(_request(context=context, reference=reference))
        self.assertEqual(send.calls, [])

    def test_unauthorized_outbound_actor_fails_closed(self):
        adapter, send, _, _ = _adapter(actor_ref="user-intruder")

        with self.assertRaises(TelegramArtifactDeliveryError):
            adapter.deliver(_request())
        self.assertEqual(send.calls, [])

    def test_current_surface_delivery_kind_is_refused(self):
        context = TrustedCurrentChannelContext(
            account_ref=ACCOUNT_REF,
            workspace_ref=WORKSPACE_REF,
            conversation_ref=CHAT_REF,
            channel_class=TrustedChannelClass.CURRENT_SURFACE,
            observed_at=NOW,
            binding=None,
        )
        reference = resolve_trusted_channel_reference(
            context,
            now=NOW,
            expected_account_ref=ACCOUNT_REF,
            expected_workspace_ref=WORKSPACE_REF,
        )
        intent = bind_delivery_intent(
            delivery_intent_id="intent-surface-1",
            artifact_ref=_artifact_ref(),
            reference=reference,
            workspace_ref=WORKSPACE_REF,
            run_ref=RUN_REF,
            created_at=NOW,
        )
        request = declare_delivery_execution_request(
            attempt_ref="attempt-surface-1",
            intent=intent,
            reference=reference,
            context=context,
            now=NOW,
            expected_account_ref=ACCOUNT_REF,
            expected_workspace_ref=WORKSPACE_REF,
        )
        self.assertIs(request.delivery_kind, DeliveryKind.CURRENT_SURFACE)

        adapter, send, _, _ = _adapter()
        with self.assertRaises(TelegramArtifactDeliveryError):
            adapter.deliver(request)
        self.assertEqual(send.calls, [])

    def test_invalid_provider_chat_identity_fails_closed(self):
        for bad_chat_id in (0, -5, "987654321"):
            with self.subTest(chat_id=bad_chat_id):
                adapter, send, _, _ = _adapter()
                adapter._binding.chat_id = bad_chat_id
                with self.assertRaises(ContractError):
                    adapter.deliver(_request(attempt_ref=f"attempt-bad-chat-{bad_chat_id}"))
                self.assertEqual(send.calls, [])

    # 16-17. no second execution / receipt authority
    def test_second_execution_authority_is_zero(self):
        self.assertEqual(tad.SECOND_EXECUTION_AUTHORITY, 0)
        self.assertEqual(tad.SECOND_SEND, 0)
        self.assertEqual(tad.FANOUT, 0)
        self.assertFalse(tad.AUTO_RETRY)
        self.assertEqual(tad.RETRY_COUNT_PER_ATTEMPT, 0)

        source = pathlib.Path(tad.__file__).read_text(encoding="utf-8")
        self.assertNotIn("class ", "\n".join(
            line for line in source.splitlines() if "Registry" in line
        ))
        self.assertIn("InMemoryDeliveryAttemptRegistry", source)

        adapter, send, _, _ = _adapter()
        receipt = adapter.deliver(_request())
        self.assertEqual(receipt.retry_count, 0)
        self.assertEqual(len(send.calls), 1)

    def test_second_receipt_authority_is_zero(self):
        self.assertEqual(tad.SECOND_RECEIPT_AUTHORITY, 0)
        source = pathlib.Path(tad.__file__).read_text(encoding="utf-8")
        self.assertNotIn("class ArtifactDeliveryReceipt", source)
        self.assertIn("build_delivery_receipt", source)

        adapter, _, _, _ = _adapter()
        receipt = adapter.deliver(_request())
        self.assertIs(type(receipt), ArtifactDeliveryReceipt)

    # 18. no external network path anywhere in the adapter or the tests
    def test_external_network_calls_in_test_are_zero(self):
        self.assertFalse(tad.EXTERNAL_NETWORK_PATH_IN_MODULE)
        self.assertFalse(tad.LIVE_TELEGRAM_SEND)
        self.assertTrue(tad.SOURCE_SLICE_WITHOUT_LIVE_SEND)

        adapter_source = pathlib.Path(tad.__file__).read_text(encoding="utf-8").lower()
        for token in _FORBIDDEN_NETWORK_TOKENS:
            self.assertNotIn(token, adapter_source, f"{token} in adapter module")

        network_import = re.compile(
            r"^\s*(?:import|from)\s+(?:socket|ssl|http|urllib|requests|ftplib|telnetlib)\b",
            re.MULTILINE,
        )
        for path in (pathlib.Path(tad.__file__), pathlib.Path(__file__)):
            source = path.read_text(encoding="utf-8")
            self.assertIsNone(network_import.search(source), f"network import in {path.name}")

    # fingerprint binding function
    def test_document_material_fingerprint_is_deterministic_and_bound(self):
        record = _record()
        base = document_material_fingerprint(
            record,
            binding_ref=BINDING_REF,
            workspace_ref=WORKSPACE_REF,
            bot_ref=BOT_REF,
            chat_ref=CHAT_REF,
        )
        self.assertEqual(len(base), 64)
        self.assertRegex(base, r"^[0-9a-f]{64}$")
        again = document_material_fingerprint(
            record,
            binding_ref=BINDING_REF,
            workspace_ref=WORKSPACE_REF,
            bot_ref=BOT_REF,
            chat_ref=CHAT_REF,
        )
        self.assertEqual(base, again)
        for changed in (
            document_material_fingerprint(
                record,
                binding_ref=BINDING_REF,
                workspace_ref=WORKSPACE_REF,
                bot_ref=BOT_REF,
                chat_ref="chat-other",
            ),
            document_material_fingerprint(
                _record(),
                binding_ref="binding-other",
                workspace_ref=WORKSPACE_REF,
                bot_ref=BOT_REF,
                chat_ref=CHAT_REF,
            ),
        ):
            self.assertNotEqual(base, changed)

    def test_material_size_bound_keeps_canonical_ceiling(self):
        self.assertLessEqual(MAX_ARTIFACT_SIZE_BYTES, 8 * 1024 * 1024)
        self.assertLessEqual(len(DOCUMENT_BYTES), MAX_ARTIFACT_SIZE_BYTES)


if __name__ == "__main__":
    unittest.main()