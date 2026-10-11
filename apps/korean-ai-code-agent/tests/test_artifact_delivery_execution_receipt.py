"""#3631 provider-neutral delivery execution request/receipt tests (parent #3580).

Hermetic: network-free, model-free, provider-free, execution-free. Pins:

- a valid #3605 intent + a re-resolved #3621 trusted reference bind to an
  execution request carrying only existing canonical refs;
- the reference string is never authority: every request is re-resolved against
  the trusted context, so wrong account / wrong workspace / stale context /
  revoked binding / tampered metadata all fail closed;
- a caller-supplied destination or channel label grants no authority;
- artifact, intent-reference and approval mismatches fail closed;
- a duplicate or replayed attempt fails closed instead of granting a second
  execution;
- the terminal vocabulary is bounded and closed, ``terminal_class`` is derived
  from ``terminal_status``, and the reused ``ConnectorProviderError`` taxonomy's
  ``retryable`` flag must agree with the terminal status;
- receipt correlation is copied exactly from the request;
- no raw channel ref, external-result ref, destination id, credential or
  artifact byte reaches a projection;
- the adapter port is a Protocol with no implementation here, and the module has
  no transport/send/write surface at all, so the external-effect count is
  structurally zero;
- no durable store or schema is introduced.
"""

from __future__ import annotations

import hashlib
import inspect
import pathlib
import re
import unittest
from datetime import datetime, timedelta, timezone

import kagent.artifact_delivery_execution_receipt as ader
from kagent.artifact_delivery_intent import ArtifactDeliveryIntent, DeliveryKind
from kagent.artifact_lineage import LineageArtifactRef
from kagent.connector_trust import (
    ConnectorBindingProjection,
    ConnectorBindingState,
    ConnectorProviderError,
    ConnectorProviderErrorKind,
    IdempotencyDisposition,
)
from kagent.contracts import ContractError
from kagent.trusted_channel_reference import (
    MAX_CONTEXT_AGE,
    TrustedChannelClass,
    TrustedChannelReference,
    TrustedChannelReferenceError,
    TrustedCurrentChannelContext,
    resolve_trusted_channel_reference,
)
from kagent.artifact_delivery_execution_receipt import (
    ArtifactDeliveryAdapterPort,
    ArtifactDeliveryExecutionError,
    ArtifactDeliveryExecutionRequest,
    ArtifactDeliveryReceipt,
    DeliveryTerminalClass,
    DeliveryTerminalStatus,
    InMemoryDeliveryAttemptRegistry,
    build_delivery_receipt,
    declare_delivery_execution_request,
    terminal_class_for,
)


NOW = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
DIGEST = hashlib.sha256(b"trusted-channel-artifact").hexdigest()

ACCOUNT_REF = "acct_" + "a" * 16
WORKSPACE_REF = "ws_" + "b" * 16
OTHER_ACCOUNT_REF = "acct_" + "c" * 16
OTHER_WORKSPACE_REF = "ws_" + "d" * 16
CONVERSATION_REF = "chat_" + "e" * 16
BINDING_REF = "bind_" + "f" * 16
CONNECTOR_ID = "telegram-bot"
APPROVAL_REF = "appr_" + "9" * 16
ATTEMPT_REF = "att_" + "5" * 16
RUN_REF = "run_" + "3" * 16
INTENT_ID = "dli_" + "1" * 16
EXTERNAL_INTENT_ID = "dli_" + "2" * 16


def artifact_ref() -> LineageArtifactRef:
    return LineageArtifactRef(artifact_id="art_" + "a" * 16, integrity_ref=DIGEST)


def other_artifact_ref() -> LineageArtifactRef:
    return LineageArtifactRef(
        artifact_id="art_" + "7" * 16,
        integrity_ref=hashlib.sha256(b"other").hexdigest(),
    )


def binding(**overrides) -> ConnectorBindingProjection:
    values = dict(
        binding_ref=BINDING_REF,
        connector_id=CONNECTOR_ID,
        actor_ref="actor_" + "1" * 8,
        account_ref=ACCOUNT_REF,
        workspace_ref=WORKSPACE_REF,
        granted_scopes=("chat:write",),
        granted_capabilities=("artifact.deliver",),
        issued_at=NOW - timedelta(hours=1),
        updated_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=1),
    )
    values.update(overrides)
    return ConnectorBindingProjection(**values)


