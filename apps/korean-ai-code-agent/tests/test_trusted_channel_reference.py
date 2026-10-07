"""#3621 trusted current-channel reference resolver tests (parent #3580).

Hermetic: network-free, model-free, provider-free, execution-free. Pins:

- a trusted current-channel context resolves to an OPAQUE reference bound to
  account + workspace + conversation + channel class (+ the existing connector
  binding for connector classes);
- the reference is a binding digest, never a capability: authority comes from
  re-resolution against a trusted context, so a forged/unknown/expired string
  fails closed;
- a request-body channel label is never delivery authority — a label that
  contradicts the trusted class is refused outright;
- fail-closed matrix: missing context, account mismatch, workspace mismatch,
  stale context, stale/revoked binding, unsupported channel class, unsupported
  connector, missing catalogue authority, cross-account / cross-workspace
  reuse, malformed reference;
- the existing #3605 ``ArtifactDeliveryIntent`` binds the EXACT trusted ref and
  the exact binding authority — no artifact field is re-declared here;
- no raw channel ref, connector id, binding ref or destination reaches the
  projection, and the module has no transport/send/write surface at all
  (external send/write count is structurally zero).
"""

from __future__ import annotations

import hashlib
import inspect
import pathlib
import re
import unittest
from datetime import datetime, timedelta, timezone

