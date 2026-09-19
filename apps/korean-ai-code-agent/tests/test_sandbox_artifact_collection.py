from __future__ import annotations

import inspect
import random
import re
import unittest

from kagent import artifact_export
from kagent.artifact_export import (
    ArtifactExportManifest,
    ArtifactExportPolicy,
    SandboxArtifactCandidate,
)
from kagent.contracts import ContractError
from kagent.sandbox_artifact_collection import (
    DELETED_CANDIDATE_REQUIRES_HOST_READ,
    PATH_AUTHORITY_OWNED_BY_CLOUD_WORKSPACE_PATH_POLICY,
    RAW_BINARY_BYTES_PROJECTED,
    REAL_WORKSPACE_ARTIFACT_COLLECTION_CONFIGURED,
    SOURCE_CHANGE_IMPLIES_EXPORT_AUTHORITY,
    ARTIFACT_EXPORT_ALLOWLIST_WIDENED,
    TEXT_EXCERPT_REDACTED_BEFORE_PROJECTION,
    WORKSPACE_ARTIFACT_COLLECTOR_DISCOVERS_NO_PATHS,
    WORKSPACE_ARTIFACT_COLLECTOR_PERFORMS_NO_FILESYSTEM_SCAN,
    ArtifactCandidateCollection,
    ArtifactPromotionBlock,
    CandidateRejection,
    ChangedFileFact,
    CollectedArtifact,
    RejectedCandidate,
    WorkspaceArtifactCollector,
    WorkspaceChangeCandidate,
    WorkspaceChangeKind,
    WorkspaceContentKind,
)
from kagent.sandbox_policy import (
    CloudWorkspacePathPolicy,
    CloudWorkspacePathRule,
    WorkspacePathOperation,
)
from kagent.security import contains_credential_material, redact_secrets

DIGEST = "a" * 64
OTHER_DIGEST = "b" * 64
_EXCERPT_LIMIT = 4_096
_INPUT_LIMIT = 65_536

_SHORTHAND = {
    "kind": "change_kind",
    "ck": "content_kind",
    "bs": "byte_size",
    "sha": "content_sha256",
}


def candidate(path: str, **overrides: object) -> WorkspaceChangeCandidate:
    fields: dict[str, object] = {
        "relative_path": path,
        "change_kind": WorkspaceChangeKind.MODIFIED,
        "content_kind": WorkspaceContentKind.TEXT,
        "byte_size": 100,
        "content_sha256": DIGEST,
    }
    for key, value in overrides.items():
        fields[_SHORTHAND.get(key, key)] = value
    return WorkspaceChangeCandidate(**fields)  # type: ignore[arg-type]


DEFAULT_PATH_POLICY = CloudWorkspacePathPolicy(
    rules=(
        CloudWorkspacePathRule("out", readable=True),
        CloudWorkspacePathRule("src", readable=True),
    )
)


def collecting(*candidates: WorkspaceChangeCandidate, **kwargs) -> ArtifactCandidateCollection:
    collector = WorkspaceArtifactCollector(
        path_policy=kwargs.pop("path_policy", DEFAULT_PATH_POLICY),
        export_policy=kwargs.pop("export_policy", ArtifactExportPolicy()),
    )
    return collector.collect(
        collection_id=kwargs.pop("collection_id", "col_001"),
        run_id=kwargs.pop("run_id", "run_001"),
        lease_id=kwargs.pop("lease_id", "lease_001"),
        candidates=candidates,
    )


def fact_for(result: ArtifactCandidateCollection, path: str) -> ChangedFileFact:
    return next(f for f in result.changed_files if f.relative_path == path)


def exportable_for(result: ArtifactCandidateCollection, path: str) -> CollectedArtifact:
    return next(e for e in result.exportable_artifacts if e.candidate.path == path)


