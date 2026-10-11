"""#3599 canonical source -> working-copy -> output artifact lineage tests.

Network-free, model-free, provider-free. Pins:

- the five legal shapes: source-only, source->working, source->output,
  source->working->output, multiple outputs;
- SOURCE_IDENTITY_PRESERVED / SOURCE_INTEGRITY_PRESERVED (source id and digest
  are pinned and never rewritten);
- WORKING_COPY_OPTIONAL=YES / WORKING_COPY_REPLACES_SOURCE=NO (a working
  canonical artifact may not alias the source id; the opaque working
  representation token may not alias it either);
- OUTPUTS_DISTINCT_CANONICAL_ARTIFACTS=YES (no duplicate output, no source or
  working artifact listed as an output);
- MULTIPLE_OUTPUT_BOUND (MAX_OUTPUT_ARTIFACTS, no unbounded list);
- fail-closed rejection of malformed refs, local absolute paths and
  credential-shaped material;
- a safe public projection: JSON-safe, metadata-only, no raw bytes, no local
  absolute paths, no secrets, no raw working-representation token, and no
  re-copy of the #3594 artifact metadata;
- the #3594 canonical artifact contract still holds and is consumed through
  the adapter rather than duplicated.
"""

from __future__ import annotations

import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone

import kagent.artifact_lineage as lineage_module

from kagent.artifact_lineage import (
    MAX_OUTPUT_ARTIFACTS,
    ArtifactLineage,
    ArtifactLineageError,
    LineageArtifactRef,
    declare_lineage,
    ref_from_canonical_artifact,
)
from kagent.artifact_registration import (
    ArtifactLifecycle,
    ArtifactLocation,
    register_canonical_artifact,
)
from kagent.contracts import ContractError


DIGEST_SOURCE = hashlib.sha256(b"lineage-source").hexdigest()
DIGEST_WORKING = hashlib.sha256(b"lineage-working").hexdigest()
DIGEST_OUT_1 = hashlib.sha256(b"lineage-output-1").hexdigest()
DIGEST_OUT_2 = hashlib.sha256(b"lineage-output-2").hexdigest()

CREATED_AT = datetime(2026, 10, 7, 4, 0, tzinfo=timezone.utc)


def ref(artifact_id: str, digest: str) -> LineageArtifactRef:
    return LineageArtifactRef(artifact_id=artifact_id, integrity_ref=digest)


def source_ref() -> LineageArtifactRef:
    return ref("art_" + "a" * 16, DIGEST_SOURCE)


def working_ref() -> LineageArtifactRef:
    return ref("art_" + "b" * 16, DIGEST_WORKING)


def output_refs(count: int = 1) -> tuple[LineageArtifactRef, ...]:
    digests = (DIGEST_OUT_1, DIGEST_OUT_2)
    return tuple(
        ref(f"art_out_{index}", digests[index % len(digests)]) for index in range(count)
    )


def lineage(**overrides) -> ArtifactLineage:
    values = dict(
        lineage_id="lin_" + "1" * 16,
        source=source_ref(),
        transformation_kind="claw.convert.xlsx_to_pdf",
        workspace_ref="ws_" + "2" * 16,
        run_ref="run_" + "3" * 16,
        created_at=CREATED_AT,
    )
    values.update(overrides)
    return ArtifactLineage(**values)