def current_surface_context(**overrides) -> TrustedCurrentChannelContext:
    values = dict(
        account_ref=ACCOUNT_REF,
        workspace_ref=WORKSPACE_REF,
        conversation_ref=CONVERSATION_REF,
        channel_class=TrustedChannelClass.CURRENT_SURFACE,
        observed_at=NOW,
    )
    values.update(overrides)
    return TrustedCurrentChannelContext(**values)


def external_context(**overrides) -> TrustedCurrentChannelContext:
    values = dict(
        account_ref=ACCOUNT_REF,
        workspace_ref=WORKSPACE_REF,
        conversation_ref=CONVERSATION_REF,
        channel_class=TrustedChannelClass.EXTERNAL_CONNECTOR,
        observed_at=NOW,
        binding=binding(),
    )
    values.update(overrides)
    return TrustedCurrentChannelContext(**values)


def surface_reference() -> TrustedChannelReference:
    return resolve_trusted_channel_reference(
        current_surface_context(),
        now=NOW,
        expected_account_ref=ACCOUNT_REF,
        expected_workspace_ref=WORKSPACE_REF,
    )


def external_reference() -> TrustedChannelReference:
    return resolve_trusted_channel_reference(
        external_context(),
        now=NOW,
        expected_account_ref=ACCOUNT_REF,
        expected_workspace_ref=WORKSPACE_REF,
        supported_connector_ids=(CONNECTOR_ID,),
    )


def surface_intent(reference: TrustedChannelReference | None = None, **overrides) -> ArtifactDeliveryIntent:
    ref = reference if reference is not None else surface_reference()
    values = dict(
        delivery_intent_id=INTENT_ID,
        artifact_ref=artifact_ref(),
        delivery_kind=DeliveryKind.CURRENT_SURFACE,
        trusted_channel_ref=ref.channel_ref,
        workspace_ref=WORKSPACE_REF,
        run_ref=RUN_REF,
        created_at=NOW,
    )
    values.update(overrides)
    return ArtifactDeliveryIntent(**values)


def external_intent(reference: TrustedChannelReference | None = None, **overrides) -> ArtifactDeliveryIntent:
    ref = reference if reference is not None else external_reference()
    values = dict(
        delivery_intent_id=EXTERNAL_INTENT_ID,
        artifact_ref=artifact_ref(),
        delivery_kind=DeliveryKind.EXTERNAL_CONNECTOR,
        trusted_channel_ref=ref.channel_ref,
        workspace_ref=WORKSPACE_REF,
        run_ref=RUN_REF,
        created_at=NOW,
        channel_binding_ref=BINDING_REF,
    )
    values.update(overrides)
    return ArtifactDeliveryIntent(**values)


def declare(intent, reference, context, **overrides) -> ArtifactDeliveryExecutionRequest:
    values = dict(
        attempt_ref=ATTEMPT_REF,
        intent=intent,
        reference=reference,
        context=context,
        now=NOW,
        expected_account_ref=ACCOUNT_REF,
        expected_workspace_ref=WORKSPACE_REF,
    )
    values.update(overrides)
    return declare_delivery_execution_request(**values)


def declare_surface(**overrides) -> ArtifactDeliveryExecutionRequest:
    reference = surface_reference()
    return declare(surface_intent(reference), reference, current_surface_context(), **overrides)


class ExecutionRequestBindingTests(unittest.TestCase):
    def test_valid_intent_and_trusted_reference_bind_to_a_request(self) -> None:
        reference = surface_reference()
        intent = surface_intent(reference)
        request = declare(intent, reference, current_surface_context())

        self.assertIsInstance(request, ArtifactDeliveryExecutionRequest)
        self.assertEqual(request.attempt_ref, ATTEMPT_REF)
        self.assertEqual(request.delivery_intent_id, INTENT_ID)
        self.assertEqual(request.artifact_ref, artifact_ref())
        self.assertEqual(request.delivery_kind, DeliveryKind.CURRENT_SURFACE)
        self.assertEqual(request.trusted_channel_ref, reference.channel_ref)
        self.assertEqual(request.workspace_ref, WORKSPACE_REF)
        self.assertEqual(request.run_ref, RUN_REF)
        self.assertIsNone(request.channel_binding_ref)

    def test_external_connector_intent_binds_through_the_existing_binding(self) -> None:
        reference = external_reference()
        intent = external_intent(reference)
        request = declare(
            intent,
            reference,
            external_context(),
            supported_connector_ids=(CONNECTOR_ID,),
        )
        self.assertEqual(request.delivery_kind, DeliveryKind.EXTERNAL_CONNECTOR)
        self.assertEqual(request.channel_binding_ref, BINDING_REF)
        self.assertEqual(request.trusted_channel_ref, reference.channel_ref)

    def test_binding_is_deterministic_for_one_intent(self) -> None:
        self.assertEqual(declare_surface().stable_identity(), declare_surface().stable_identity())

    def test_request_carries_only_existing_canonical_refs(self) -> None:
        parameters = set(inspect.signature(declare_delivery_execution_request).parameters)
        for forbidden in (
            "destination",
            "destination_ref",
            "destination_id",
            "chat_id",
            "channel_id",
            "drive_file_id",
            "folder_id",
            "transport",
            "connector_id",
            "token",
            "secret",
            "bot_token",
            "refresh_token",
            "sender",
            "uploader",
            "writer",
        ):
            self.assertNotIn(forbidden, parameters)

    def test_agreeing_channel_label_is_accepted_but_still_not_the_authority(self) -> None:
        reference = surface_reference()
        intent = surface_intent(reference)
        with_label = declare(
            intent, reference, current_surface_context(), caller_channel_label="current_surface"
        )
        without_label = declare(intent, reference, current_surface_context())
        self.assertEqual(with_label.stable_identity(), without_label.stable_identity())
        self.assertIsNone(with_label.channel_binding_ref)