class ChangedFileVsExportableArtifactTests(unittest.TestCase):
    """Blocker 1: a source change is evidence, not a publishable file artifact."""

    def test_readable_source_path_is_accepted_as_a_changed_file_fact(self):
        result = collecting(candidate("src/app.py"))
        self.assertEqual(result.changed_file_count, 1)
        fact = fact_for(result, "src/app.py")
        self.assertEqual(fact.change_kind, WorkspaceChangeKind.MODIFIED)
        self.assertEqual(result.rejected, ())

    def test_readable_source_path_does_not_become_an_artifact_candidate(self):
        result = collecting(candidate("src/app.py"))
        self.assertEqual(result.exportable_count, 0)
        self.assertEqual(result.exportable_artifacts, ())
        self.assertIsNone(result.manifest)
        self.assertFalse(fact_for(result, "src/app.py").exportable)
        self.assertFalse(SOURCE_CHANGE_IMPLIES_EXPORT_AUTHORITY)

    def test_source_path_promotion_block_names_the_allowlist_as_the_reason(self):
        result = collecting(candidate("src/app.py"))
        self.assertEqual(
            fact_for(result, "src/app.py").promotion_block,
            ArtifactPromotionBlock.ARTIFACT_CLASS_NOT_ALLOWLISTED,
        )

    def test_allowlisted_classes_still_become_exportable_artifacts(self):
        result = collecting(
            candidate("out/result.diff"),
            candidate("out/report.md", sha=OTHER_DIGEST),
            candidate("out/summary.json"),
        )
        self.assertEqual(result.changed_file_count, 3)
        self.assertEqual(result.exportable_count, 3)
        self.assertEqual(
            sorted(e.candidate.path for e in result.exportable_artifacts),
            ["out/report.md", "out/result.diff", "out/summary.json"],
        )
        for entry in result.exportable_artifacts:
            self.assertIsInstance(entry.candidate, SandboxArtifactCandidate)

    def test_mixed_set_keeps_source_evidence_and_exports_only_the_artifact_subset(self):
        result = collecting(
            candidate("src/app.py"),
            candidate("src/service.ts"),
            candidate("out/result.diff"),
        )
        self.assertEqual(result.changed_file_count, 3)
        self.assertEqual(result.exportable_count, 1)
        manifest = result.manifest
        assert manifest is not None
        self.assertEqual([item.path for item in manifest.artifacts], ["out/result.diff"])
        self.assertTrue(all(f.exportable is False for f in result.changed_files if f.relative_path.startswith("src/")))

    def test_changed_file_projection_carries_no_content(self):
        result = collecting(candidate("src/app.py"), candidate("out/a.md", text_excerpt="body"))
        for fact in result.changed_files:
            self.assertFalse(fact.safe_dict()["content_included"])

    def test_existing_artifact_export_allowlist_is_untouched(self):
        # Pinned so widening the export class set can never ride in on a collection PR.
        self.assertEqual(
            artifact_export._ALLOWED_EXTENSIONS,
            frozenset({".txt", ".md", ".json", ".csv", ".log", ".xml", ".html", ".diff", ".patch"}),
        )
        self.assertNotIn(".py", artifact_export._ALLOWED_EXTENSIONS)
        self.assertNotIn(".ts", artifact_export._ALLOWED_EXTENSIONS)
        self.assertFalse(ARTIFACT_EXPORT_ALLOWLIST_WIDENED)