class LegalShapeTests(unittest.TestCase):
    def test_source_only_lineage_is_valid(self) -> None:
        lin = lineage()
        self.assertIsNone(lin.working)
        self.assertIsNone(lin.working_artifact_id)
        self.assertEqual(lin.outputs, ())
        self.assertEqual(lin.output_artifact_ids, ())

    def test_source_to_working_without_output_is_valid(self) -> None:
        lin = lineage(working=working_ref())
        self.assertEqual(lin.working_artifact_id, working_ref().artifact_id)
        self.assertEqual(lin.working_integrity_ref, DIGEST_WORKING)
        self.assertEqual(lin.outputs, ())

    def test_source_to_output_without_working_copy_is_valid(self) -> None:
        # The Google-Sheets working copy is NOT a prerequisite: an ephemeral
        # local conversion must be expressible with no working artifact.
        lin = lineage(outputs=output_refs(1))
        self.assertIsNone(lin.working)
        self.assertEqual(lin.output_artifact_ids, ("art_out_0",))

    def test_source_to_working_to_output_is_valid(self) -> None:
        lin = lineage(working=working_ref(), outputs=output_refs(1), operation_ref="op_" + "4" * 16)
        self.assertEqual(lin.working_artifact_id, working_ref().artifact_id)
        self.assertEqual(lin.output_artifact_ids, ("art_out_0",))
        self.assertEqual(lin.operation_ref, "op_" + "4" * 16)

    def test_multiple_outputs_are_supported(self) -> None:
        lin = lineage(outputs=output_refs(2))
        self.assertEqual(lin.output_artifact_ids, ("art_out_0", "art_out_1"))
        self.assertEqual(lin.output_integrity_refs, (DIGEST_OUT_1, DIGEST_OUT_2))

    def test_output_list_is_bounded(self) -> None:
        lin = lineage(outputs=output_refs(MAX_OUTPUT_ARTIFACTS))
        self.assertEqual(len(lin.outputs), MAX_OUTPUT_ARTIFACTS)
        with self.assertRaises(ArtifactLineageError) as ctx:
            lineage(outputs=output_refs(MAX_OUTPUT_ARTIFACTS + 1))
        self.assertIn("MAX_OUTPUT_ARTIFACTS", str(ctx.exception))

    def test_working_representation_without_canonical_artifact_is_valid(self) -> None:
        lin = lineage(working_representation_ref="rep_opaque_handle_9")
        self.assertIsNone(lin.working)
        self.assertEqual(lin.working_representation_ref, "rep_opaque_handle_9")

    def test_source_identity_and_integrity_are_pinned_not_rewritten(self) -> None:
        lin = lineage(working=working_ref(), outputs=output_refs(2))
        self.assertEqual(lin.source_artifact_id, source_ref().artifact_id)
        self.assertEqual(lin.source_integrity_ref, DIGEST_SOURCE)
        # The source never appears among the derived artifacts.
        self.assertNotIn(lin.source_artifact_id, lin.output_artifact_ids)
        self.assertNotEqual(lin.working_artifact_id, lin.source_artifact_id)

    def test_created_at_is_normalized_to_utc(self) -> None:
        lin = lineage(created_at=datetime(2026, 10, 7, 13, 0, tzinfo=timezone(timedelta(hours=9))))
        self.assertEqual(lin.created_at, CREATED_AT)
        self.assertEqual(lin.public_projection()["created_at"], "2026-10-07T04:00:00Z")


class InvariantFailureTests(unittest.TestCase):
    def test_working_may_not_alias_the_source_artifact(self) -> None:
        with self.assertRaises(ArtifactLineageError) as ctx:
            lineage(working=ref(source_ref().artifact_id, DIGEST_WORKING))
        self.assertIn("alias the source", str(ctx.exception))

    def test_working_representation_may_not_alias_the_source_artifact(self) -> None:
        with self.assertRaises(ArtifactLineageError):
            lineage(working_representation_ref=source_ref().artifact_id)

    def test_working_artifact_and_representation_are_mutually_exclusive(self) -> None:
        with self.assertRaises(ArtifactLineageError):
            lineage(working=working_ref(), working_representation_ref="rep_opaque_handle_9")

    def test_source_must_not_be_listed_as_an_output(self) -> None:
        with self.assertRaises(ArtifactLineageError) as ctx:
            lineage(outputs=(source_ref(),))
        self.assertIn("must not be listed as an output", str(ctx.exception))

    def test_working_must_not_be_listed_as_an_output(self) -> None:
        with self.assertRaises(ArtifactLineageError):
            lineage(working=working_ref(), outputs=(working_ref(),))

    def test_working_representation_must_not_be_listed_as_an_output(self) -> None:
        with self.assertRaises(ArtifactLineageError):
            lineage(
                working_representation_ref="rep_opaque_handle_9",
                outputs=(ref("rep_opaque_handle_9", DIGEST_OUT_1),),
            )

    def test_duplicate_outputs_are_rejected(self) -> None:
        duplicate = output_refs(1)[0]
        with self.assertRaises(ArtifactLineageError) as ctx:
            lineage(outputs=(duplicate, duplicate))
        self.assertIn("distinct", str(ctx.exception))

    def test_duplicate_output_ids_with_different_digests_are_rejected(self) -> None:
        with self.assertRaises(ArtifactLineageError):
            lineage(outputs=(ref("art_out_0", DIGEST_OUT_1), ref("art_out_0", DIGEST_OUT_2)))

    def test_invalid_integrity_relation_fails_closed(self) -> None:
        for bad in ("", "ABC", hashlib.md5(b"x").hexdigest(), "z" * 64, DIGEST_SOURCE + "0"):
            with self.assertRaises(ArtifactLineageError):
                lineage(source=ref("art_" + "a" * 16, bad))
            with self.assertRaises(ArtifactLineageError):
                lineage(outputs=(ref("art_out_0", bad),))