class FailClosedTests(unittest.TestCase):
    """#3621's re-resolution contract stays the authority for channel failures.

    A wrong account/workspace, a stale context, a revoked binding and tampered
    metadata are refused by the existing ``TrustedChannelReferenceError`` — this
    module re-implements no part of that check. The delivery-specific mismatches
    below are refused by this module's own ``ArtifactDeliveryExecutionError``.
    """

    def test_wrong_account_is_refused(self) -> None:
        reference = surface_reference()
        with self.assertRaises(TrustedChannelReferenceError) as ctx:
            declare(
                surface_intent(reference),
                reference,
                current_surface_context(),
                expected_account_ref=OTHER_ACCOUNT_REF,
            )
        self.assertIn("cross-account", str(ctx.exception))

    def test_wrong_workspace_is_refused(self) -> None:
        reference = surface_reference()
        with self.assertRaises(TrustedChannelReferenceError) as ctx:
            declare(
                surface_intent(reference),
                reference,
                current_surface_context(),
                expected_workspace_ref=OTHER_WORKSPACE_REF,
            )
        self.assertIn("cross-workspace", str(ctx.exception))

    def test_stale_trusted_context_is_refused(self) -> None:
        reference = surface_reference()
        stale = current_surface_context(observed_at=NOW - MAX_CONTEXT_AGE - timedelta(seconds=1))
        with self.assertRaises(TrustedChannelReferenceError) as ctx:
            declare(surface_intent(reference), reference, stale)
        self.assertIn("stale", str(ctx.exception))

    def test_revoked_binding_is_refused(self) -> None:
        reference = external_reference()
        revoked = external_context(
            binding=binding(
                state=ConnectorBindingState.REVOKED,
                revoked_at=NOW - timedelta(minutes=1),
            )
        )
        with self.assertRaises(TrustedChannelReferenceError) as ctx:
            declare(
                external_intent(reference),
                reference,
                revoked,
                supported_connector_ids=(CONNECTOR_ID,),
            )
        self.assertIn("expired, revoked or not yet valid", str(ctx.exception))

    def test_tampered_reference_metadata_is_refused(self) -> None:
        reference = surface_reference()
        tampered = TrustedChannelReference(
            channel_ref=reference.channel_ref,
            channel_class=reference.channel_class,
            account_ref=reference.account_ref,
            workspace_ref=OTHER_WORKSPACE_REF,
            conversation_ref=reference.conversation_ref,
            resolved_at=reference.resolved_at,
        )
        with self.assertRaises(TrustedChannelReferenceError) as ctx:
            declare(surface_intent(reference), tampered, current_surface_context())
        self.assertIn("metadata does not match the context", str(ctx.exception))

    def test_forged_request_body_destination_is_rejected(self) -> None:
        reference = surface_reference()
        for forged in ("123456789", "chat-99", "https://t.me/x"):
            with self.assertRaises(ArtifactDeliveryExecutionError) as ctx:
                declare(
                    surface_intent(reference),
                    reference,
                    current_surface_context(),
                    caller_destination=forged,
                )
            self.assertIn("not delivery authority", str(ctx.exception))

    def test_caller_supplied_channel_label_grants_no_authority(self) -> None:
        reference = surface_reference()
        for forged in ("telegram", "drive", "", "external_connector"):
            with self.assertRaises(ArtifactDeliveryExecutionError) as ctx:
                declare(
                    surface_intent(reference),
                    reference,
                    current_surface_context(),
                    caller_channel_label=forged,
                )
            self.assertIn("not delivery authority", str(ctx.exception))

    def test_artifact_mismatch_is_refused(self) -> None:
        reference = surface_reference()
        with self.assertRaises(ArtifactDeliveryExecutionError) as ctx:
            declare(
                surface_intent(reference),
                reference,
                current_surface_context(),
                artifact_ref=other_artifact_ref(),
            )
        self.assertIn("does not match the delivery intent artifact", str(ctx.exception))

    def test_matching_artifact_argument_is_accepted(self) -> None:
        reference = surface_reference()
        request = declare(
            surface_intent(reference),
            reference,
            current_surface_context(),
            artifact_ref=artifact_ref(),
        )
        self.assertEqual(request.artifact_ref, artifact_ref())

    def test_intent_reference_mismatch_is_refused(self) -> None:
        # A validly resolved reference, but an intent pointing at a *different*
        # resolved channel: the intent/ref binding must be exact.
        bound_reference = surface_reference()
        other_reference = resolve_trusted_channel_reference(
            current_surface_context(conversation_ref="chat_" + "9" * 16),
            now=NOW,
            expected_account_ref=ACCOUNT_REF,
            expected_workspace_ref=WORKSPACE_REF,
        )
        self.assertNotEqual(bound_reference.channel_ref, other_reference.channel_ref)
        mismatched_intent = surface_intent(
            bound_reference, trusted_channel_ref=other_reference.channel_ref
        )
        with self.assertRaises(ArtifactDeliveryExecutionError) as ctx:
            declare(mismatched_intent, bound_reference, current_surface_context())
        self.assertIn("does not reference this trusted channel", str(ctx.exception))

    def test_reference_resolved_for_another_conversation_is_refused(self) -> None:
        reference = surface_reference()
        other_reference = resolve_trusted_channel_reference(
            current_surface_context(conversation_ref="chat_" + "9" * 16),
            now=NOW,
            expected_account_ref=ACCOUNT_REF,
            expected_workspace_ref=WORKSPACE_REF,
        )
        with self.assertRaises(TrustedChannelReferenceError) as ctx:
            declare(surface_intent(reference), other_reference, current_surface_context())
        self.assertIn("does not match the context", str(ctx.exception))

    def test_approval_mismatch_is_refused(self) -> None:
        reference = surface_reference()
        intent = surface_intent(reference, approval_ref=APPROVAL_REF)
        with self.assertRaises(ArtifactDeliveryExecutionError) as ctx:
            declare(
                intent,
                reference,
                current_surface_context(),
                approval_ref="appr_" + "8" * 16,
            )
        self.assertIn("does not match the delivery intent approval", str(ctx.exception))

    def test_matching_approval_argument_is_accepted(self) -> None:
        reference = surface_reference()
        intent = surface_intent(reference, approval_ref=APPROVAL_REF)
        request = declare(
            intent, reference, current_surface_context(), approval_ref=APPROVAL_REF
        )
        self.assertEqual(request.approval_ref, APPROVAL_REF)

    def test_delivery_kind_without_a_channel_class_is_refused(self) -> None:
        reference = surface_reference()
        intent = surface_intent(reference, delivery_kind=DeliveryKind.DURABLE_STORE)
        with self.assertRaises(ArtifactDeliveryExecutionError) as ctx:
            declare(intent, reference, current_surface_context())
        self.assertIn("no trusted channel class", str(ctx.exception))

    def test_missing_trusted_context_is_refused(self) -> None:
        reference = surface_reference()
        with self.assertRaises(TrustedChannelReferenceError) as ctx:
            declare(surface_intent(reference), reference, None)
        self.assertIn("trusted current-channel context is required", str(ctx.exception))

    def test_malformed_intent_is_refused(self) -> None:
        reference = surface_reference()
        with self.assertRaises(ArtifactDeliveryExecutionError) as ctx:
            declare({"delivery_intent_id": INTENT_ID}, reference, current_surface_context())
        self.assertIn("must be an ArtifactDeliveryIntent", str(ctx.exception))

    def test_hand_built_non_resolved_reference_is_refused(self) -> None:
        with self.assertRaises(ArtifactDeliveryExecutionError) as ctx:
            ArtifactDeliveryExecutionRequest(
                attempt_ref=ATTEMPT_REF,
                delivery_intent_id=INTENT_ID,
                artifact_ref=artifact_ref(),
                delivery_kind=DeliveryKind.CURRENT_SURFACE,
                trusted_channel_ref="channel_ref_opaque_7",
                workspace_ref=WORKSPACE_REF,
                run_ref=RUN_REF,
                requested_at=NOW,
            )
        self.assertIn("resolved trusted channel reference handle", str(ctx.exception))

    def test_current_surface_request_may_not_carry_a_binding(self) -> None:
        with self.assertRaises(ArtifactDeliveryExecutionError) as ctx:
            ArtifactDeliveryExecutionRequest(
                attempt_ref=ATTEMPT_REF,
                delivery_intent_id=INTENT_ID,
                artifact_ref=artifact_ref(),
                delivery_kind=DeliveryKind.CURRENT_SURFACE,
                trusted_channel_ref=surface_reference().channel_ref,
                workspace_ref=WORKSPACE_REF,
                run_ref=RUN_REF,
                requested_at=NOW,
                channel_binding_ref=BINDING_REF,
            )
        self.assertIn("must not carry a connector binding ref", str(ctx.exception))