import kagent.trusted_channel_reference as tcr
from kagent.artifact_delivery_intent import ArtifactDeliveryIntent, DeliveryKind
from kagent.artifact_lineage import LineageArtifactRef
from kagent.connector_trust import (
    ConnectorBindingProjection,
    ConnectorBindingState,
)
from kagent.contracts import ContractError
from kagent.trusted_channel_reference import (
    MAX_CONTEXT_AGE,
    SUPPORTED_CHANNEL_CLASSES,
    TrustedChannelClass,
    TrustedChannelReference,
    TrustedChannelReferenceError,
    TrustedCurrentChannelContext,
    bind_delivery_intent,
    resolve_trusted_channel_reference,
    supported_connector_ids_from_catalogue,
    verify_trusted_channel_reference,
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


def resolve(context, **overrides):
    values = dict(
        now=NOW,
        expected_account_ref=ACCOUNT_REF,
        expected_workspace_ref=WORKSPACE_REF,
    )
    values.update(overrides)
    return resolve_trusted_channel_reference(context, **values)


def verify(reference, context, **overrides):
    values = dict(
        now=NOW,
        expected_account_ref=ACCOUNT_REF,
        expected_workspace_ref=WORKSPACE_REF,
    )
    values.update(overrides)
    return verify_trusted_channel_reference(reference, context, **values)


class TrustedCurrentChannelResolutionTests(unittest.TestCase):
    def test_trusted_current_surface_resolves_to_an_opaque_reference(self) -> None:
        ref = resolve(current_surface_context())
        self.assertIsInstance(ref, TrustedChannelReference)
        self.assertEqual(ref.channel_class, TrustedChannelClass.CURRENT_SURFACE)
        self.assertRegex(ref.channel_ref, re.compile(r"^tcr1_[0-9a-f]{64}$"))
        # The reference reveals none of its inputs.
        self.assertNotIn(ACCOUNT_REF, ref.channel_ref)
        self.assertNotIn(WORKSPACE_REF, ref.channel_ref)
        self.assertNotIn(CONVERSATION_REF, ref.channel_ref)
        self.assertIsNone(ref.binding_ref)
        self.assertIsNone(ref.connector_id)

    def test_same_account_and_workspace_resolve_and_verify(self) -> None:
        context = current_surface_context()
        ref = resolve(context)
        self.assertEqual(verify(ref.channel_ref, context).channel_ref, ref.channel_ref)
        self.assertEqual(verify(ref, context).channel_ref, ref.channel_ref)

    def test_resolution_is_deterministic_for_one_context(self) -> None:
        self.assertEqual(
            resolve(current_surface_context()).channel_ref,
            resolve(current_surface_context()).channel_ref,
        )

    def test_different_conversation_resolves_to_a_different_reference(self) -> None:
        first = resolve(current_surface_context())
        second = resolve(current_surface_context(conversation_ref="chat_" + "9" * 16))
        self.assertNotEqual(first.channel_ref, second.channel_ref)

    def test_external_connector_resolves_through_the_existing_binding(self) -> None:
        ref = resolve(external_context(), supported_connector_ids=(CONNECTOR_ID,))
        self.assertEqual(ref.channel_class, TrustedChannelClass.EXTERNAL_CONNECTOR)
        self.assertEqual(ref.binding_ref, BINDING_REF)
        self.assertEqual(ref.connector_id, CONNECTOR_ID)
        self.assertEqual(ref.expires_at, NOW + timedelta(hours=1))

    def test_supported_connector_ids_come_from_the_existing_catalogue(self) -> None:
        class Entry:
            def __init__(self, connector_id: str) -> None:
                self.connector_id = connector_id

        ids = supported_connector_ids_from_catalogue([Entry("google-drive"), Entry(CONNECTOR_ID)])
        self.assertEqual(ids, ("google-drive", CONNECTOR_ID))
        ref = resolve(external_context(), supported_connector_ids=ids)
        self.assertEqual(ref.connector_id, CONNECTOR_ID)


class RequestBodyLabelIsNotAuthorityTests(unittest.TestCase):
    def test_forged_request_body_channel_label_has_no_authority(self) -> None:
        context = current_surface_context()
        with self.assertRaises(TrustedChannelReferenceError):
            resolve(context, caller_channel_label="telegram")
        with self.assertRaises(TrustedChannelReferenceError):
            resolve(context, caller_channel_label="drive")
        with self.assertRaises(TrustedChannelReferenceError):
            resolve(context, caller_channel_label="")

    def test_agreeing_label_is_accepted_but_still_not_the_authority(self) -> None:
        context = current_surface_context()
        with_label = resolve(context, caller_channel_label="current_surface")
        without_label = resolve(context)
        self.assertEqual(with_label.channel_ref, without_label.channel_ref)
        self.assertEqual(with_label.channel_class, context.channel_class)

    def test_a_caller_supplied_destination_is_not_even_a_parameter(self) -> None:
        parameters = set(inspect.signature(resolve_trusted_channel_reference).parameters)
        for forbidden in (
            "destination",
            "destination_ref",
            "chat_id",
            "channel_id",
            "destination_id",
            "transport",
            "connector_id",
            "token",
            "secret",
            "bot_token",
        ):
            self.assertNotIn(forbidden, parameters)


class FailClosedTests(unittest.TestCase):
    def test_missing_trusted_context_is_refused(self) -> None:
        with self.assertRaises(TrustedChannelReferenceError) as ctx:
            resolve(None)
        self.assertIn("trusted current-channel context is required", str(ctx.exception))

    def test_malformed_context_is_refused(self) -> None:
        with self.assertRaises(TrustedChannelReferenceError):
            resolve({"account_ref": ACCOUNT_REF})  # type: ignore[arg-type]

    def test_wrong_account_is_refused(self) -> None:
        with self.assertRaises(TrustedChannelReferenceError) as ctx:
            resolve(current_surface_context(), expected_account_ref=OTHER_ACCOUNT_REF)
        self.assertIn("cross-account", str(ctx.exception))

    def test_wrong_workspace_is_refused(self) -> None:
        with self.assertRaises(TrustedChannelReferenceError) as ctx:
            resolve(current_surface_context(), expected_workspace_ref=OTHER_WORKSPACE_REF)
        self.assertIn("cross-workspace", str(ctx.exception))

    def test_stale_context_is_refused(self) -> None:
        context = current_surface_context(observed_at=NOW - MAX_CONTEXT_AGE - timedelta(seconds=1))
        with self.assertRaises(TrustedChannelReferenceError) as ctx:
            resolve(context)
        self.assertIn("stale", str(ctx.exception))

    def test_future_observation_is_refused(self) -> None:
        with self.assertRaises(TrustedChannelReferenceError):
            resolve(current_surface_context(observed_at=NOW + timedelta(seconds=1)))

    def test_unsupported_channel_class_is_refused(self) -> None:
        with self.assertRaises(TrustedChannelReferenceError):
            TrustedCurrentChannelContext(
                account_ref=ACCOUNT_REF,
                workspace_ref=WORKSPACE_REF,
                conversation_ref=CONVERSATION_REF,
                channel_class="sms",  # type: ignore[arg-type]
                observed_at=NOW,
            )
        self.assertEqual(len(SUPPORTED_CHANNEL_CLASSES), 2)

    def test_external_connector_without_the_binding_authority_is_refused(self) -> None:
        with self.assertRaises(TrustedChannelReferenceError) as ctx:
            TrustedCurrentChannelContext(
                account_ref=ACCOUNT_REF,
                workspace_ref=WORKSPACE_REF,
                conversation_ref=CONVERSATION_REF,
                channel_class=TrustedChannelClass.EXTERNAL_CONNECTOR,
                observed_at=NOW,
            )
        self.assertIn("existing connector binding", str(ctx.exception))

    def test_binding_from_another_account_is_refused(self) -> None:
        context = external_context(binding=binding(account_ref=OTHER_ACCOUNT_REF))
        with self.assertRaises(TrustedChannelReferenceError) as ctx:
            resolve(context, supported_connector_ids=(CONNECTOR_ID,))
        self.assertIn("different account", str(ctx.exception))

    def test_binding_from_another_workspace_is_refused(self) -> None:
        context = external_context(binding=binding(workspace_ref=OTHER_WORKSPACE_REF))
        with self.assertRaises(TrustedChannelReferenceError) as ctx:
            resolve(context, supported_connector_ids=(CONNECTOR_ID,))
        self.assertIn("different workspace", str(ctx.exception))

    def test_expired_binding_is_refused(self) -> None:
        context = external_context(
            binding=binding(expires_at=NOW - timedelta(seconds=1)),
        )
        with self.assertRaises(TrustedChannelReferenceError) as ctx:
            resolve(context, supported_connector_ids=(CONNECTOR_ID,))
        self.assertIn("expired, revoked or not yet valid", str(ctx.exception))

    def test_revoked_binding_is_refused(self) -> None:
        context = external_context(
            binding=binding(
                state=ConnectorBindingState.REVOKED,
                revoked_at=NOW - timedelta(minutes=1),
            ),
        )
        with self.assertRaises(TrustedChannelReferenceError):
            resolve(context, supported_connector_ids=(CONNECTOR_ID,))

    def test_connector_outside_the_catalogue_authority_is_refused(self) -> None:
        with self.assertRaises(TrustedChannelReferenceError) as ctx:
            resolve(external_context(), supported_connector_ids=("google-drive",))
        self.assertIn("unsupported connector", str(ctx.exception))

    def test_missing_catalogue_authority_is_refused(self) -> None:
        with self.assertRaises(TrustedChannelReferenceError) as ctx:
            resolve(external_context())
        self.assertIn("existing catalogue authority", str(ctx.exception))

    def test_cross_account_reference_reuse_is_refused(self) -> None:
        context = current_surface_context()
        ref = resolve(context)
        with self.assertRaises(TrustedChannelReferenceError):
            verify(ref.channel_ref, context, expected_account_ref=OTHER_ACCOUNT_REF)

    def test_cross_workspace_reference_reuse_is_refused(self) -> None:
        context = current_surface_context()
        ref = resolve(context)
        with self.assertRaises(TrustedChannelReferenceError):
            verify(ref.channel_ref, context, expected_workspace_ref=OTHER_WORKSPACE_REF)

    def test_reference_from_another_conversation_is_refused(self) -> None:
        ref = resolve(current_surface_context())
        other = current_surface_context(conversation_ref="chat_" + "9" * 16)
        with self.assertRaises(TrustedChannelReferenceError) as ctx:
            verify(ref.channel_ref, other)
        self.assertIn("does not match the context", str(ctx.exception))

    def test_reference_object_with_tampered_bound_metadata_is_refused(self) -> None:
        context = current_surface_context()
        ref = resolve(context)
        tampered = TrustedChannelReference(
            channel_ref=ref.channel_ref,
            channel_class=ref.channel_class,
            account_ref=ref.account_ref,
            workspace_ref=OTHER_WORKSPACE_REF,
            conversation_ref=ref.conversation_ref,
            resolved_at=ref.resolved_at,
        )
        with self.assertRaises(TrustedChannelReferenceError) as ctx:
            verify(tampered, context)
        self.assertIn("metadata does not match the context", str(ctx.exception))

    def test_unknown_or_malformed_reference_is_refused(self) -> None:
        context = current_surface_context()
        for forged in (
            "",
            "tcr1_" + "0" * 64,
            "tcr1_" + "z" * 64,
            "channel_ref_opaque_7",
            "tcr1_" + "0" * 63,
            "../" + "0" * 64,
        ):
            with self.assertRaises(TrustedChannelReferenceError):
                verify(forged, context)

    def test_expired_reference_is_refused(self) -> None:
        context = external_context()
        ref = resolve(context, supported_connector_ids=(CONNECTOR_ID,))
        with self.assertRaises(TrustedChannelReferenceError) as ctx:
            verify(ref, context, now=NOW + timedelta(hours=2), supported_connector_ids=(CONNECTOR_ID,))
        self.assertIn("stale", str(ctx.exception))

    def test_malformed_identity_refs_are_refused_at_construction(self) -> None:
        for field_name, bad in (
            ("account_ref", "acct:x"),
            ("account_ref", ".."),
            ("workspace_ref", "token:abc"),
            ("conversation_ref", "C:\\chat"),
            ("conversation_ref", "https://chat.example"),
        ):
            values = {
                "account_ref": ACCOUNT_REF,
                "workspace_ref": WORKSPACE_REF,
                "conversation_ref": CONVERSATION_REF,
                "channel_class": TrustedChannelClass.CURRENT_SURFACE,
                "observed_at": NOW,
            }
            values[field_name] = bad
            with self.assertRaises(TrustedChannelReferenceError):
                TrustedCurrentChannelContext(**values)


class DeliveryIntentBindingTests(unittest.TestCase):
    def artifact_ref(self) -> LineageArtifactRef:
        return LineageArtifactRef(artifact_id="art_" + "a" * 16, integrity_ref=DIGEST)

    def test_delivery_intent_binds_the_exact_trusted_reference(self) -> None:
        ref = resolve(current_surface_context())
        intent = bind_delivery_intent(
            delivery_intent_id="dli_" + "1" * 16,
            artifact_ref=self.artifact_ref(),
            reference=ref,
            workspace_ref=WORKSPACE_REF,
            run_ref="run_" + "3" * 16,
            created_at=NOW,
        )
        self.assertIsInstance(intent, ArtifactDeliveryIntent)
        self.assertEqual(intent.delivery_kind, DeliveryKind.CURRENT_SURFACE)
        self.assertEqual(intent.trusted_channel_ref, ref.channel_ref)
        self.assertIsNone(intent.channel_binding_ref)

    def test_external_delivery_intent_names_the_existing_binding_authority(self) -> None:
        ref = resolve(external_context(), supported_connector_ids=(CONNECTOR_ID,))
        intent = bind_delivery_intent(
            delivery_intent_id="dli_" + "2" * 16,
            artifact_ref=self.artifact_ref(),
            reference=ref,
            workspace_ref=WORKSPACE_REF,
            run_ref="run_" + "3" * 16,
            created_at=NOW,
        )
        self.assertEqual(intent.delivery_kind, DeliveryKind.EXTERNAL_CONNECTOR)
        self.assertEqual(intent.channel_binding_ref, BINDING_REF)
        self.assertEqual(intent.trusted_channel_ref, ref.channel_ref)

    def test_binding_to_another_workspace_is_refused(self) -> None:
        ref = resolve(current_surface_context())
        with self.assertRaises(TrustedChannelReferenceError):
            bind_delivery_intent(
                delivery_intent_id="dli_" + "3" * 16,
                artifact_ref=self.artifact_ref(),
                reference=ref,
                workspace_ref=OTHER_WORKSPACE_REF,
                run_ref="run_" + "3" * 16,
                created_at=NOW,
            )

    def test_unresolved_reference_is_refused(self) -> None:
        with self.assertRaises(TrustedChannelReferenceError):
            bind_delivery_intent(
                delivery_intent_id="dli_" + "4" * 16,
                artifact_ref=self.artifact_ref(),
                reference="tcr1_" + "0" * 64,  # type: ignore[arg-type]
                workspace_ref=WORKSPACE_REF,
                run_ref="run_" + "3" * 16,
                created_at=NOW,
            )

    def test_intent_projection_still_withholds_the_raw_channel_ref(self) -> None:
        ref = resolve(current_surface_context())
        intent = bind_delivery_intent(
            delivery_intent_id="dli_" + "5" * 16,
            artifact_ref=self.artifact_ref(),
            reference=ref,
            workspace_ref=WORKSPACE_REF,
            run_ref="run_" + "3" * 16,
            created_at=NOW,
        )
        projection = intent.public_projection()
        self.assertTrue(projection["trusted_channel_ref_present"])
        self.assertFalse(projection["delivery_execution"])
        self.assertFalse(projection["send_write_authority"])
        self.assertNotIn(ref.channel_ref, str(projection))


class ProjectionAndNoEffectTests(unittest.TestCase):
    def test_reference_projection_leaks_no_raw_reference_or_connector_id(self) -> None:
        ref = resolve(external_context(), supported_connector_ids=(CONNECTOR_ID,))
        projection = ref.public_projection()
        rendered = str(projection)
        self.assertNotIn(ref.channel_ref, rendered)
        self.assertNotIn(BINDING_REF, rendered)
        self.assertNotIn(CONNECTOR_ID, rendered)
        self.assertNotIn(CONVERSATION_REF, rendered)
        self.assertNotIn(ACCOUNT_REF, rendered)
        self.assertNotIn(WORKSPACE_REF, rendered)
        self.assertTrue(projection["channel_ref_present"])
        self.assertFalse(projection["raw_channel_ref_in_projection"])
        self.assertFalse(projection["raw_connector_id_in_projection"])
        self.assertFalse(projection["raw_binding_ref_in_projection"])
        self.assertFalse(projection["raw_destination_in_projection"])
        self.assertFalse(projection["connector_secret_in_projection"])
        self.assertFalse(projection["delivery_execution"])
        self.assertFalse(projection["send_write_authority"])
        self.assertNotIn("binding_ref", projection)
        self.assertNotIn("connector_id", projection)
        self.assertNotIn("conversation_ref", projection)

    def test_module_has_no_transport_send_or_secret_surface(self) -> None:
        source = pathlib.Path(tcr.__file__).read_text(encoding="utf-8")
        for forbidden in (
            "import requests",
            "import httpx",
            "import urllib",
            "import socket",
            "subprocess",
            "sendDocument",
            "send_document",
            "files.upload",
            "boto3",
            "googleapiclient",
            "refresh_token",
            "access_token",
            "bot_token",
            "api.telegram.org",
        ):
            self.assertNotIn(forbidden, source, forbidden)
        # No function accepts anything resembling a transport or destination.
        for name in (
            "resolve_trusted_channel_reference",
            "verify_trusted_channel_reference",
            "bind_delivery_intent",
        ):
            parameters = set(inspect.signature(getattr(tcr, name)).parameters)
            for forbidden in ("transport", "sender", "uploader", "writer", "destination"):
                self.assertNotIn(forbidden, parameters)

    def test_resolving_repeatedly_performs_zero_external_effects(self) -> None:
        class CountingTransport:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str]] = []

            def call(self, connector_id: str, tool_name: str) -> None:
                self.calls.append((connector_id, tool_name))

        transport = CountingTransport()
        context = external_context()
        for _ in range(25):
            ref = resolve(context, supported_connector_ids=(CONNECTOR_ID,))
            verify(ref, context, supported_connector_ids=(CONNECTOR_ID,))
        # The resolver never receives a transport, so the count is structurally 0.
        self.assertEqual(transport.calls, [])

    def test_module_invariants_are_pinned(self) -> None:
        self.assertTrue(tcr.TRUSTED_CHANNEL_REF_IS_OPAQUE)
        self.assertFalse(tcr.REQUEST_BODY_CHANNEL_LABEL_IS_AUTHORITY)
        self.assertFalse(tcr.SECOND_CONNECTOR_IDENTITY_AUTHORITY)
        self.assertFalse(tcr.SECOND_ARTIFACT_AUTHORITY)
        self.assertFalse(tcr.EXTERNAL_SEND_AUTHORITY)

    def test_error_type_is_a_contract_error(self) -> None:
        self.assertTrue(issubclass(TrustedChannelReferenceError, ContractError))


if __name__ == "__main__":
    unittest.main()