class BoundedFieldValidationTests(unittest.TestCase):
    def test_missing_or_malformed_source_fails_closed(self) -> None:
        for bad in (None, "", "art_source", 123, object()):
            with self.assertRaises(ArtifactLineageError):
                lineage(source=bad)

    def test_malformed_outputs_fails_closed(self) -> None:
        for bad in ("art_out_0", b"art_out_0", 123, None, object()):
            with self.assertRaises(ArtifactLineageError):
                lineage(outputs=bad)
        with self.assertRaises(ArtifactLineageError):
            lineage(outputs=("art_out_0",))

    def test_malformed_ids_are_rejected(self) -> None:
        for bad in ("", "-lead", "a" * 200, "bad id", "아이디", None, 123):
            with self.assertRaises(ArtifactLineageError):
                lineage(lineage_id=bad)
            with self.assertRaises(ArtifactLineageError):
                lineage(transformation_kind=bad)

    def test_malformed_provenance_refs_are_rejected(self) -> None:
        for field in ("workspace_ref", "run_ref"):
            for bad in ("", "../escape", "has space", "a\x00b", "x" * 400, None, 123):
                with self.assertRaises(ArtifactLineageError):
                    lineage(**{field: bad})
        # operation_ref is optional, so only a malformed non-None value fails.
        for bad in ("", "../escape", "has space", "a\x00b", "x" * 400, 123):
            with self.assertRaises(ArtifactLineageError):
                lineage(operation_ref=bad)
        self.assertIsNone(lineage(operation_ref=None).operation_ref)

    def test_naive_or_non_datetime_created_at_is_rejected(self) -> None:
        for bad in (datetime(2026, 10, 7, 4, 0), "2026-10-07T04:00:00Z", None, 123):
            with self.assertRaises(ArtifactLineageError):
                lineage(created_at=bad)

    def test_local_path_leaks_are_rejected(self) -> None:
        for field, bad in (
            ("working_representation_ref", "E:\\downloads\\sheet.xlsx"),
            ("working_representation_ref", "G:/downloads/sheet.xlsx"),
            ("working_representation_ref", "\\\\server\\share\\sheet.xlsx"),
            ("working_representation_ref", "/abs/path/sheet.xlsx"),
            ("working_representation_ref", "file:///etc/passwd"),
            ("working_representation_ref", "file://C:/secret/sheet.xlsx"),
            ("workspace_ref", "E:\\tmp"),
            ("run_ref", "file:///tmp/run"),
            ("operation_ref", "/abs/op"),
        ):
            with self.assertRaises(ArtifactLineageError):
                lineage(**{field: bad})

    def test_secret_shaped_material_is_rejected(self) -> None:
        for field, bad in (
            ("workspace_ref", "secret:example"),
            ("workspace_ref", "oauth:abc123"),
            ("workspace_ref", "api_key:example"),
            ("run_ref", "token:abc"),
            ("operation_ref", "bearer:xyz"),
            ("operation_ref", "apikey:xyz"),
            ("working_representation_ref", "secret:abc"),
            ("working_representation_ref", "oauth:abc123"),
            ("working_representation_ref", "Bearer abcdef123456"),
            ("working_representation_ref", "token sk-live-abcdef0123456789"),
            ("working_representation_ref", "https://api.example.test/v1/files?token=abc123"),
            ("working_representation_ref", "key=AIzaSyD-1234567890"),
            ("working_representation_ref", "chat=-1001234567890;bot=123:ABC"),
        ):
            with self.assertRaises(ArtifactLineageError):
                lineage(**{field: bad})

    def test_valid_opaque_representation_forms_remain_accepted(self) -> None:
        for good in ("rep_opaque_handle_9", "tenants/t/working/doc_x", "sheet:opaque-token-1"):
            lin = lineage(working_representation_ref=good)
            self.assertEqual(lin.working_representation_ref, good)