class ReplayBoundaryTests(unittest.TestCase):
    def test_first_attempt_is_admitted(self) -> None:
        registry = InMemoryDeliveryAttemptRegistry()
        registry.admit(declare_surface())  # first attempt is allowed through the guard

    def test_first_observation_reports_new(self) -> None:
        registry = InMemoryDeliveryAttemptRegistry()
        self.assertIs(
            registry.disposition(declare_surface()), IdempotencyDisposition.NEW
        )

    def test_same_attempt_replay_is_refused(self) -> None:
        registry = InMemoryDeliveryAttemptRegistry()
        first = declare_surface()
        registry.admit(first)
        replay = declare_surface()  # identical attempt, same attempt_ref
        self.assertIs(registry.disposition(replay), IdempotencyDisposition.REPLAY_SAME)
        with self.assertRaises(ArtifactDeliveryExecutionError) as ctx:
            registry.admit(replay)
        self.assertIn("second execution is not authorized", str(ctx.exception))

    def test_conflicting_reuse_of_attempt_ref_is_refused(self) -> None:
        registry = InMemoryDeliveryAttemptRegistry()
        registry.admit(declare_surface())
        conflicting = ArtifactDeliveryExecutionRequest(
            attempt_ref=ATTEMPT_REF,
            delivery_intent_id="dli_" + "7" * 16,
            artifact_ref=artifact_ref(),
            delivery_kind=DeliveryKind.CURRENT_SURFACE,
            trusted_channel_ref=surface_reference().channel_ref,
            workspace_ref=WORKSPACE_REF,
            run_ref=RUN_REF,
            requested_at=NOW,
        )
        self.assertIs(registry.disposition(conflicting), IdempotencyDisposition.CONFLICT)
        with self.assertRaises(ArtifactDeliveryExecutionError) as ctx:
            registry.admit(conflicting)
        self.assertIn("already bound to a different delivery attempt", str(ctx.exception))

    def test_guard_is_in_memory_only(self) -> None:
        registry = InMemoryDeliveryAttemptRegistry()
        registry.admit(declare_surface())
        self.assertEqual(
            [name for name in vars(registry) if name.startswith("_")],
            ["_seen"],
        )