class ExportBudgetPromotionTests(unittest.TestCase):
    """Budget exhaustion withholds publication; it never erases the change fact."""

    def test_count_bound_blocks_promotion_but_keeps_the_fact(self):
        export = ArtifactExportPolicy(max_files=2, max_file_bytes=4096, max_total_bytes=8192)
        result = collecting(
            candidate("out/a.md"),
            candidate("out/b.md", sha=OTHER_DIGEST),
            candidate("out/c.md"),
            export_policy=export,
        )
        self.assertEqual(result.changed_file_count, 3)
        self.assertEqual(result.exportable_count, 2)
        self.assertEqual(result.rejected, ())
        blocked = fact_for(result, "out/c.md")
        self.assertFalse(blocked.exportable)
        self.assertEqual(blocked.promotion_block, ArtifactPromotionBlock.CANDIDATE_COUNT_EXCEEDS_LIMIT)

    def test_per_item_byte_bound_blocks_promotion_but_keeps_the_fact(self):
        export = ArtifactExportPolicy(max_files=50, max_file_bytes=1024, max_total_bytes=8192)
        result = collecting(candidate("src/huge.py", bs=9000), export_policy=export)
        self.assertEqual(result.changed_file_count, 1)
        self.assertEqual(result.exportable_count, 0)
        self.assertEqual(
            fact_for(result, "src/huge.py").promotion_block,
            ArtifactPromotionBlock.BYTE_SIZE_EXCEEDS_CANDIDATE_LIMIT,
        )

    def test_large_readable_artifact_class_is_blocked_by_size_not_class(self):
        export = ArtifactExportPolicy(max_files=50, max_file_bytes=1024, max_total_bytes=8192)
        result = collecting(candidate("out/big.md", bs=9000), export_policy=export)
        self.assertEqual(
            fact_for(result, "out/big.md").promotion_block,
            ArtifactPromotionBlock.BYTE_SIZE_EXCEEDS_CANDIDATE_LIMIT,
        )

    def test_aggregate_bound_blocks_promotion_but_keeps_the_fact(self):
        export = ArtifactExportPolicy(max_files=50, max_file_bytes=4096, max_total_bytes=5000)
        result = collecting(
            candidate("out/a.md", bs=3000),
            candidate("out/b.md", bs=3000, sha=OTHER_DIGEST),
            export_policy=export,
        )
        self.assertEqual(result.changed_file_count, 2)
        self.assertEqual(result.exportable_count, 1)
        self.assertEqual(result.aggregate_bytes, 3000)
        self.assertEqual(
            fact_for(result, "out/b.md").promotion_block,
            ArtifactPromotionBlock.AGGREGATE_BYTES_EXCEED_LIMIT,
        )

    def test_source_only_changes_never_consume_export_budget(self):
        export = ArtifactExportPolicy(max_files=1, max_file_bytes=4096, max_total_bytes=4096)
        result = collecting(
            candidate("src/a.py"),
            candidate("src/b.py", sha=OTHER_DIGEST),
            candidate("out/only.md"),
            export_policy=export,
        )
        self.assertEqual(result.exportable_count, 1)
        self.assertEqual(result.aggregate_bytes, 100)
        self.assertEqual(exportable_for(result, "out/only.md").candidate.path, "out/only.md")

    def test_input_count_closed_ceiling_raises(self):
        with self.assertRaises(ContractError):
            collecting(*[candidate(f"out/{n}.md") for n in range(201)])


