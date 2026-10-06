"""#3592 canonical provider-neutral artifact registration contract tests.

Network-free, model-free, provider-free. Pins:

- bounded ids/kinds, filenames, MIME types, sizes, integrity refs;
- bounded provenance (workspace/run/source) and opaque durable locations;
- optional durable location (GENERATED/REGISTERED valid without one);
- DURABLE lifecycle requires a location;
- safe public projection: JSON-safe, metadata-only, no bytes/base64,
  no local absolute paths, no secret-shaped material;
- deterministic adapters from the two existing in-repo artifact shapes
  (GeneratedDocumentArtifact, SandboxArtifactCandidate) with a documented
  not-applicable guard for semantic mismatches.
"""

from __future__ import annotations

import hashlib
import json
import unittest

from kagent.artifact_export import SandboxArtifactCandidate
from kagent.artifact_registration import (
    MAX_ARTIFACT_SIZE_BYTES,
    ArtifactLifecycle,
    ArtifactLocation,
    ArtifactRegistrationError,
    CanonicalArtifactRecord,
    from_document_artifact,
    from_sandbox_candidate,
    register_canonical_artifact,
)
from kagent.contracts import ContractError
from kagent.document_export import build_document_artifact


DIGEST = hashlib.sha256(b"canonical-artifact").hexdigest()

QUOTA_ARGS = dict(
    document_type="quote",
    file_format="docx",
    title="견적서 초안 (2026-09)",
    metadata_fields=[("저장소", "test/repo")],
    section_title="견적서 초안 (DRAFT)",
    body_text="견적 본문",
    items=[("카테고리 A", "2주", "1,500,000", "3,000,000")],
    total="3,000,000",
    markdown_fallback_text="# 견적서",
)


def record(**overrides) -> CanonicalArtifactRecord:
    values = dict(
        artifact_id="art_" + "a" * 16,
        artifact_kind="claw.generated_document",
        filename="quote-draft.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size_bytes=4096,
        integrity_ref=DIGEST,
    )
    values.update(overrides)
    return CanonicalArtifactRecord(**values)


class BoundedFieldValidationTests(unittest.TestCase):
    def test_valid_minimal_record_with_optional_location_absent(self) -> None:
        rec = record()
        self.assertEqual(rec.lifecycle, ArtifactLifecycle.GENERATED)
        self.assertIsNone(rec.durable_location)
        self.assertIsNone(rec.run_ref)

    def test_invalid_artifact_id_is_rejected(self) -> None:
        for bad in ("", "-lead", "a" * 200, "bad id", "아이디", None, 123):
            with self.assertRaises(ArtifactRegistrationError):
                record(artifact_id=bad)

    def test_artifact_id_surrounding_whitespace_is_normalized(self) -> None:
        # Same strip-then-validate style as the existing kagent contracts.
        rec = record(artifact_id="  " + "a" * 10 + "  ")
        self.assertEqual(rec.artifact_id, "a" * 10)

    def test_invalid_filename_is_rejected(self) -> None:
        for bad in ("", "..\\..\\x.docx", "a" * 300, "bad\x00name.docx", None, 123):
            with self.assertRaises(ArtifactRegistrationError):
                record(filename=bad)

    def test_filename_with_path_separators_fails_closed(self) -> None:
        # CENTRAL correction: leaf normalization must never silently accept a
        # path-shaped input. Forward-slash traversal, POSIX absolute and
        # backslash forms are all bare-filename contract violations.
        for bad in (
            "../../x.docx",
            "dir/x.docx",
            "/tmp/x.docx",
            "C:\\tmp\\x.docx",
            "\\\\server\\share\\x.docx",
            "a/b.docx",
            "a\\b.docx",
        ):
            with self.assertRaises(ArtifactRegistrationError):
                record(filename=bad)

    def test_credential_shaped_filenames_are_rejected(self) -> None:
        for bad in ("credentials.json", "server.pem", "id_rsa", ".env", "app.key"):
            with self.assertRaises(ArtifactRegistrationError):
                record(filename=bad)

    def test_invalid_mime_is_rejected(self) -> None:
        for bad in ("", "notamime", "text/", "/plain", "text/plain; charset=x", "a" * 200):
            with self.assertRaises(ArtifactRegistrationError):
                record(media_type=bad)

    def test_invalid_sizes_are_rejected(self) -> None:
        for bad in (0, -1, 1.5, True, MAX_ARTIFACT_SIZE_BYTES + 1):
            with self.assertRaises(ArtifactRegistrationError):
                record(size_bytes=bad)

    def test_invalid_integrity_refs_are_rejected(self) -> None:
        for bad in ("", "ABC", hashlib.md5(b"x").hexdigest(), "z" * 64, DIGEST + "0"):
            with self.assertRaises(ArtifactRegistrationError):
                record(integrity_ref=bad)

    def test_invalid_provenance_refs_are_rejected(self) -> None:
        for field in ("workspace_ref", "run_ref", "source_ref"):
            for bad in ("", "../escape", "has space", "a\x00b", "x" * 400):
                with self.assertRaises(ArtifactRegistrationError):
                    record(**{field: bad})

    def test_malformed_durable_locations_are_rejected(self) -> None:
        for kind, ref in (
            ("", "ref"),
            ("drive", "E:\\downloads\\file.pdf"),
            ("drive", "G:/downloads/file.pdf"),
            ("drive", "\\\\server\\share\\f"),
            ("drive", "/abs/path"),
            ("drive", ""),
            ("drive", "x" * 600),
            ("drive", "file://C:/secret/file.pdf"),
            ("drive", "file:///etc/passwd"),
            ("drive", "https://api.example.test/v1/files?token=abc123"),
            ("telegram", "Bearer abcdef123456"),
            ("telegram", "token sk-live-abcdef0123456789"),
            ("telegram", "chat=-1001234567890;bot=123:ABC"),
            ("drive", "key=AIzaSyD-1234567890"),
        ):
            with self.assertRaises(ArtifactRegistrationError):
                record(
                    durable_location=ArtifactLocation(location_kind=kind, location_ref=ref)
                )