class PublicProjectionTests(unittest.TestCase):
    def full_lineage(self) -> ArtifactLineage:
        return lineage(
            working=working_ref(),
            outputs=output_refs(2),
            operation_ref="op_" + "4" * 16,
        )

    def test_projection_is_json_safe_and_metadata_only(self) -> None:
        projection = self.full_lineage().public_projection()
        encoded = json.dumps(projection, ensure_ascii=False)
        self.assertIsInstance(encoded, str)
        self.assertEqual(projection["contract_version"], "claw-canonical-artifact-lineage.v1")
        self.assertEqual(projection["source_artifact_id"], source_ref().artifact_id)
        self.assertEqual(projection["source_integrity_ref"], DIGEST_SOURCE)
        self.assertEqual(projection["working_artifact_id"], working_ref().artifact_id)
        self.assertEqual(projection["output_artifact_ids"], ["art_out_0", "art_out_1"])
        self.assertEqual(projection["output_integrity_refs"], [DIGEST_OUT_1, DIGEST_OUT_2])
        self.assertEqual(projection["working_copy_optional"], True)
        self.assertEqual(projection["working_copy_replaces_source"], False)
        self.assertEqual(projection["raw_bytes_in_lineage"], False)

    def test_projection_does_not_duplicate_canonical_artifact_metadata(self) -> None:
        # The lineage must reference artifacts, not re-copy the #3594 record.
        projection = self.full_lineage().public_projection()
        encoded = json.dumps(projection, ensure_ascii=False)
        for field in ("filename", "media_type", "size_bytes", "artifact_kind", "lifecycle"):
            self.assertNotIn(field, projection)
            self.assertNotIn(field, encoded)

    def test_no_local_absolute_paths_in_projection(self) -> None:
        encoded = json.dumps(self.full_lineage().public_projection(), ensure_ascii=False)
        for forbidden in ("E:\\", "G:\\", "C:\\", "\\\\", "file://"):
            self.assertNotIn(forbidden, encoded)

    def test_no_secret_shaped_material_in_projection(self) -> None:
        encoded = json.dumps(self.full_lineage().public_projection(), ensure_ascii=False).lower()
        for forbidden in (
            "bearer ",
            "api_key",
            "apikey",
            "password",
            "secret=",
            "authorization:",
            "oauth",
            "file://",
            "location_ref",
        ):
            self.assertNotIn(forbidden, encoded)

    def test_raw_working_representation_token_is_never_projected(self) -> None:
        token = "rep_opaque_handle_9"
        lin = lineage(working_representation_ref=token)
        projection = lin.public_projection()
        encoded = json.dumps(projection, ensure_ascii=False)
        self.assertEqual(projection["working_representation_present"], True)
        self.assertNotIn(token, encoded)
        self.assertNotIn("working_representation_ref", projection)

    def test_optional_keys_are_omitted_when_absent(self) -> None:
        projection = lineage().public_projection()
        for field in (
            "working_artifact_id",
            "working_integrity_ref",
            "working_representation_present",
            "operation_ref",
        ):
            self.assertNotIn(field, projection)

    def test_projection_is_deterministic(self) -> None:
        first = json.dumps(self.full_lineage().public_projection(), sort_keys=True)
        second = json.dumps(self.full_lineage().public_projection(), sort_keys=True)
        self.assertEqual(first, second)