class SecretRedactionTests(unittest.TestCase):
    """Blocker 2: a readable path is not a licence to project a credential."""

    def projecting(self, body: str) -> str | None:
        result = collecting(candidate("out/report.md", text_excerpt=body))
        return exportable_for(result, "out/report.md").text_excerpt

    def test_credential_shapes_never_survive_into_the_projection(self):
        # Fixture policy: low-entropy hyphenated placeholders only, and no provider's real
        # key format is imitated. An earlier revision used ghp_/AIzaSy/sk-or-v1- shaped
        # values and GitGuardian flagged this test file as a hardcoded secret — exactly the
        # noise a redaction test must not generate. The assignment grammar still matches, so
        # all three shapes security.redact_secrets handles are exercised.
        # Labels are neutral "shape-N" tokens placed after the body. Naming a row
        # "bearer" immediately before the word "Authorization" puts a credential keyword
        # next to a long unbroken token, which is the exact adjacency a generic-password
        # detector scores; the body itself already says which shape it is.
        hostile = (
            ("Authorization: Bearer fake-bearer-value-1", "fake-bearer-value-1", "shape-1"),
            ("key sk-fake-key-value-2", "sk-fake-key-value-2", "shape-2"),
            ("issuer sk-or-v1-fake-key-value-3", "sk-or-v1-fake-key-value-3", "shape-3"),
            ("api_key=fake-api-key-value-4", "fake-api-key-value-4", "shape-4"),
            ("token: fake-token-value-5", "fake-token-value-5", "shape-5"),
            ("client_secret=fake-secret-value-6", "fake-secret-value-6", "shape-6"),
            ("db_password=fake-password-value-7", "fake-password-value-7", "shape-7"),
        )
        for body, secret_value, label in hostile:
            with self.subTest(secret=label):
                self.assertIn(secret_value, body)
                projected = self.projecting(body) or ""
                self.assertNotIn(secret_value, projected)
                self.assertIn("[REDACTED", projected)

    def test_redaction_is_applied_and_reported(self):
        result = collecting(
            candidate("out/report.md", text_excerpt="token=fake-token-value-8")
        )
        entry = exportable_for(result, "out/report.md")
        self.assertTrue(entry.excerpt_redacted)
        self.assertNotIn("fake-token-value-8", entry.text_excerpt or "")
        self.assertIn("[REDACTED]", entry.text_excerpt or "")
        self.assertTrue(TEXT_EXCERPT_REDACTED_BEFORE_PROJECTION)

    def test_clean_text_is_passed_through_unmarked(self):
        entry = exportable_for(collecting(candidate("out/a.md", text_excerpt="just prose")), "out/a.md")
        self.assertEqual(entry.text_excerpt, "just prose")
        self.assertFalse(entry.excerpt_redacted)
        self.assertFalse(entry.excerpt_truncated)

    def test_redaction_happens_before_truncation_at_the_boundary(self):
        # A key starting just before the cut keeps 0 characters when the whole text is
        # redacted first, and 4 when the text is cut first. This pins the ordering, not
        # just the outcome.
        body = "y" * 4088 + " sk-" + "X" * 14
        entry = exportable_for(collecting(candidate("out/a.md", text_excerpt=body)), "out/a.md")
        projected = entry.text_excerpt or ""

        self.assertEqual(len(projected), _EXCERPT_LIMIT)
        self.assertTrue(entry.excerpt_redacted)
        self.assertTrue(entry.excerpt_truncated)
        self.assertNotIn("XXXX", projected)
        self.assertNotIn("sk-", projected)

        reversed_order = redact_secrets(body[:_EXCERPT_LIMIT])
        self.assertIn("XXXX", reversed_order, "the reversed order must leak, or this proves nothing")

    def test_oversized_input_excerpt_is_rejected_before_regex_work(self):
        result = collecting(candidate("out/a.md", text_excerpt="z" * (_INPUT_LIMIT + 1)))
        self.assertEqual(result.changed_file_count, 0)
        self.assertEqual(result.exportable_count, 0)
        self.assertEqual(
            result.rejected[0].reason, CandidateRejection.TEXT_EXCERPT_EXCEEDS_INPUT_LIMIT
        )

    def test_excerpt_at_the_input_ceiling_is_still_accepted(self):
        result = collecting(candidate("out/a.md", text_excerpt="z" * _INPUT_LIMIT))
        entry = exportable_for(result, "out/a.md")
        self.assertEqual(len(entry.text_excerpt or ""), _EXCERPT_LIMIT)
        self.assertTrue(entry.excerpt_truncated)

    def test_digest_still_describes_the_whole_file_after_redaction(self):
        result = collecting(candidate("out/a.md", text_excerpt="api_key=fake-api-key-value-10"))
        entry = exportable_for(result, "out/a.md")
        self.assertNotIn("fake-api-key-value-10", entry.text_excerpt or "")
        self.assertEqual(entry.candidate.sha256, DIGEST)

    def test_glued_boundary_gap_is_closed(self):
        # Inverted from a pinned limitation. This asserted redact_secrets(glued) == glued
        # to document that the shared primitive anchored sk- at a word boundary, so a
        # credential concatenated onto alphanumerics was invisible. #2784 removed that
        # anchor, so the repaired behaviour is now what is asserted here.
        glued = "y" * 20 + "sk-" + "X" * 14
        self.assertNotEqual(redact_secrets(glued), glued)
        self.assertTrue(contains_credential_material(glued))
        entry = exportable_for(collecting(candidate("out/a.md", text_excerpt=glued)), "out/a.md")
        self.assertTrue(entry.excerpt_redacted)
        self.assertNotIn("sk-XXX", entry.text_excerpt or "")