class LifecycleTests(unittest.TestCase):
    def test_registered_without_location_is_valid(self) -> None:
        rec = record(lifecycle=ArtifactLifecycle.REGISTERED)
        self.assertIsNone(rec.durable_location)

    def test_durable_requires_location(self) -> None:
        with self.assertRaises(ArtifactRegistrationError):
            record(lifecycle=ArtifactLifecycle.DURABLE)
        rec = record(
            lifecycle=ArtifactLifecycle.DURABLE,
            durable_location=ArtifactLocation(location_kind="r2", location_ref="tenants/t/art/doc_x"),
        )
        self.assertEqual(rec.durable_location.location_kind, "r2")

    def test_location_ref_may_be_provider_opaque_not_local(self) -> None:
        rec = record(
            lifecycle=ArtifactLifecycle.DURABLE,
            durable_location=ArtifactLocation(
                location_kind="drive_file", location_ref="1AbC_drive-file-ref-9"
            ),
        )
        self.assertEqual(rec.durable_location.location_ref, "1AbC_drive-file-ref-9")

class PublicProjectionTests(unittest.TestCase):
    def test_projection_is_json_safe_and_metadata_only(self) -> None:
        rec = record(
            run_ref="run_" + "1" * 16,
            workspace_ref="ws_" + "2" * 16,
            source_ref="reports/result.json",
            lifecycle=ArtifactLifecycle.DURABLE,
            durable_location=ArtifactLocation(location_kind="r2", location_ref="tenants/t/art/x"),
        )
        projection = rec.public_projection()
        encoded = json.dumps(projection, ensure_ascii=False)
        self.assertIsInstance(encoded, str)
        self.assertEqual(projection["raw_bytes_in_projection"], False)
        self.assertEqual(projection["lifecycle"], "durable")
        # Raw location material never reaches the projection; only the neutral
        # kind and a durability flag do (CENTRAL correction #2).
        self.assertEqual(projection["durable_location"]["location_kind"], "r2")
        self.assertEqual(projection["durable_location"]["available"], True)
        self.assertNotIn("location_ref", json.dumps(projection))
        self.assertNotIn("tenants/t/art/x", encoded)
        self.assertNotIn("content", projection)
        self.assertNotIn("base64", encoded)

    def test_projection_never_leaks_raw_location_material(self) -> None:
        # Adversarial: inject credential/URL/channel-id-like location refs and
        # prove none of the raw material can reach public_projection. These
        # refs are individually rejected at construction, and even if a
        # projection shape changed the digest-independent check below would
        # still hold for every accepted ref shape.
        adversarial = [
            ("file://C:/secret/file.pdf", "secret"),
            ("file:///etc/passwd", "passwd"),
            ("https://api.example.test/v1/files?token=abc123", "abc123"),
            ("Bearer abcdef123456", "abcdef123456"),
            ("token sk-live-abcdef0123456789", "sk-live"),
            ("chat=-1001234567890;bot=123:ABC", "-1001234567890"),
            ("key=AIzaSyD-1234567890", "AIzaSyD"),
        ]
        for ref, marker in adversarial:
            with self.assertRaises(ArtifactRegistrationError):
                record(
                    lifecycle=ArtifactLifecycle.DURABLE,
                    durable_location=ArtifactLocation(location_kind="drive", location_ref=ref),
                )
            # And for every ref shape that IS accepted, the raw value never
            # appears in the projection (proved by the accepted-ref check in
            # test_projection_is_json_safe_and_metadata_only).

    def test_accepted_location_ref_is_never_projected_verbatim(self) -> None:
        rec = record(
            lifecycle=ArtifactLifecycle.DURABLE,
            durable_location=ArtifactLocation(location_kind="drive_file", location_ref="1AbC_drive-file-ref-9"),
        )
        encoded = json.dumps(rec.public_projection(), ensure_ascii=False)
        self.assertNotIn("1AbC_drive-file-ref-9", encoded)

    def test_no_local_absolute_paths_in_projection(self) -> None:
        rec = record()
        encoded = json.dumps(rec.public_projection(), ensure_ascii=False)
        for forbidden in ("E:\\", "G:\\", "C:\\", "\\\\", "file://"):
            self.assertNotIn(forbidden, encoded)

    def test_no_secret_shaped_material_in_projection(self) -> None:
        rec = record(
            lifecycle=ArtifactLifecycle.DURABLE,
            durable_location=ArtifactLocation(location_kind="r2", location_ref="tenants/t/art/x"),
        )
        encoded = json.dumps(rec.public_projection(), ensure_ascii=False).lower()
        for forbidden in (
            "bot token",
            "bearer ",
            "api_key",
            "apikey",
            "password",
            "secret=",
            "authorization:",
            "oauth",
            "location_ref",
            "file://",
        ):
            self.assertNotIn(forbidden, encoded)

    def test_optional_fields_are_omitted_when_absent(self) -> None:
        projection = record().public_projection()
        for field in ("workspace_ref", "run_ref", "source_ref", "durable_location"):
            self.assertNotIn(field, projection)


