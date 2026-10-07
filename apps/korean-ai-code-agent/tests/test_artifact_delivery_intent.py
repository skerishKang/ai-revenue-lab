"""#3605 provider-neutral artifact delivery intent contract tests.

Network-free, model-free, provider-free, execution-free. Pins:

- artifact reference is REQUIRED and is consumed from the #3599/#3602
  ``LineageArtifactRef`` (which itself consumes the #3594 record) — no artifact
  field is re-declared here;
- ``lineage_ref`` is OPTIONAL and carries only the opaque lineage id, never the
  lineage metadata;
- run/workspace provenance is required;
- ``trusted_channel_ref`` is consumed, not minted: caller-minted raw provider
  destinations (bare numeric ids, local paths, UNC, ``file://``, URLs with
  credential/query material, credential-shaped refs) fail closed;
- provider neutrality is structural: the record and its projection expose no
  provider-specific field name and the module imports no connector/provider
  module;
- the in-app current surface vs external connector distinction is carried by
  ``DeliveryKind`` without provider logic, and external delivery must name the
  existing channel binding authority;
- ``approval_ref`` is an opaque reference only; no new approval authority;
- the public projection never leaks the raw channel ref, local paths, secrets
  or provider destinations, and asserts the no-execution / no-send flags.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import unittest
from datetime import datetime, timedelta, timezone

from kagent.artifact_delivery_intent import (
    ArtifactDeliveryIntent,
    ArtifactDeliveryIntentError,
    DeliveryKind,
    declare_delivery_intent,
)
from kagent.artifact_lineage import LineageArtifactRef
from kagent.artifact_registration import register_canonical_artifact
from kagent.contracts import ContractError


DIGEST = hashlib.sha256(b"delivery-intent-artifact").hexdigest()
CREATED_AT = datetime(2026, 10, 7, 5, 0, tzinfo=timezone.utc)
CHANNEL_REF = "channel_ref_opaque_7"


def artifact_ref() -> LineageArtifactRef:
    return LineageArtifactRef(artifact_id="art_" + "a" * 16, integrity_ref=DIGEST)


def intent(**overrides) -> ArtifactDeliveryIntent:
    values = dict(
        delivery_intent_id="dli_" + "1" * 16,
        artifact_ref=artifact_ref(),
        delivery_kind=DeliveryKind.CURRENT_SURFACE,
        trusted_channel_ref=CHANNEL_REF,
        workspace_ref="ws_" + "2" * 16,
        run_ref="run_" + "3" * 16,
        created_at=CREATED_AT,
    )
    values.update(overrides)
    return ArtifactDeliveryIntent(**values)


class DeliveryKindShapeTests(unittest.TestCase):
    def test_current_surface_intent_is_valid(self) -> None:
        rec = intent()
        self.assertEqual(rec.delivery_kind, DeliveryKind.CURRENT_SURFACE)
        self.assertFalse(rec.requires_external_approval)
        self.assertIsNone(rec.channel_binding_ref)

    def test_external_connector_intent_requires_binding_authority(self) -> None:
        with self.assertRaises(ArtifactDeliveryIntentError) as ctx:
            intent(delivery_kind=DeliveryKind.EXTERNAL_CONNECTOR)
        self.assertIn("channel_binding_ref", str(ctx.exception))
        rec = intent(
            delivery_kind=DeliveryKind.EXTERNAL_CONNECTOR,
            channel_binding_ref="binding_ref_opaque_4",
        )
        self.assertTrue(rec.requires_external_approval)
        self.assertEqual(rec.channel_binding_ref, "binding_ref_opaque_4")

    def test_durable_store_intent_is_valid_and_provider_neutral(self) -> None:
        rec = intent(delivery_kind=DeliveryKind.DURABLE_STORE)
        self.assertEqual(rec.delivery_kind, DeliveryKind.DURABLE_STORE)
        self.assertFalse(rec.requires_external_approval)

    def test_delivery_kind_accepts_its_wire_value(self) -> None:
        rec = intent(delivery_kind="durable_store")
        self.assertEqual(rec.delivery_kind, DeliveryKind.DURABLE_STORE)

    def test_provider_named_delivery_kind_is_rejected(self) -> None:
        # The delivery class is never a provider name: there is no
        # "telegram"/"drive"/"sheet" kind to select.
        for bad in ("telegram", "drive", "google_sheets", "telegram.send_document", ""):
            with self.assertRaises(ArtifactDeliveryIntentError):
                intent(delivery_kind=bad)

    def test_created_at_is_normalized_to_utc(self) -> None:
        rec = intent(created_at=datetime(2026, 10, 7, 14, 0, tzinfo=timezone(timedelta(hours=9))))
        self.assertEqual(rec.created_at, CREATED_AT)
        self.assertEqual(rec.public_projection()["created_at"], "2026-10-07T05:00:00Z")


class ArtifactReferenceTests(unittest.TestCase):
    def test_artifact_reference_is_required(self) -> None:
        for bad in (None, "", "art_" + "a" * 16, 123, object()):
            with self.assertRaises(ArtifactDeliveryIntentError):
                intent(artifact_ref=bad)

    def test_malformed_artifact_reference_fails_closed(self) -> None:
        # A wrong-typed reference is rejected by this contract...
        for bad in ("bad id", "a" * 200, "-lead", "아이디"):
            with self.assertRaises(ArtifactDeliveryIntentError):
                intent(artifact_ref=bad)
        # ...while the referenced ref type keeps owning its own content
        # validation (both stay in the ContractError family).
        for bad in ("bad id", "a" * 200, "-lead"):
            with self.assertRaises(ContractError):
                LineageArtifactRef(artifact_id=bad, integrity_ref=DIGEST)
        for bad in ("", "ABC", hashlib.md5(b"x").hexdigest(), "z" * 64):
            with self.assertRaises(ContractError):
                LineageArtifactRef(artifact_id="art_x", integrity_ref=bad)

    def test_canonical_record_is_consumed_directly(self) -> None:
        record = register_canonical_artifact(
            artifact_id="art_" + "c" * 16,
            artifact_kind="claw.generated_document",
            filename="quote.pdf",
            media_type="application/pdf",
            size_bytes=4096,
            integrity_ref=DIGEST,
            workspace_ref="ws_" + "2" * 16,
            run_ref="run_" + "3" * 16,
        )
        rec = declare_delivery_intent(
            delivery_intent_id="dli_" + "5" * 16,
            artifact_ref=record,
            delivery_kind=DeliveryKind.CURRENT_SURFACE,
            trusted_channel_ref=CHANNEL_REF,
            workspace_ref="ws_" + "2" * 16,
            run_ref="run_" + "3" * 16,
            created_at=CREATED_AT,
        )
        self.assertEqual(rec.artifact_id, record.artifact_id)
        self.assertEqual(rec.artifact_integrity_ref, record.integrity_ref)

    def test_lineage_ref_is_optional_and_id_only(self) -> None:
        self.assertIsNone(intent().lineage_ref)
        rec = intent(lineage_ref="lin_" + "6" * 16)
        self.assertEqual(rec.lineage_ref, "lin_" + "6" * 16)
        projection = rec.public_projection()
        self.assertEqual(projection["lineage_ref"], "lin_" + "6" * 16)
        # Only the opaque id crosses; no lineage metadata is duplicated here.
        for field in ("source_artifact_id", "output_artifact_ids", "transformation_kind", "outputs"):
            self.assertNotIn(field, projection)

    def test_malformed_lineage_ref_is_rejected(self) -> None:
        for bad in ("", "has space", "../escape", "a" * 200, 123):
            with self.assertRaises(ArtifactDeliveryIntentError):
                intent(lineage_ref=bad)

    def test_run_and_workspace_provenance_is_required(self) -> None:
        for field in ("workspace_ref", "run_ref"):
            for bad in ("", None, "has space", "../escape", "a\x00b", "x" * 400, 123):
                with self.assertRaises(ArtifactDeliveryIntentError):
                    intent(**{field: bad})


class ConsumedNotMintedTests(unittest.TestCase):
    def test_caller_minted_raw_provider_ids_are_rejected(self) -> None:
        for bad in ("1001234567890", "-1001234567890", "+8210", "0", "1234567890123456789012"):
            with self.assertRaises(ArtifactDeliveryIntentError) as ctx:
                intent(trusted_channel_ref=bad)
            self.assertIn("bare provider id", str(ctx.exception))

    def test_local_path_and_file_uri_destinations_are_rejected(self) -> None:
        for bad in (
            "E:\\work\\quotation.pdf",
            "G:/downloads/quote.pdf",
            "\\\\server\\share\\quote.pdf",
            "/abs/path/quote.pdf",
            "file:///etc/passwd",
            "file://C:/secret/quote.pdf",
            "../escape/ref",
        ):
            with self.assertRaises(ArtifactDeliveryIntentError):
                intent(trusted_channel_ref=bad)

    def test_url_and_query_credential_material_is_rejected(self) -> None:
        for bad in (
            "https://api.example.test/v1/files?token=abc123",
            "http://example.test/private",
            "https://drive.google.com/file/d/abc",
            "key=AIzaSyD-1234567890",
            "chat=-1001234567890;bot=123:ABC",
        ):
            with self.assertRaises(ArtifactDeliveryIntentError):
                intent(trusted_channel_ref=bad)

    def test_no_lexical_provider_detection_is_claimed(self) -> None:
        """The contract does not claim to detect a provider from a token.

        A scheme-less token that carries no URL/credential/local-path syntax is
        lexically indistinguishable from any other opaque host handle, so it is
        accepted *as an opaque reference* — exactly as #3605 warns against
        claiming semantic secrecy from a blacklist. The protections are
        structural, and this test pins them: the value is never interpreted,
        never resolved, never executed, and never projected.
        """
        provider_shaped = "drive.google.com/file/d/abc"
        rec = intent(trusted_channel_ref=provider_shaped)
        self.assertEqual(rec.trusted_channel_ref, provider_shaped)
        encoded = json.dumps(rec.public_projection(), ensure_ascii=False)
        self.assertNotIn(provider_shaped, encoded)
        self.assertNotIn("google", encoded.lower())
        projection = rec.public_projection()
        self.assertEqual(projection["delivery_execution"], False)
        self.assertEqual(projection["send_write_authority"], False)
        self.assertEqual(projection["caller_minted_destination"], False)

    def test_credential_shaped_refs_are_rejected(self) -> None:
        for bad in (
            "secret:abc",
            "oauth:abc123",
            "api_key:example",
            "apikey:example",
            "token:abc",
            "bearer:xyz",
            "password:xyz",
            "credential:xyz",
            "Bearer abcdef123456",
            "token sk-live-abcdef0123456789",
        ):
            with self.assertRaises(ArtifactDeliveryIntentError):
                intent(trusted_channel_ref=bad)

    def test_binding_and_approval_refs_use_the_same_opaque_rules(self) -> None:
        for field in ("channel_binding_ref", "approval_ref"):
            for bad in ("1001234567890", "E:\\tmp\\x", "file:///etc/passwd", "token:abc", "has space"):
                with self.assertRaises(ArtifactDeliveryIntentError):
                    intent(**{field: bad})

    def test_opaque_host_refs_remain_accepted(self) -> None:
        rec = intent(
            delivery_kind=DeliveryKind.EXTERNAL_CONNECTOR,
            trusted_channel_ref="channel_ref_opaque_7",
            channel_binding_ref="binding_ref_opaque_4",
            approval_ref="approval_ref_opaque_2",
        )
        self.assertEqual(rec.trusted_channel_ref, "channel_ref_opaque_7")
        self.assertEqual(rec.channel_binding_ref, "binding_ref_opaque_4")
        self.assertEqual(rec.approval_ref, "approval_ref_opaque_2")

    def test_missing_or_oversized_channel_ref_is_rejected(self) -> None:
        for bad in (None, "", "   ", 123, "x" * 600, "a\x00b"):
            with self.assertRaises(ArtifactDeliveryIntentError):
                intent(trusted_channel_ref=bad)

    def test_malformed_intent_id_is_rejected(self) -> None:
        for bad in ("", "-lead", "bad id", "a" * 200, "아이디", None, 123):
            with self.assertRaises(ArtifactDeliveryIntentError):
                intent(delivery_intent_id=bad)

    def test_naive_or_non_datetime_created_at_is_rejected(self) -> None:
        for bad in (datetime(2026, 10, 7, 5, 0), "2026-10-07T05:00:00Z", None, 123):
            with self.assertRaises(ArtifactDeliveryIntentError):
                intent(created_at=bad)


class StructuralNeutralityTests(unittest.TestCase):
    def full_intent(self) -> ArtifactDeliveryIntent:
        return intent(
            delivery_kind=DeliveryKind.EXTERNAL_CONNECTOR,
            channel_binding_ref="binding_ref_opaque_4",
            approval_ref="approval_ref_opaque_2",
            lineage_ref="lin_" + "6" * 16,
        )

    def test_no_provider_specific_field_name_exists(self) -> None:
        # Provider neutrality is structural: neither the record nor its
        # projection names a provider, a chat id, a token or a secret.
        names = set(ArtifactDeliveryIntent.__dataclass_fields__)
        names |= set(self.full_intent().public_projection())
        forbidden_tokens = (
            "telegram",
            "drive",
            "oauth",
            "token",
            "secret",
            "chat_id",
            "chatid",
            "bot",
            "sheet",
            "slack",
            "kakao",
            "discord",
            "s3",
            "r2",
            "bucket",
            "object_key",
        )
        for name in names:
            lowered = name.lower()
            for token in forbidden_tokens:
                self.assertNotIn(token, lowered, f"{name} leaks provider-specific naming")

    def test_module_imports_no_connector_or_provider_module(self) -> None:
        import ast
        import kagent.artifact_delivery_intent as module

        source = pathlib.Path(module.__file__).read_text(encoding="utf-8")
        imported: list[str] = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        joined = " ".join(imported)
        for token in (
            "telegram",
            "google_drive",
            "drive_",
            "connector_platform",
            "connector_trust",
            "artifact_export",
            "httpx",
            "requests",
            "urllib",
            "socket",
        ):
            self.assertNotIn(token, joined, f"unexpected provider/transport import: {token}")

    def test_module_public_surface_is_exactly_the_declared_api(self) -> None:
        # No transport/execution entry point was added alongside the contract.
        import ast
        import kagent.artifact_delivery_intent as module

        source = pathlib.Path(module.__file__).read_text(encoding="utf-8")
        defined = {
            node.name
            for node in ast.parse(source).body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and not node.name.startswith("_")
        }
        self.assertEqual(
            defined,
            {
                "ArtifactDeliveryIntentError",
                "DeliveryKind",
                "ArtifactDeliveryIntent",
                "declare_delivery_intent",
            },
        )

    def test_no_destination_collection_exists(self) -> None:
        # Exactly one destination per intent, so no unbounded list can exist.
        for field in ArtifactDeliveryIntent.__dataclass_fields__:
            self.assertNotIn("targets", field)
            self.assertNotIn("destinations", field)


class PublicProjectionTests(unittest.TestCase):
    def full_intent(self) -> ArtifactDeliveryIntent:
        return intent(
            delivery_kind=DeliveryKind.EXTERNAL_CONNECTOR,
            channel_binding_ref="binding_ref_opaque_4",
            approval_ref="approval_ref_opaque_2",
            lineage_ref="lin_" + "6" * 16,
        )

    def test_projection_is_json_safe_and_metadata_only(self) -> None:
        projection = self.full_intent().public_projection()
        encoded = json.dumps(projection, ensure_ascii=False)
        self.assertIsInstance(encoded, str)
        self.assertEqual(projection["contract_version"], "claw-artifact-delivery-intent.v1")
        self.assertEqual(projection["artifact_id"], artifact_ref().artifact_id)
        self.assertEqual(projection["artifact_integrity_ref"], DIGEST)
        self.assertEqual(projection["delivery_kind"], "external_connector")
        self.assertEqual(projection["trusted_channel_ref_present"], True)
        self.assertEqual(projection["caller_minted_destination"], False)
        self.assertEqual(projection["model_selected_destination"], False)
        self.assertEqual(projection["delivery_execution"], False)
        self.assertEqual(projection["send_write_authority"], False)

    def test_raw_channel_reference_is_never_projected(self) -> None:
        rec = intent(trusted_channel_ref="channel_ref_opaque_7")
        encoded = json.dumps(rec.public_projection(), ensure_ascii=False)
        self.assertNotIn("channel_ref_opaque_7", encoded)
        self.assertNotIn("trusted_channel_ref", rec.public_projection())

    def test_no_local_absolute_paths_in_projection(self) -> None:
        encoded = json.dumps(self.full_intent().public_projection(), ensure_ascii=False)
        for forbidden in ("E:\\", "G:\\", "C:\\", "\\\\", "file://"):
            self.assertNotIn(forbidden, encoded)

    def test_no_secret_or_credential_material_in_projection(self) -> None:
        encoded = json.dumps(self.full_intent().public_projection(), ensure_ascii=False).lower()
        for forbidden in (
            "bearer ",
            "api_key",
            "apikey",
            "password",
            "secret",
            "authorization:",
            "oauth",
            "file://",
            "location_ref",
            "chat_id",
            "bot_token",
        ):
            self.assertNotIn(forbidden, encoded)

    def test_optional_keys_are_omitted_when_absent(self) -> None:
        projection = intent().public_projection()
        for field in ("lineage_ref", "channel_binding_ref", "approval_ref"):
            self.assertNotIn(field, projection)

    def test_projection_is_deterministic(self) -> None:
        first = json.dumps(self.full_intent().public_projection(), sort_keys=True)
        second = json.dumps(self.full_intent().public_projection(), sort_keys=True)
        self.assertEqual(first, second)


class AuthorityBoundaryTests(unittest.TestCase):
    def test_no_approval_authority_is_created(self) -> None:
        import kagent.artifact_delivery_intent as module

        # The module names no approval state machine, store or decision type.
        for name in dir(module):
            if name.startswith("_"):
                continue
            self.assertNotIn("ApprovalDecision", name)
            self.assertNotIn("ApprovalStore", name)
            self.assertNotIn("ApprovalState", name)
            self.assertNotIn("ApprovalPause", name)

    def test_requires_external_approval_describes_does_not_decide(self) -> None:
        rec = intent(
            delivery_kind=DeliveryKind.EXTERNAL_CONNECTOR,
            channel_binding_ref="binding_ref_opaque_4",
        )
        self.assertIsInstance(rec.requires_external_approval, bool)
        # An external intent with no approval_ref is still a valid *intent*:
        # approval is decided by the existing authority, not inferred here.
        self.assertIsNone(rec.approval_ref)

    def test_frozen_intent_cannot_be_mutated(self) -> None:
        rec = intent()
        with self.assertRaises(Exception):
            rec.delivery_intent_id = "mutated"  # type: ignore[misc]
        with self.assertRaises(Exception):
            rec.trusted_channel_ref = "mutated"  # type: ignore[misc]

    def test_contract_error_family_is_preserved(self) -> None:
        self.assertTrue(issubclass(ArtifactDeliveryIntentError, ContractError))


class DependencyRegressionTests(unittest.TestCase):
    def test_lineage_ref_type_is_reused_not_redeclared(self) -> None:
        rec = intent()
        self.assertIsInstance(rec.artifact_ref, LineageArtifactRef)

    def test_lineage_contract_still_holds(self) -> None:
        from kagent.artifact_lineage import ArtifactLineage, declare_lineage

        lin = declare_lineage(
            lineage_id="lin_" + "7" * 16,
            source=artifact_ref(),
            transformation_kind="claw.convert.xlsx_to_pdf",
            workspace_ref="ws_" + "2" * 16,
            run_ref="run_" + "3" * 16,
            created_at=CREATED_AT,
        )
        self.assertIsInstance(lin, ArtifactLineage)
        rec = intent(lineage_ref=lin.lineage_id, artifact_ref=lin.source)
        self.assertEqual(rec.lineage_ref, lin.lineage_id)
        self.assertEqual(rec.artifact_id, lin.source_artifact_id)

    def test_canonical_artifact_contract_still_holds(self) -> None:
        from kagent.artifact_registration import ArtifactLifecycle, ArtifactLocation

        record = register_canonical_artifact(
            artifact_id="art_" + "d" * 16,
            artifact_kind="claw.generated_document",
            filename="quote.pdf",
            media_type="application/pdf",
            size_bytes=2048,
            integrity_ref=DIGEST,
            lifecycle=ArtifactLifecycle.DURABLE,
            durable_location=ArtifactLocation(location_kind="r2", location_ref="tenants/t/art/x"),
        )
        self.assertEqual(record.public_projection()["durable_location"]["available"], True)
        rec = intent(artifact_ref=record)
        projection = rec.public_projection()
        self.assertEqual(projection["artifact_id"], record.artifact_id)
        # The canonical record's own metadata never crosses into the intent.
        for field in ("filename", "media_type", "size_bytes", "artifact_kind", "lifecycle"):
            self.assertNotIn(field, projection)


if __name__ == "__main__":
    unittest.main()