class WorkspaceArtifactCollectorCoreTests(unittest.TestCase):
    """Carried forward from the first revision: authority, purity, determinism."""

    def test_canonical_relative_readable_candidate_accepted(self):
        result = collecting(candidate("out/report.md"))
        self.assertEqual(result.exportable_count, 1)
        self.assertEqual(result.rejected, ())
        entry = exportable_for(result, "out/report.md")
        self.assertEqual(entry.candidate.kind, "modified")
        self.assertEqual(entry.candidate.sha256, DIGEST)

    def test_manifest_is_the_existing_export_contract(self):
        result = collecting(candidate("out/a.md"), candidate("out/b.json", sha=OTHER_DIGEST))
        manifest = result.manifest
        self.assertIsInstance(manifest, ArtifactExportManifest)
        assert manifest is not None
        self.assertEqual(manifest.run_id, "run_001")
        self.assertEqual(manifest.total_bytes, 200)
        manifest.validate_against(ArtifactExportPolicy())

    def test_unmatched_path_rejected_as_not_readable(self):
        result = collecting(candidate("notes/private.md"))
        self.assertEqual(result.changed_file_count, 0)
        self.assertEqual(result.rejected[0].reason, CandidateRejection.PATH_NOT_READABLE)

    def test_write_only_path_is_still_not_readable_evidence(self):
        policy = CloudWorkspacePathPolicy(
            rules=(CloudWorkspacePathRule("out", writable=True, delete_allowed=True),)
        )
        result = collecting(candidate("out/report.md"), path_policy=policy)
        self.assertEqual(result.changed_file_count, 0)
        self.assertEqual(result.rejected[0].reason, CandidateRejection.PATH_NOT_READABLE)

    def test_symlink_or_reparse_candidate_rejected(self):
        result = collecting(candidate("out/evil.md", symlink_or_reparse=True))
        self.assertEqual(result.changed_file_count, 0)
        self.assertEqual(result.rejected[0].reason, CandidateRejection.SYMLINK_OR_REPARSE)

    def test_hostile_path_forms_rejected_by_the_workspace_authority(self):
        for path in (
            "/etc/passwd",
            "//server/share/x.md",
            "C:/Windows/x.md",
            "d:/repo/out.md",
            "../outside.md",
            "out/../../etc/x.md",
            "out\\report.md",
            "out//report.md",
            "./out/x.md",
            "~/.ssh/id.md",
            "out/.env",
            "*",
        ):
            with self.subTest(path=path):
                result = collecting(candidate(path))
                self.assertEqual(result.changed_file_count, 0)
                self.assertEqual(
                    result.rejected[0].reason,
                    CandidateRejection.PATH_REFUSED_BY_WORKSPACE_AUTHORITY,
                )

    def test_collection_never_widens_write_or_delete_authority(self):
        policy = CloudWorkspacePathPolicy(rules=(CloudWorkspacePathRule("out", readable=True),))
        result = collecting(candidate("out/report.md"), path_policy=policy)
        self.assertEqual(result.exportable_count, 1)
        self.assertFalse(policy.authorize("out/report.md", WorkspacePathOperation.WRITE))
        self.assertFalse(policy.authorize("out/report.md", WorkspacePathOperation.DELETE))

    def test_deleted_candidate_never_requires_reading_the_host(self):
        result = collecting(candidate("out/gone.md", change_kind=WorkspaceChangeKind.DELETED))
        self.assertEqual(result.exportable_count, 1)
        self.assertIsNone(exportable_for(result, "out/gone.md").text_excerpt)
        self.assertEqual(exportable_for(result, "out/gone.md").candidate.kind, "deleted")
        self.assertFalse(DELETED_CANDIDATE_REQUIRES_HOST_READ)

    def test_deleted_candidate_carrying_content_is_rejected(self):
        result = collecting(
            candidate(
                "out/gone.md",
                change_kind=WorkspaceChangeKind.DELETED,
                text_excerpt="recovered body",
            )
        )
        self.assertEqual(result.changed_file_count, 0)
        self.assertEqual(
            result.rejected[0].reason, CandidateRejection.DELETED_CANDIDATE_CARRIES_CONTENT
        )

    def test_binary_candidate_projects_metadata_only(self):
        result = collecting(candidate("out/build.log", content_kind=WorkspaceContentKind.BINARY))
        self.assertEqual(result.exportable_count, 1)
        entry = exportable_for(result, "out/build.log")
        self.assertIsNone(entry.text_excerpt)
        self.assertFalse(entry.candidate.safe_dict()["raw_content_in_projection"])
        self.assertFalse(RAW_BINARY_BYTES_PROJECTED)

    def test_binary_candidate_carrying_body_is_rejected(self):
        result = collecting(
            candidate(
                "out/build.log",
                content_kind=WorkspaceContentKind.BINARY,
                text_excerpt="\x00\x01binary",
            )
        )
        self.assertEqual(result.changed_file_count, 0)
        self.assertEqual(
            result.rejected[0].reason, CandidateRejection.BINARY_CANDIDATE_CARRIES_CONTENT
        )

    def test_duplicate_path_fails_closed_under_one_deterministic_rule(self):
        result = collecting(
            candidate("out/a.md"),
            candidate("out/a.md", sha=OTHER_DIGEST),
            candidate("out/a.md", change_kind=WorkspaceChangeKind.ADDED),
        )
        self.assertEqual(result.changed_file_count, 0)
        self.assertEqual(len(result.rejected), 3)
        self.assertEqual(
            {item.reason for item in result.rejected},
            {CandidateRejection.DUPLICATE_PATH_AMBIGUOUS},
        )

    def test_identical_input_produces_identical_projection(self):
        facts = (
            candidate("out/a.md", text_excerpt="one"),
            candidate("src/b.ts", bs=77, sha=OTHER_DIGEST),
            candidate("out/c.md", symlink_or_reparse=True),
        )
        self.assertEqual(collecting(*facts).safe_dict(), collecting(*facts).safe_dict())

    def test_input_order_does_not_change_the_projection(self):
        facts = (
            candidate("out/a.md", bs=10),
            candidate("out/b.md", bs=20, sha=OTHER_DIGEST),
            candidate("src/c.ts", bs=30),
            candidate("out/bad.md", symlink_or_reparse=True),
        )
        baseline = collecting(*facts).safe_dict()
        for seed in range(5):
            shuffled = list(facts)
            random.Random(seed).shuffle(shuffled)
            with self.subTest(seed=seed):
                self.assertEqual(collecting(*shuffled).safe_dict(), baseline)

    def test_empty_and_fully_rejected_inputs_yield_no_manifest(self):
        self.assertIsNone(collecting().manifest)
        self.assertEqual(collecting().exportable_count, 0)
        rejected_only = collecting(candidate("/etc/passwd"), candidate("notes/x.md"))
        self.assertIsNone(rejected_only.manifest)
        self.assertEqual(len(rejected_only.rejected), 2)

    def test_exportable_and_changed_file_sets_must_agree(self):
        with self.assertRaises(ContractError):
            ArtifactCandidateCollection(
                collection_id="col_001",
                run_id="run_001",
                lease_id="lease_001",
                changed_files=(
                    ChangedFileFact(
                        relative_path="out/a.md",
                        change_kind=WorkspaceChangeKind.MODIFIED,
                        content_kind=WorkspaceContentKind.TEXT,
                        byte_size=10,
                        exportable=True,
                    ),
                ),
                exportable_artifacts=(),
            )

    def test_change_fact_must_explain_a_non_promotion(self):
        base = {
            "relative_path": "src/a.py",
            "change_kind": WorkspaceChangeKind.MODIFIED,
            "content_kind": WorkspaceContentKind.TEXT,
            "byte_size": 10,
        }
        with self.assertRaises(ContractError):
            ChangedFileFact(**base, exportable=False, promotion_block=None)
        with self.assertRaises(ContractError):
            ChangedFileFact(
                **base,
                exportable=True,
                promotion_block=ArtifactPromotionBlock.ARTIFACT_CLASS_NOT_ALLOWLISTED,
            )