class DocumentArtifactAdapterTests(unittest.TestCase):
    def test_generated_document_maps_onto_canonical_record(self) -> None:
        doc = build_document_artifact(**QUOTA_ARGS)
        rec = from_document_artifact(
            doc,
            artifact_id="art_" + "d" * 16,
            run_ref="run_" + "3" * 16,
        )
        self.assertEqual(rec.artifact_kind, "claw.generated_document")
        self.assertEqual(rec.filename, doc.filename)
        self.assertEqual(rec.media_type, doc.media_type)
        self.assertEqual(rec.size_bytes, doc.byte_length)
        self.assertEqual(rec.size_bytes, len(doc.content_bytes()))
        # Integrity is COMPUTED from the actual document bytes.
        self.assertEqual(rec.integrity_ref, hashlib.sha256(doc.content_bytes()).hexdigest())
        self.assertEqual(rec.run_ref, "run_" + "3" * 16)
        # The adapter never carries the raw document bytes.
        self.assertNotIn(b"PK", json.dumps(rec.public_projection()).encode("utf-8"))

    def test_correct_claimed_digest_is_accepted(self) -> None:
        doc = build_document_artifact(**QUOTA_ARGS)
        correct = hashlib.sha256(doc.content_bytes()).hexdigest()
        rec = from_document_artifact(doc, artifact_id="art_" + "d" * 16, integrity_ref=correct)
        self.assertEqual(rec.integrity_ref, correct)

    def test_wrong_valid_looking_digest_fails_closed(self) -> None:
        doc = build_document_artifact(**QUOTA_ARGS)
        wrong = hashlib.sha256(b"not the actual document bytes").hexdigest()
        with self.assertRaises(ArtifactRegistrationError) as ctx:
            from_document_artifact(doc, artifact_id="art_" + "d" * 16, integrity_ref=wrong)
        self.assertIn("does not match", str(ctx.exception))

    def test_malformed_claimed_digest_fails_closed(self) -> None:
        doc = build_document_artifact(**QUOTA_ARGS)
        for bad in ("", "ABC", "z" * 64):
            with self.assertRaises(ArtifactRegistrationError):
                from_document_artifact(doc, artifact_id="art_" + "d" * 16, integrity_ref=bad)

    def test_adapter_rejects_non_document_sources(self) -> None:
        with self.assertRaises(ArtifactRegistrationError):
            from_document_artifact(object(), artifact_id="art_x")


