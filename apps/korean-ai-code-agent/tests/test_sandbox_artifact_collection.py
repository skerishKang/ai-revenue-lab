from __future__ import annotations

import inspect
import random
import unittest

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
    WORKSPACE_ARTIFACT_COLLECTOR_DISCOVERS_NO_PATHS,
    WORKSPACE_ARTIFACT_COLLECTOR_PERFORMS_NO_FILESYSTEM_SCAN,
    ArtifactCandidateCollection,
    CandidateRejection,
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

DIGEST = "a" * 64
OTHER_DIGEST = "b" * 64


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


class WorkspaceArtifactCollectorTests(unittest.TestCase):
    """#2765: project already-observed change facts under authorities owned elsewhere."""

    def collecting(self, *candidates: WorkspaceChangeCandidate, **kwargs):
        policy = kwargs.pop("path_policy", None)
        export = kwargs.pop("export_policy", None)
        collector = WorkspaceArtifactCollector(
            path_policy=policy
            or CloudWorkspacePathPolicy(
                rules=(
                    CloudWorkspacePathRule("out", readable=True),
                    CloudWorkspacePathRule("src", readable=True),
                )
            ),
            export_policy=export or ArtifactExportPolicy(),
        )
        return collector.collect(
            collection_id=kwargs.pop("collection_id", "col_001"),
            run_id=kwargs.pop("run_id", "run_001"),
            lease_id=kwargs.pop("lease_id", "lease_001"),
            candidates=candidates,
        )

    # --- acceptance -------------------------------------------------------------

    def test_canonical_relative_readable_candidate_accepted(self):
        result = self.collecting(candidate("out/report.md"))
        self.assertEqual(result.exportable_count, 1)
        self.assertEqual(result.rejected, ())
        entry = result.entries[0]
        self.assertIsInstance(entry.candidate, SandboxArtifactCandidate)
        self.assertEqual(entry.candidate.path, "out/report.md")
        self.assertEqual(entry.candidate.kind, "modified")
        self.assertEqual(entry.candidate.sha256, DIGEST)

    def test_manifest_is_the_existing_export_contract(self):
        result = self.collecting(
            candidate("out/a.md"), candidate("src/b.json", sha=OTHER_DIGEST)
        )
        manifest = result.manifest
        self.assertIsInstance(manifest, ArtifactExportManifest)
        assert manifest is not None
        self.assertEqual(manifest.run_id, "run_001")
        self.assertEqual(manifest.lease_id, "lease_001")
        self.assertEqual(manifest.total_bytes, 200)
        manifest.validate_against(ArtifactExportPolicy())

    def test_deleted_candidate_never_requires_reading_the_host(self):
        result = self.collecting(
            candidate("out/gone.md", change_kind=WorkspaceChangeKind.DELETED)
        )
        self.assertEqual(result.exportable_count, 1)
        entry = result.entries[0]
        self.assertIsNone(entry.text_excerpt)
        self.assertEqual(entry.candidate.kind, "deleted")
        # The evidence is the last observed digest, not a re-read of the path.
        self.assertEqual(entry.candidate.sha256, DIGEST)
        self.assertFalse(DELETED_CANDIDATE_REQUIRES_HOST_READ)

    def test_deleted_candidate_carrying_content_is_rejected(self):
        result = self.collecting(
            candidate(
                "out/gone.md",
                change_kind=WorkspaceChangeKind.DELETED,
                text_excerpt="recovered body",
            )
        )
        self.assertEqual(result.exportable_count, 0)
        self.assertEqual(
            result.rejected[0].reason,
            CandidateRejection.DELETED_CANDIDATE_CARRIES_CONTENT,
        )

    # --- path authority (delegated, never reimplemented) ------------------------

    def test_unmatched_path_rejected_as_not_readable(self):
        result = self.collecting(candidate("notes/private.md"))
        self.assertEqual(result.exportable_count, 0)
        self.assertEqual(
            result.rejected[0].reason, CandidateRejection.PATH_NOT_READABLE
        )

    def test_read_denied_but_write_granted_path_is_still_rejected(self):
        policy = CloudWorkspacePathPolicy(
            rules=(CloudWorkspacePathRule("out", writable=True, readable=False, delete_allowed=True),)
        )
        result = self.collecting(candidate("out/report.md"), path_policy=policy)
        self.assertEqual(result.exportable_count, 0)
        self.assertEqual(result.rejected[0].reason, CandidateRejection.PATH_NOT_READABLE)

    def test_symlink_or_reparse_candidate_rejected(self):
        for flag in (True,):
            with self.subTest(symlink_or_reparse=flag):
                result = self.collecting(candidate("out/evil.md", symlink_or_reparse=flag))
                self.assertEqual(result.exportable_count, 0)
                self.assertEqual(
                    result.rejected[0].reason, CandidateRejection.SYMLINK_OR_REPARSE
                )

    def test_hostile_path_forms_rejected_by_the_workspace_authority(self):
        hostile = (
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
        )
        for path in hostile:
            with self.subTest(path=path):
                result = self.collecting(candidate(path))
                self.assertEqual(result.exportable_count, 0)
                self.assertEqual(
                    result.rejected[0].reason,
                    CandidateRejection.PATH_REFUSED_BY_WORKSPACE_AUTHORITY,
                )

    def test_collection_never_widens_write_or_delete_authority(self):
        policy = CloudWorkspacePathPolicy(rules=(CloudWorkspacePathRule("out", readable=True),))
        result = self.collecting(candidate("out/report.md"), path_policy=policy)
        self.assertEqual(result.exportable_count, 1)
        self.assertFalse(policy.authorize("out/report.md", WorkspacePathOperation.WRITE))
        self.assertFalse(
            policy.authorize("out/report.md", WorkspacePathOperation.DELETE)
        )

    def test_artifact_class_allowlist_is_inherited_not_widened(self):
        # src/app.py is readable, yet not an exportable artifact class. Refusing it here
        # is the existing artifact_export contract speaking, not a new authority.
        result = self.collecting(candidate("src/app.py"))
        self.assertEqual(result.exportable_count, 0)
        self.assertEqual(
            result.rejected[0].reason, CandidateRejection.REFUSED_BY_ARTIFACT_CLASS_POLICY
        )

    # --- bounds -----------------------------------------------------------------

    def test_candidate_count_bound(self):
        export = ArtifactExportPolicy(max_files=2, max_file_bytes=1024, max_total_bytes=1024)
        result = self.collecting(
            candidate("out/a.md", bs=10),
            candidate("out/b.md", bs=10, sha=OTHER_DIGEST),
            candidate("out/c.md", bs=10),
            export_policy=export,
        )
        self.assertEqual(result.exportable_count, 2)
        self.assertEqual(
            [item.reason for item in result.rejected],
            [CandidateRejection.CANDIDATE_COUNT_EXCEEDS_LIMIT],
        )

    def test_input_count_closed_ceiling_raises(self):
        collector = WorkspaceArtifactCollector(path_policy=CloudWorkspacePathPolicy())
        with self.assertRaises(ContractError):
            collector.collect(
                collection_id="col_001",
                run_id="run_001",
                lease_id="lease_001",
                candidates=tuple(candidate(f"out/{n}.md") for n in range(201)),
            )

    def test_per_candidate_byte_bound(self):
        export = ArtifactExportPolicy(max_files=50, max_file_bytes=1024, max_total_bytes=1024)
        result = self.collecting(candidate("out/huge.md", bs=5000), export_policy=export)
        self.assertEqual(result.exportable_count, 0)
        self.assertEqual(
            result.rejected[0].reason, CandidateRejection.BYTE_SIZE_EXCEEDS_CANDIDATE_LIMIT
        )

    def test_aggregate_byte_bound(self):
        export = ArtifactExportPolicy(max_files=50, max_file_bytes=4096, max_total_bytes=5000)
        result = self.collecting(
            candidate("out/a.md", bs=3000),
            candidate("out/b.md", bs=3000, sha=OTHER_DIGEST),
            export_policy=export,
        )
        self.assertEqual(result.exportable_count, 1)
        self.assertEqual(result.aggregate_bytes, 3000)
        self.assertEqual(
            result.rejected[0].reason, CandidateRejection.AGGREGATE_BYTES_EXCEED_LIMIT
        )

    # --- bounded text -----------------------------------------------------------

    def test_text_truncation_is_deterministic_explicit_and_bounded(self):
        body = "x" * 9_000
        first = self.collecting(candidate("out/a.md", text_excerpt=body))
        second = self.collecting(candidate("out/a.md", text_excerpt=body))
        entry = first.entries[0]
        self.assertTrue(entry.excerpt_truncated)
        self.assertEqual(len(entry.text_excerpt or ""), 4_096)
        self.assertEqual(entry.text_excerpt, body[:4_096])
        self.assertEqual(first.safe_dict(), second.safe_dict())

    def test_short_excerpt_is_kept_verbatim_and_flagged_untouched(self):
        entry = self.collecting(candidate("out/a.md", text_excerpt="brief note")).entries[0]
        self.assertEqual(entry.text_excerpt, "brief note")
        self.assertFalse(entry.excerpt_truncated)

    def test_collected_entry_refuses_an_over_limit_excerpt(self):
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
                text_excerpt="y" * 5_000,
            )

    # --- binary and projection safety -------------------------------------------

    def test_binary_candidate_projects_metadata_only(self):
        result = self.collecting(
            candidate("out/build.log", content_kind=WorkspaceContentKind.BINARY)
        )
        self.assertEqual(result.exportable_count, 1)
        projected = result.entries[0].safe_dict()
        self.assertIsNone(projected["text_excerpt"])
        self.assertFalse(projected["raw_content_in_projection"])
        self.assertNotIn("\x00", str(projected))
        self.assertFalse(RAW_BINARY_BYTES_PROJECTED)

    def test_binary_candidate_carrying_body_is_rejected(self):
        result = self.collecting(
            candidate(
                "out/build.log",
                content_kind=WorkspaceContentKind.BINARY,
                text_excerpt="\x00\x01binary",
            )
        )
        self.assertEqual(result.exportable_count, 0)
        self.assertEqual(
            result.rejected[0].reason, CandidateRejection.BINARY_CANDIDATE_CARRIES_CONTENT
        )

    def test_safe_projection_leaks_no_host_provider_mount_or_runtime_metadata(self):
        result = self.collecting(
            candidate("out/a.md", text_excerpt="body"),
            candidate("out/dup.md"),
            candidate("out/dup.md", sha=OTHER_DIGEST),
            candidate("/etc/passwd"),
            candidate("C:/Windows/x.md"),
            candidate("out/link.md", symlink_or_reparse=True),
            candidate("notes/hidden.md"),
        )
        projection = result.safe_dict()
        forbidden_keys = (
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
        for key in projection:
            self.assertEqual([t for t in forbidden_keys if t in key.lower()], [], key)
        for item in projection["exportable"]:
            for key in item:
                self.assertEqual([t for t in forbidden_keys if t in key.lower()], [], key)

        dumped = repr(projection)
        for leak in ("/etc", "C:", "\\\\", "://", "passwd"):
            self.assertNotIn(leak, dumped)
        self.assertTrue(projection["raw_binary_in_projection"] is False)
        self.assertTrue(projection["filesystem_scan_performed"] is False)
        # Pinned so the denial survives a rename: no entry was produced by reading back a
        # deleted path, and the projection says so under a token-clean key.
        self.assertTrue(projection["deleted_candidate_requires_content_read"] is False)
        self.assertEqual(
            [key for key in projection if "host" in key.lower()], [], "no host token in keys"
        )

    def test_rejections_do_not_echo_the_refused_path(self):
        result = self.collecting(candidate("/etc/passwd"))
        self.assertEqual(
            result.rejected[0].reason, CandidateRejection.PATH_REFUSED_BY_WORKSPACE_AUTHORITY
        )
        self.assertNotIn(
            "passwd", repr(result.rejected[0].safe_dict()), "refused path must not be projected"
        )
        self.assertNotIn("/etc", repr(result.rejected[0].safe_dict()))

    # --- determinism ------------------------------------------------------------

    def test_duplicate_path_fails_closed_under_one_deterministic_rule(self):
        result = self.collecting(
            candidate("out/a.md"),
            candidate("out/a.md", sha=OTHER_DIGEST),
            candidate("out/a.md", change_kind=WorkspaceChangeKind.ADDED),
        )
        self.assertEqual(result.exportable_count, 0)
        self.assertEqual(
            {item.reason for item in result.rejected},
            {CandidateRejection.DUPLICATE_PATH_AMBIGUOUS},
        )
        self.assertEqual(len(result.rejected), 3)

    def test_identical_input_produces_identical_projection(self):
        facts = (
            candidate("out/a.md", text_excerpt="one"),
            candidate("src/b.json", sha=OTHER_DIGEST, bs=77),
            candidate("out/c.md", symlink_or_reparse=True),
        )
        self.assertEqual(
            self.collecting(*facts).safe_dict(), self.collecting(*facts).safe_dict()
        )

    def test_input_order_does_not_change_the_projection(self):
        facts = (
            candidate("out/a.md", bs=10),
            candidate("out/b.md", bs=20, sha=OTHER_DIGEST),
            candidate("src/c.md", bs=30),
            candidate("out/bad.md", symlink_or_reparse=True),
        )
        baseline = self.collecting(*facts).safe_dict()
        for seed in range(5):
            shuffled = list(facts)
            random.Random(seed).shuffle(shuffled)
            with self.subTest(seed=seed):
                self.assertEqual(self.collecting(*shuffled).safe_dict(), baseline)

    def test_empty_candidate_set_yields_no_manifest_but_a_full_report(self):
        result = self.collecting()
        self.assertIsNone(result.manifest)
        self.assertEqual(result.exportable_count, 0)
        self.assertEqual(result.aggregate_bytes, 0)
        self.assertEqual(result.rejected, ())

    def test_all_rejected_input_yields_no_manifest(self):
        result = self.collecting(candidate("/etc/passwd"), candidate("notes/x.md"))
        self.assertIsNone(result.manifest)
        self.assertEqual(len(result.rejected), 2)

    # --- purity of the collector --------------------------------------------------

    def test_collector_has_no_filesystem_network_or_subprocess_capability(self):
        module = inspect.getmodule(WorkspaceArtifactCollector)
        assert module is not None
        source = inspect.getsource(module)
        forbidden = (
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
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, source)
        for name in ("os", "pathlib", "subprocess", "shutil", "socket", "urllib", "glob"):
            self.assertFalse(hasattr(module, name), name)
        self.assertTrue(WORKSPACE_ARTIFACT_COLLECTOR_DISCOVERS_NO_PATHS)
        self.assertTrue(WORKSPACE_ARTIFACT_COLLECTOR_PERFORMS_NO_FILESYSTEM_SCAN)

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
        for bad in ("bad id", "", None):
            with self.subTest(collection_id=bad):
                collector = WorkspaceArtifactCollector(path_policy=CloudWorkspacePathPolicy())
                with self.assertRaises(ContractError):
                    collector.collect(
                        collection_id=bad,
                        run_id="run_001",
                        lease_id="lease_001",
                        candidates=(candidate("out/a.md"),),
                    )

    def test_reject_vocabulary_is_closed(self):
        for entry in self.collecting(
            candidate("/abs.md"), candidate("notes/x.md"), candidate("out/y.md", symlink_or_reparse=True)
        ).rejected:
            self.assertIsInstance(entry.reason, CandidateRejection)
        self.assertEqual(
            {item.value for item in CandidateRejection},
            {
                "symlink_or_reparse_denied",
                "path_refused_by_workspace_authority",
                "path_not_readable_by_workspace_authority",
                "duplicate_relative_path_ambiguous",
                "deleted_candidate_carries_content",
                "binary_candidate_carries_content",
                "byte_size_exceeds_candidate_limit",
                "aggregate_bytes_exceed_limit",
                "candidate_count_exceeds_limit",
                "refused_by_artifact_class_policy",
            },
        )

    def test_candidate_record_is_strict_but_still_accepts_hostile_facts(self):
        # A hostile record must be constructible so the collector is what denies it.
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
        self.assertEqual(record.content_sha256, "a" * 64)
        result = self.collecting(record)
        self.assertEqual(result.entries[0].candidate.sha256, DIGEST)

    def test_rejected_candidate_shape_is_strict(self):
        with self.assertRaises(ContractError):
            RejectedCandidate(slot=-1, reason=CandidateRejection.SYMLINK_OR_REPARSE)
        with self.assertRaises(ContractError):
            RejectedCandidate(slot=0, reason="not-a-real-reason")
        with self.assertRaises(ContractError):
            RejectedCandidate(slot=True, reason=CandidateRejection.SYMLINK_OR_REPARSE)

    def test_nothing_is_claimed_as_wired(self):
        self.assertFalse(REAL_WORKSPACE_ARTIFACT_COLLECTION_CONFIGURED)
        self.assertTrue(WORKSPACE_ARTIFACT_COLLECTOR_DISCOVERS_NO_PATHS)
        result = self.collecting(candidate("out/a.md"))
        self.assertIsInstance(result, ArtifactCandidateCollection)


if __name__ == "__main__":
    unittest.main()