class ReceiptContractTests(unittest.TestCase):
    def receipt(self, request=None, **overrides) -> ArtifactDeliveryReceipt:
        values = dict(
            receipt_ref="rcp_" + "4" * 16,
            request=request if request is not None else declare_surface(),
            terminal_status=DeliveryTerminalStatus.SUCCEEDED,
            started_at=NOW,
            completed_at=NOW + timedelta(seconds=3),
        )
        values.update(overrides)
        return build_delivery_receipt(**values)

    def test_terminal_vocabulary_is_bounded_and_closed(self) -> None:
        self.assertEqual(
            [status.value for status in DeliveryTerminalStatus],
            [
                "succeeded",
                "refused",
                "failed_retryable",
                "failed_terminal",
                "cancelled",
            ],
        )
        self.assertEqual(len(DeliveryTerminalStatus), 5)
        self.assertEqual(
            [cls.value for cls in DeliveryTerminalClass],
            ["success", "refusal", "failure", "cancellation"],
        )

    def test_terminal_class_is_derived_from_status(self) -> None:
        self.assertIs(
            terminal_class_for(DeliveryTerminalStatus.SUCCEEDED), DeliveryTerminalClass.SUCCESS
        )
        self.assertIs(
            terminal_class_for(DeliveryTerminalStatus.REFUSED), DeliveryTerminalClass.REFUSAL
        )
        self.assertIs(
            terminal_class_for(DeliveryTerminalStatus.CANCELLED),
            DeliveryTerminalClass.CANCELLATION,
        )
        with self.assertRaises(ArtifactDeliveryExecutionError):
            terminal_class_for("not_a_status")

    def test_receipt_correlation_is_copied_exactly_from_the_request(self) -> None:
        request = declare_surface()
        receipt = self.receipt(request)
        self.assertTrue(receipt.correlates_with(request))
        self.assertEqual(receipt.attempt_ref, request.attempt_ref)
        self.assertEqual(receipt.delivery_intent_id, request.delivery_intent_id)
        self.assertEqual(receipt.artifact_ref, request.artifact_ref)
        self.assertEqual(receipt.trusted_channel_ref, request.trusted_channel_ref)
        self.assertEqual(receipt.terminal_class, DeliveryTerminalClass.SUCCESS)

    def test_receipt_from_another_attempt_does_not_correlate(self) -> None:
        request = declare_surface()
        other = ArtifactDeliveryExecutionRequest(
            attempt_ref="att_" + "6" * 16,
            delivery_intent_id=request.delivery_intent_id,
            artifact_ref=request.artifact_ref,
            delivery_kind=request.delivery_kind,
            trusted_channel_ref=request.trusted_channel_ref,
            workspace_ref=request.workspace_ref,
            run_ref=request.run_ref,
            requested_at=NOW,
        )
        self.assertFalse(self.receipt(other).correlates_with(request))

    def test_receipt_builder_requires_a_request(self) -> None:
        with self.assertRaises(ArtifactDeliveryExecutionError):
            build_delivery_receipt(
                receipt_ref="rcp_" + "4" * 16,
                request="not-a-request",  # type: ignore[arg-type]
                terminal_status=DeliveryTerminalStatus.SUCCEEDED,
                started_at=NOW,
                completed_at=NOW,
            )

    def test_refused_receipt_cannot_report_an_external_side_effect(self) -> None:
        with self.assertRaises(ArtifactDeliveryExecutionError) as ctx:
            self.receipt(
                terminal_status=DeliveryTerminalStatus.REFUSED,
                external_side_effect_count=1,
            )
        self.assertIn("refused delivery cannot report an external side effect", str(ctx.exception))

    def test_refused_receipt_with_zero_side_effects_is_accepted(self) -> None:
        receipt = self.receipt(terminal_status=DeliveryTerminalStatus.REFUSED)
        self.assertEqual(receipt.terminal_class, DeliveryTerminalClass.REFUSAL)
        self.assertEqual(receipt.external_side_effect_count, 0)

    def test_failed_receipt_requires_the_reused_provider_error_taxonomy(self) -> None:
        with self.assertRaises(ArtifactDeliveryExecutionError) as ctx:
            self.receipt(terminal_status=DeliveryTerminalStatus.FAILED_TERMINAL)
        self.assertIn("must carry the provider error taxonomy", str(ctx.exception))

    def test_provider_error_retryable_flag_must_agree_with_status(self) -> None:
        retryable_error = ConnectorProviderError(
            kind=ConnectorProviderErrorKind.UNAVAILABLE,
            error_ref="err_" + "1" * 12,
            retryable=True,
        )
        terminal_error = ConnectorProviderError(
            kind=ConnectorProviderErrorKind.INVALID_REQUEST,
            error_ref="err_" + "2" * 12,
            retryable=False,
        )
        retryable_receipt = self.receipt(
            terminal_status=DeliveryTerminalStatus.FAILED_RETRYABLE,
            provider_error=retryable_error,
        )
        self.assertEqual(retryable_receipt.terminal_class, DeliveryTerminalClass.FAILURE)
        self.assertTrue(retryable_receipt.public_projection()["provider_error_retryable"])

        with self.assertRaises(ArtifactDeliveryExecutionError) as ctx:
            self.receipt(
                terminal_status=DeliveryTerminalStatus.FAILED_TERMINAL,
                provider_error=retryable_error,
            )
        self.assertIn("disagrees with the terminal status", str(ctx.exception))

        terminal_receipt = self.receipt(
            terminal_status=DeliveryTerminalStatus.FAILED_TERMINAL,
            provider_error=terminal_error,
        )
        self.assertFalse(terminal_receipt.public_projection()["provider_error_retryable"])

    def test_succeeded_receipt_must_not_carry_a_provider_error(self) -> None:
        with self.assertRaises(ArtifactDeliveryExecutionError) as ctx:
            self.receipt(
                provider_error=ConnectorProviderError(
                    kind=ConnectorProviderErrorKind.UNKNOWN,
                    error_ref="err_" + "3" * 12,
                    retryable=False,
                )
            )
        self.assertIn("must not carry a provider error", str(ctx.exception))

    def test_completed_before_started_is_refused(self) -> None:
        with self.assertRaises(ArtifactDeliveryExecutionError) as ctx:
            self.receipt(completed_at=NOW - timedelta(seconds=1))
        self.assertIn("cannot precede started_at", str(ctx.exception))

    def test_negative_counters_are_refused(self) -> None:
        for field_name in ("retry_count", "external_side_effect_count"):
            with self.assertRaises(ArtifactDeliveryExecutionError):
                self.receipt(**{field_name: -1})

    def test_unknown_terminal_status_is_refused(self) -> None:
        with self.assertRaises(ArtifactDeliveryExecutionError):
            self.receipt(terminal_status="delivered")  # type: ignore[arg-type]