class AdapterAndRegressionTests(unittest.TestCase):
    def canonical_record(self, **overrides):
        values = dict(
            artifact_id="art_" + "c" * 16,
            artifact_kind="claw.generated_document",
            filename="quote-draft.docx",
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            size_bytes=4096,
            integrity_ref=DIGEST_SOURCE,
            workspace_ref="ws_" + "2" * 16,
            run_ref="run_" + "3" * 16,
        )
        values.update(overrides)
        return register_canonical_artifact(**values)

    def test_canonical_record_maps_onto_a_lineage_ref(self) -> None:
        record = self.canonical_record()
        mapped = ref_from_canonical_artifact(record)
        self.assertEqual(mapped.artifact_id, record.artifact_id)
        self.assertEqual(mapped.integrity_ref, record.integrity_ref)
        # Only identity + integrity cross the boundary; no artifact metadata.
        self.assertEqual(set(mapped.public_projection()), {"artifact_id", "integrity_ref"})

    def test_declare_lineage_consumes_canonical_records_directly(self) -> None:
        source = self.canonical_record()
        output = self.canonical_record(
            artifact_id="art_" + "d" * 16,
            artifact_kind="claw.generated_document",
            filename="quote.pdf",
            media_type="application/pdf",
            size_bytes=8192,
            integrity_ref=DIGEST_OUT_1,
        )
        lin = declare_lineage(
            lineage_id="lin_" + "5" * 16,
            source=source,
            transformation_kind="claw.convert.docx_to_pdf",
            workspace_ref="ws_" + "2" * 16,
            run_ref="run_" + "3" * 16,
            created_at=CREATED_AT,
            outputs=[output],
        )
        self.assertEqual(lin.source_artifact_id, source.artifact_id)
        self.assertEqual(lin.output_artifact_ids, (output.artifact_id,))

    def test_adapter_rejects_non_canonical_sources(self) -> None:
        for bad in (object(), None, "art_x", {"artifact_id": "art_x"}):
            with self.assertRaises(ArtifactLineageError):
                ref_from_canonical_artifact(bad)

    def test_direct_ref_origin_is_precondition_not_attestation(self) -> None:
        record = self.canonical_record()
        direct = LineageArtifactRef(
            artifact_id=record.artifact_id,
            integrity_ref=record.integrity_ref,
        )
        common = dict(
            lineage_id="lin_" + "8" * 16,
            transformation_kind="claw.identity",
            workspace_ref="ws_" + "2" * 16,
            run_ref="run_" + "3" * 16,
            created_at=CREATED_AT,
        )
        from_record = declare_lineage(source=record, **common)
        from_direct = declare_lineage(source=direct, **common)
        self.assertEqual(
            json.dumps(from_record.public_projection(), sort_keys=True),
            json.dumps(from_direct.public_projection(), sort_keys=True),
        )
        for key in from_direct.public_projection():
            lowered = key.lower()
            self.assertNotIn("registered_by", lowered)
            self.assertNotIn("registry_provenance", lowered)
            self.assertNotIn("origin_attest", lowered)

    def test_lineage_adds_no_registry_store_resolver_or_authority(self) -> None:
        public_names = [name.lower() for name in dir(lineage_module) if not name.startswith("_")]
        for forbidden in ("registry", "store", "resolver", "authority"):
            self.assertFalse(
                any(forbidden in name for name in public_names),
                f"unexpected new {forbidden} surface: {public_names}",
            )

    def test_canonical_artifact_contract_regression(self) -> None:
        # #3594 behaviour is untouched by this module: registration, optional
        # durable location and the metadata-only projection still hold.
        record = self.canonical_record(
            lifecycle=ArtifactLifecycle.DURABLE,
            durable_location=ArtifactLocation(location_kind="drive_file", location_ref="1AbC_opaque_9"),
        )
        self.assertEqual(record.lifecycle, ArtifactLifecycle.DURABLE)
        projection = record.public_projection()
        self.assertEqual(projection["durable_location"]["available"], True)
        self.assertNotIn("1AbC_opaque_9", json.dumps(projection))
        lin = lineage(source=record)
        self.assertEqual(lin.source_integrity_ref, DIGEST_SOURCE)
        self.assertNotIn(record.filename, json.dumps(lin.public_projection(), ensure_ascii=False))

    def test_frozen_lineage_cannot_be_mutated(self) -> None:
        lin = lineage()
        with self.assertRaises(Exception):
            lin.lineage_id = "mutated"  # type: ignore[misc]
        with self.assertRaises(Exception):
            lin.source = working_ref()  # type: ignore[misc]

    def test_contract_error_family_is_preserved(self) -> None:
        self.assertTrue(issubclass(ArtifactLineageError, ContractError))


if __name__ == "__main__":
    unittest.main()