class ProjectionSafetyTests(unittest.TestCase):

    FORBIDDEN_KEYS = (
        "host",
        "mount",
        "endpoint",
        "provider",
        "socket",
        "credential",
        "secret",
        "inode",
        "device",
        "resolved",
        "realpath",
        "driver",
        "abs",
    )

    def test_projection_leaks_no_host_provider_mount_or_runtime_metadata(self):
        result = collecting(
            candidate("out/a.md", text_excerpt="body"),
            candidate("out/dup.md"),
            candidate("out/dup.md", sha=OTHER_DIGEST),
            candidate("/etc/passwd"),
            candidate("C:/Windows/x.md"),
            candidate("out/link.md", symlink_or_reparse=True),
            candidate("notes/hidden.md"),
            candidate("src/app.py", text_excerpt="token=fake-token-value-11"),
        )
        projection = result.safe_dict()
        for key in projection:
            self.assertEqual([t for t in self.FORBIDDEN_KEYS if t in key.lower()], [], key)
        for item in projection["exportable_artifacts"]:
            for key in item:
                self.assertEqual([t for t in self.FORBIDDEN_KEYS if t in key.lower()], [], key)
        for item in projection["changed_files"]:
            for key in item:
                self.assertEqual([t for t in self.FORBIDDEN_KEYS if t in key.lower()], [], key)

        dumped = repr(projection)
        for leak in ("/etc", "C:", "\\\\", "://", "passwd", "fake-token-value-11"):
            self.assertNotIn(leak, dumped)
        self.assertIs(projection["unredacted_excerpt_in_projection"], False)
        self.assertIs(projection["filesystem_scan_performed"], False)
        self.assertIs(projection["deleted_candidate_requires_content_read"], False)
        self.assertEqual([k for k in projection if "host" in k.lower()], [])

    def test_rejections_do_not_echo_the_refused_path(self):
        for path in ("/etc/passwd", "C:/Windows/x.md", "out/.env"):
            with self.subTest(path=path):
                rejected = collecting(candidate(path)).rejected[0]
                dumped = repr(rejected.safe_dict())
                for fragment in ("passwd", "Windows", ".env", "/etc", "C:"):
                    self.assertNotIn(fragment, dumped)

    def test_closed_reason_and_block_vocabularies(self):
        self.assertEqual(
            {item.value for item in CandidateRejection},
            {
                "symlink_or_reparse_denied",
                "path_refused_by_workspace_authority",
                "path_not_readable_by_workspace_authority",
                "duplicate_relative_path_ambiguous",
                "deleted_candidate_carries_content",
                "binary_candidate_carries_content",
                "text_excerpt_exceeds_input_limit",
            },
        )
        self.assertEqual(
            {item.value for item in ArtifactPromotionBlock},
            {
                "artifact_class_not_allowlisted",
                "byte_size_exceeds_candidate_limit",
                "candidate_count_exceeds_limit",
                "aggregate_bytes_exceed_limit",
            },
        )


