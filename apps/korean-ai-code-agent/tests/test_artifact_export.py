from __future__ import annotations

import hashlib
import unittest

from kagent.artifact_export import (
    REAL_ARTIFACT_EXPORT_CONFIGURED,
    ArtifactExportManifest,
    ArtifactExportPolicy,
    SandboxArtifactCandidate,
    UnconfiguredArtifactExportPort,
)
from kagent.contracts import ContractError


DIGEST = hashlib.sha256(b"artifact").hexdigest()


def artifact(path="reports/result.json", *, artifact_id="a1", size=100, run_id="run_1", lease_id="lease_1"):
    return SandboxArtifactCandidate(
        artifact_id=artifact_id,
        run_id=run_id,
        lease_id=lease_id,
        path=path,
        kind="report",
        size_bytes=size,
        sha256=DIGEST,
    )


class ArtifactExportTests(unittest.TestCase):
    def test_safe_relative_allowlisted_artifact(self):
        item = artifact()
        self.assertFalse(item.safe_dict()["raw_content_in_projection"])

    def test_absolute_traversal_backslash_and_control_paths_fail(self):
        for path in ("/tmp/a.json", "../a.json", "a/../b.json", "a\\b.json", "a\nb.json"):
            with self.subTest(path=path):
                with self.assertRaises(ContractError):
                    artifact(path)

    def test_dotenv_private_key_database_and_binary_classes_fail(self):
        for path in (
            "out/.env",
            "out/.env.production",
            "out/id_rsa",
            "out/private.pem",
            "out/private.key",
            "out/cache.db",
            "out/cache.sqlite",
            "out/app.exe",
            "out/lib.so",
        ):
            with self.subTest(path=path):
                with self.assertRaises(ContractError):
                    artifact(path)

    def test_non_allowlisted_extension_fails(self):
        with self.assertRaises(ContractError):
            artifact("out/archive.zip")

    def test_symlink_is_never_exportable(self):
        with self.assertRaises(ContractError):
            SandboxArtifactCandidate("a1", "run_1", "lease_1", "out/a.json", "report", 1, DIGEST, True)

    def test_digest_must_be_exact_sha256(self):
        with self.assertRaises(ContractError):
            SandboxArtifactCandidate("a1", "run_1", "lease_1", "out/a.json", "report", 1, "abc")

    def test_manifest_rejects_duplicate_id_and_path(self):
        with self.assertRaises(ContractError):
            ArtifactExportManifest("m1", "run_1", "lease_1", (artifact(), artifact("other.json", artifact_id="a1")))
        with self.assertRaises(ContractError):
            ArtifactExportManifest("m1", "run_1", "lease_1", (artifact(), artifact(artifact_id="a2")))

    def test_manifest_rejects_cross_run_or_lease_mix(self):
        with self.assertRaises(ContractError):
            ArtifactExportManifest("m1", "run_1", "lease_1", (artifact(run_id="run_2"),))
        with self.assertRaises(ContractError):
            ArtifactExportManifest("m1", "run_1", "lease_1", (artifact(lease_id="lease_2"),))

    def test_policy_enforces_file_count_individual_and_total_bytes(self):
        policy = ArtifactExportPolicy(max_files=2, max_file_bytes=1024, max_total_bytes=1500)
        with self.assertRaises(ContractError):
            ArtifactExportManifest("m1", "run_1", "lease_1", (artifact(size=1025),)).validate_against(policy)
        with self.assertRaises(ContractError):
            ArtifactExportManifest(
                "m1", "run_1", "lease_1",
                (artifact(size=800), artifact("out/b.json", artifact_id="a2", size=800)),
            ).validate_against(policy)
        with self.assertRaises(ContractError):
            ArtifactExportManifest(
                "m1", "run_1", "lease_1",
                (artifact(size=1), artifact("out/b.json", artifact_id="a2", size=1), artifact("out/c.json", artifact_id="a3", size=1)),
            ).validate_against(policy)

    def test_safe_manifest_contains_hash_metadata_not_raw_content(self):
        manifest = ArtifactExportManifest("m1", "run_1", "lease_1", (artifact(),))
        manifest.validate_against(ArtifactExportPolicy())
        rendered = manifest.safe_dict()
        self.assertFalse(rendered["raw_content_in_manifest"])
        self.assertEqual(rendered["artifacts"][0]["sha256"], DIGEST)

    def test_default_real_export_fails_closed(self):
        self.assertFalse(REAL_ARTIFACT_EXPORT_CONFIGURED)
        with self.assertRaises(ContractError):
            UnconfiguredArtifactExportPort().export(ArtifactExportManifest("m1", "run_1", "lease_1", (artifact(),)))


if __name__ == "__main__":
    unittest.main()