class SecurityAndNoEffectTests(unittest.TestCase):
    def test_request_projection_withholds_the_raw_channel_ref(self) -> None:
        request = declare_surface()
        projection = request.public_projection()
        rendered = str(projection)
        self.assertNotIn(request.trusted_channel_ref, rendered)
        self.assertNotIn(ACCOUNT_REF, rendered)
        self.assertNotIn(CONVERSATION_REF, rendered)
        self.assertTrue(projection["trusted_channel_ref_present"])
        self.assertFalse(projection["raw_channel_ref_in_projection"])
        self.assertFalse(projection["raw_destination_in_projection"])
        self.assertFalse(projection["delivery_execution"])
        self.assertFalse(projection["send_write_authority"])
        self.assertNotIn("trusted_channel_ref", projection)
        self.assertNotIn("channel_binding_ref", projection)
        # workspace_ref/run_ref are the intent's own provenance fields, projected
        # by #3605 as well; only the channel handle is withheld.
        self.assertEqual(projection["workspace_ref"], WORKSPACE_REF)

    def test_receipt_projection_leaks_no_raw_refs_or_secrets(self) -> None:
        request = declare_surface()
        receipt = build_delivery_receipt(
            receipt_ref="rcp_" + "4" * 16,
            request=request,
            terminal_status=DeliveryTerminalStatus.SUCCEEDED,
            started_at=NOW,
            completed_at=NOW + timedelta(seconds=1),
            external_result_ref="provider_op_" + "a" * 12,
        )
        projection = receipt.public_projection()
        rendered = str(projection)
        self.assertNotIn(receipt.trusted_channel_ref, rendered)
        self.assertNotIn("provider_op_", rendered)
        self.assertNotIn(ACCOUNT_REF, rendered)
        self.assertNotIn(WORKSPACE_REF, rendered)
        self.assertNotIn(CONVERSATION_REF, rendered)
        self.assertTrue(projection["trusted_channel_ref_present"])
        self.assertTrue(projection["external_result_ref_present"])
        self.assertFalse(projection["raw_channel_ref_in_projection"])
        self.assertFalse(projection["raw_external_result_ref_in_projection"])
        self.assertFalse(projection["raw_provider_error_in_projection"])
        self.assertFalse(projection["raw_destination_in_projection"])
        self.assertFalse(projection["connector_secret_in_projection"])
        self.assertFalse(projection["artifact_bytes_in_projection"])
        self.assertFalse(projection["delivery_execution"])
        self.assertFalse(projection["send_write_authority"])

    def test_raw_destination_ids_and_credentials_are_rejected_at_construction(self) -> None:
        request = declare_surface()
        for bad in (
            "123456789",
            "https://drive.google.com/file/d/abc",
            "bot123456:AAHsecret",
            "token:abc",
            "file:///c:/tmp/x",
            "C:\\Users\\x",
            "a b",
        ):
            with self.assertRaises(ArtifactDeliveryExecutionError):
                build_delivery_receipt(
                    receipt_ref="rcp_" + "4" * 16,
                    request=request,
                    terminal_status=DeliveryTerminalStatus.SUCCEEDED,
                    started_at=NOW,
                    completed_at=NOW,
                    external_result_ref=bad,
                )

    def test_adapter_port_has_no_implementation_in_this_module(self) -> None:
        implementations = [
            name
            for name, value in vars(ader).items()
            if isinstance(value, type)
            and hasattr(value, "deliver")
            and value is not ader.ArtifactDeliveryAdapterPort
        ]
        self.assertEqual(implementations, [])
        self.assertTrue(inspect.isclass(ArtifactDeliveryAdapterPort))

    def test_module_has_no_transport_send_or_secret_surface(self) -> None:
        source = pathlib.Path(ader.__file__).read_text(encoding="utf-8")
        for forbidden in (
            "import requests",
            "import httpx",
            "import urllib",
            "import socket",
            "import subprocess",
            "sendDocument",
            "send_document",
            "files.upload",
            "files().create",
            "boto3",
            "googleapiclient",
            "refresh_token",
            "access_token",
            "bot_token",
            "api.telegram.org",
            "sqlite3",
            "psycopg",
            "CREATE TABLE",
        ):
            self.assertNotIn(forbidden, source, forbidden)

    def test_zero_external_effects_while_binding_and_building_receipts(self) -> None:
        class CountingAdapter:
            """Deterministic in-memory fake port; must never be called by this module."""

            def __init__(self) -> None:
                self.calls: list[ArtifactDeliveryExecutionRequest] = []

            def deliver(self, request: ArtifactDeliveryExecutionRequest) -> ArtifactDeliveryReceipt:
                self.calls.append(request)
                raise AssertionError("this module must never execute a delivery")

        adapter = CountingAdapter()
        self.assertIsInstance(adapter, ArtifactDeliveryAdapterPort)

        registry = InMemoryDeliveryAttemptRegistry()
        for _ in range(10):
            request = declare_surface()
            try:
                registry.admit(request)
            except ArtifactDeliveryExecutionError:
                pass
            build_delivery_receipt(
                receipt_ref="rcp_" + "4" * 16,
                request=request,
                terminal_status=DeliveryTerminalStatus.CANCELLED,
                started_at=NOW,
                completed_at=NOW,
            )
        self.assertEqual(adapter.calls, [])

    def test_no_durable_store_or_schema_is_introduced(self) -> None:
        source = pathlib.Path(ader.__file__).read_text(encoding="utf-8")
        for forbidden in (
            "sqlite3",
            "psycopg",
            "CREATE TABLE",
            "json.dump",
            "shelve",
            "pickle",
            "open(",
            "write_text(",
            "os.makedirs",
            "pathlib",
        ):
            self.assertNotIn(forbidden, source, forbidden)
        self.assertFalse(ader.NEW_DURABLE_STORE)
        self.assertNotIn("_seen", source.split("class InMemoryDeliveryAttemptRegistry")[0])

    def test_module_invariants_are_pinned(self) -> None:
        self.assertFalse(ader.DELIVERY_EXECUTION_AUTHORITY)
        self.assertFalse(ader.SECOND_EXECUTION_AUTHORITY)
        self.assertFalse(ader.SECOND_REPLAY_AUTHORITY)
        self.assertFalse(ader.SECOND_APPROVAL_AUTHORITY)
        self.assertFalse(ader.SECOND_CONNECTOR_IDENTITY_AUTHORITY)
        self.assertFalse(ader.SECOND_ARTIFACT_AUTHORITY)
        self.assertFalse(ader.REQUEST_BODY_DESTINATION_AUTHORITY)
        self.assertFalse(ader.TOKEN_STRING_IS_AUTHORITY)
        self.assertTrue(ader.RE_RESOLUTION_REQUIRED)
        self.assertFalse(ader.EXTERNAL_SEND_AUTHORITY)
        self.assertFalse(ader.NETWORK_ACCESS)
        self.assertTrue(ader.PROVIDER_NEUTRAL_ADAPTER_PORT_ONLY)

    def test_error_type_is_a_contract_error(self) -> None:
        self.assertTrue(issubclass(ArtifactDeliveryExecutionError, ContractError))

    def test_receipt_ref_shape_is_bounded(self) -> None:
        request = declare_surface()
        with self.assertRaises(ArtifactDeliveryExecutionError):
            build_delivery_receipt(
                receipt_ref="../etc/passwd",
                request=request,
                terminal_status=DeliveryTerminalStatus.SUCCEEDED,
                started_at=NOW,
                completed_at=NOW,
            )


if __name__ == "__main__":
    unittest.main()