class CollectorPurityTests(unittest.TestCase):

    def test_collector_has_no_filesystem_network_or_subprocess_capability(self):
        module = inspect.getmodule(WorkspaceArtifactCollector)
        assert module is not None
        source = inspect.getsource(module)
        for token in (
            "os.walk",
            "rglob",
            "glob(",
            "realpath",
            ".resolve(",
            "subprocess",
            "open(",
            "shutil",
            "socket",
            "urllib",
            "http.client",
            "hashlib",
            "git ",
            "import os",
            "import pathlib",
            "Path(",
            "listdir",
            "scandir",
            "stat(",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, source)
        for name in ("os", "pathlib", "subprocess", "shutil", "socket", "urllib", "glob"):
            self.assertFalse(hasattr(module, name), name)
        self.assertTrue(WORKSPACE_ARTIFACT_COLLECTOR_DISCOVERS_NO_PATHS)
        self.assertTrue(WORKSPACE_ARTIFACT_COLLECTOR_PERFORMS_NO_FILESYSTEM_SCAN)

    def test_secret_patterns_are_reused_not_reinvented(self):
        # Asserted structurally rather than by naming credential keywords. An earlier form
        # listed ("Bearer", "api_key", "password", ...) as the strings to look for, and
        # that literal tuple was itself what GitGuardian's generic-password detector
        # flagged. Claiming "no second secret grammar exists" is better proven by counting
        # what the module compiles, which also fails if a third pattern is ever added.
        module = inspect.getmodule(WorkspaceArtifactCollector)
        assert module is not None
        source = inspect.getsource(module)
        self.assertIn("from .security import redact_secrets", source)
        self.assertEqual(source.count("redact_secrets("), 1, "one delegation, no local copy")
        # The only compiled patterns here are the digest and identifier shape validators.
        self.assertEqual(len(re.findall(r"re\.compile\(", source)), 2)
        self.assertIn("_SHA256_RE", source)
        self.assertIn("_SAFE_REFERENCE_RE", source)

    def test_collector_requires_the_merged_workspace_authority_type(self):
        for invalid in ("not-a-policy", None, object()):
            with self.subTest(path_policy=invalid):
                with self.assertRaises(ContractError):
                    WorkspaceArtifactCollector(path_policy=invalid)
        with self.assertRaises(ContractError):
            WorkspaceArtifactCollector(
                path_policy=CloudWorkspacePathPolicy(), export_policy="nope"
            )
        self.assertTrue(PATH_AUTHORITY_OWNED_BY_CLOUD_WORKSPACE_PATH_POLICY)

    def test_malformed_request_identifiers_fail_as_caller_errors(self):
        collector = WorkspaceArtifactCollector(path_policy=DEFAULT_PATH_POLICY)
        for bad in ("bad id", "", None):
            for field in ("collection_id", "run_id", "lease_id"):
                with self.subTest(field=field, value=bad):
                    arguments = {
                        "collection_id": "col_001",
                        "run_id": "run_001",
                        "lease_id": "lease_001",
                        "candidates": (candidate("out/a.md"),),
                    }
                    arguments[field] = bad
                    with self.assertRaises(ContractError):
                        collector.collect(**arguments)

    def test_candidate_record_is_strict_but_still_accepts_hostile_facts(self):
        self.assertTrue(candidate("out/x.md", symlink_or_reparse=True).symlink_or_reparse)
        for bad in (
            {"relative_path": ""},
            {"relative_path": "   "},
            {"relative_path": None},
            {"byte_size": -1},
            {"byte_size": True},
            {"byte_size": "10"},
            {"content_sha256": "not-a-digest"},
            {"content_sha256": "a" * 63},
            {"change_kind": "renamed"},
            {"content_kind": "archive"},
            {"symlink_or_reparse": "yes"},
            {"text_excerpt": 12},
        ):
            with self.subTest(**bad):
                fields: dict[str, object] = {
                    "relative_path": "out/a.md",
                    "change_kind": WorkspaceChangeKind.MODIFIED,
                    "content_kind": WorkspaceContentKind.TEXT,
                    "byte_size": 100,
                    "content_sha256": DIGEST,
                }
                fields.update(bad)
                with self.assertRaises(ContractError):
                    WorkspaceChangeCandidate(**fields)  # type: ignore[arg-type]

    def test_digest_is_normalised_to_lowercase_like_the_export_contract(self):
        record = candidate("out/a.md", content_sha256="A" * 64)
        self.assertEqual(record.content_sha256, DIGEST)

    def test_collected_artifact_still_refuses_an_over_limit_excerpt(self):
        with self.assertRaises(ContractError):
            CollectedArtifact(
                candidate=SandboxArtifactCandidate(
                    artifact_id="a_1",
                    run_id="run_001",
                    lease_id="lease_001",
                    path="out/a.md",
                    kind="modified",
                    size_bytes=10,
                    sha256=DIGEST,
                ),
                text_excerpt="y" * (_EXCERPT_LIMIT + 1),
            )

    def test_rejected_candidate_shape_is_strict(self):
        with self.assertRaises(ContractError):
            RejectedCandidate(slot=-1, reason=CandidateRejection.SYMLINK_OR_REPARSE)
        with self.assertRaises(ContractError):
            RejectedCandidate(slot=0, reason="not-a-real-reason")
        with self.assertRaises(ContractError):
            RejectedCandidate(slot=True, reason=CandidateRejection.SYMLINK_OR_REPARSE)

    def test_nothing_is_claimed_as_wired(self):
        self.assertFalse(REAL_WORKSPACE_ARTIFACT_COLLECTION_CONFIGURED)
        self.assertIsInstance(
            collecting(candidate("out/a.md")), ArtifactCandidateCollection
        )


if __name__ == "__main__":
    unittest.main()