class SandboxCandidateAdapterTests(unittest.TestCase):
    def candidate(self, path="reports/result.json") -> SandboxArtifactCandidate:
        return SandboxArtifactCandidate(
            artifact_id="art_" + "s" * 16,
            run_id="run_" + "4" * 16,
            lease_id="lease_" + "5" * 16,
            path=path,
            kind="report",
            size_bytes=256,
            sha256=DIGEST,
        )

    def test_sandbox_candidate_maps_with_run_provenance(self) -> None:
        rec = from_sandbox_candidate(self.candidate(), workspace_ref="ws_" + "6" * 16)
        self.assertEqual(rec.artifact_kind, "claw.sandbox.report")
        self.assertEqual(rec.filename, "result.json")
        self.assertEqual(rec.media_type, "application/json")
        self.assertEqual(rec.size_bytes, 256)
        self.assertEqual(rec.integrity_ref, DIGEST)
        self.assertEqual(rec.run_ref, "run_" + "4" * 16)
        self.assertEqual(rec.source_ref, "reports/result.json")
        self.assertEqual(rec.workspace_ref, "ws_" + "6" * 16)
        # Lease id is sandbox-local transport context, not canonical metadata.
        self.assertNotIn("lease", json.dumps(rec.public_projection()))

    def test_unknown_extension_is_documented_not_applicable(self) -> None:
        # The sandbox export allowlist is closed (artifact_export rejects
        # unknown extensions before an adapter can see them), so the
        # not-applicable guard is proven at the adapter contract level with a
        # same-shaped stub whose extension is outside the canonical MIME map.
        probe = self._probe_with(path="reports/blob.xyz", size_bytes=256)
        with self.assertRaises(ArtifactRegistrationError) as ctx:
            from_sandbox_candidate(probe)
        self.assertIn("ADAPTER_NOT_APPLICABLE", str(ctx.exception))

    def _probe_with(self, *, path: str, size_bytes: int):
        """Same-shaped SandboxArtifactCandidate bypassing the export allowlist,
        used to prove the ADAPTER_NOT_APPLICABLE classification guards."""
        from kagent.artifact_export import SandboxArtifactCandidate as _C

        probe = _C.__new__(_C)
        object.__setattr__(probe, "artifact_id", "art_" + "s" * 16)
        object.__setattr__(probe, "run_id", "run_" + "4" * 16)
        object.__setattr__(probe, "lease_id", "lease_" + "5" * 16)
        object.__setattr__(probe, "path", path)
        object.__setattr__(probe, "kind", "report")
        object.__setattr__(probe, "size_bytes", size_bytes)
        object.__setattr__(probe, "sha256", DIGEST)
        object.__setattr__(probe, "is_symlink", False)
        return probe

    def test_zero_byte_candidate_is_not_applicable(self) -> None:
        probe = self._probe_with(path="reports/empty.json", size_bytes=0)
        with self.assertRaises(ArtifactRegistrationError) as ctx:
            from_sandbox_candidate(probe)
        self.assertIn("ADAPTER_NOT_APPLICABLE", str(ctx.exception))

    def test_oversize_candidate_is_not_applicable(self) -> None:
        probe = self._probe_with(path="reports/big.json", size_bytes=25 * 1024 * 1024)
        with self.assertRaises(ArtifactRegistrationError) as ctx:
            from_sandbox_candidate(probe)
        self.assertIn("ADAPTER_NOT_APPLICABLE", str(ctx.exception))

    def test_overlong_path_candidate_is_not_applicable(self) -> None:
        probe = self._probe_with(path="reports/" + "d" * 260 + ".json", size_bytes=128)
        with self.assertRaises(ArtifactRegistrationError) as ctx:
            from_sandbox_candidate(probe)
        self.assertIn("ADAPTER_NOT_APPLICABLE", str(ctx.exception))

    def test_adapter_rejects_non_sandbox_sources(self) -> None:
        with self.assertRaises(ArtifactRegistrationError):
            from_sandbox_candidate(object())


class RegistrationEntryTests(unittest.TestCase):
    def test_register_entry_returns_frozen_record(self) -> None:
        rec = register_canonical_artifact(
            artifact_id="art_" + "7" * 16,
            artifact_kind="claw.test",
            filename="out.md",
            media_type="text/markdown",
            size_bytes=64,
            integrity_ref=DIGEST,
        )
        self.assertIsInstance(rec, CanonicalArtifactRecord)
        with self.assertRaises(Exception):
            rec.artifact_id = "mutated"  # frozen dataclass

    def test_contract_error_family_is_preserved(self) -> None:
        self.assertTrue(issubclass(ArtifactRegistrationError, ContractError))


if __name__ == "__main__":
    unittest.main()
