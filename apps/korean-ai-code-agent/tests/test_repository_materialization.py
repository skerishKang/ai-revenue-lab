from __future__ import annotations

import hashlib
import unittest

from kagent.contracts import ContractError
from kagent.repository_materialization import (
    REAL_GIT_NETWORK_MATERIALIZATION_CONFIGURED,
    DeterministicFakeRepositoryMaterializer,
    RepositoryMaterializationPolicy,
    RepositoryMaterializationReceipt,
    RepositoryMaterializationRequest,
    UnconfiguredRepositoryMaterializer,
)


REV = "abcdef1234567890abcdef1234567890abcdef12"
DIGEST = hashlib.sha256(b"tree").hexdigest()


def request(revision=REV, repository="skerishKang/example"):
    return RepositoryMaterializationRequest("mat_1", "run_1", "lease_1", repository, revision)


class RepositoryMaterializationTests(unittest.TestCase):
    def test_request_requires_owner_repo_and_exact_40_hex_revision(self):
        self.assertEqual(request().exact_revision, REV)
        for repository in ("https://github.com/o/r", "o", "o/r/extra", "../o/r"):
            with self.subTest(repository=repository):
                with self.assertRaises(ContractError):
                    request(repository=repository)
        for revision in ("main", "v1.0.0", "abcdef1", "g" * 40):
            with self.subTest(revision=revision):
                with self.assertRaises(ContractError):
                    request(revision=revision)

    def test_policy_cannot_enable_hooks_submodules_lfs_credentials_or_symlinks(self):
        for field_name in (
            "checkout_hooks_enabled",
            "submodules_enabled",
            "lfs_enabled",
            "credential_helper_inheritance",
            "symlink_entries_allowed",
        ):
            with self.subTest(field_name=field_name):
                with self.assertRaises(ContractError):
                    RepositoryMaterializationPolicy(**{field_name: True})

    def test_receipt_observed_revision_must_equal_requested(self):
        with self.assertRaises(ContractError):
            RepositoryMaterializationReceipt(
                "mat_1", "run_1", "lease_1", "skerishKang/example", REV,
                "1234567890abcdef1234567890abcdef12345678", DIGEST, 1, 10,
            )

    def test_receipt_correlation_mismatch_fails_closed(self):
        receipt = RepositoryMaterializationReceipt(
            "mat_1", "run_2", "lease_1", "skerishKang/example", REV, REV, DIGEST, 1, 10,
        )
        with self.assertRaises(ContractError):
            receipt.validate_against(request(), RepositoryMaterializationPolicy())

    def test_file_count_size_and_symlink_policy_are_enforced(self):
        policy = RepositoryMaterializationPolicy(max_files=2, max_bytes=100)
        for fake in (
            DeterministicFakeRepositoryMaterializer(file_count=3, materialized_bytes=10),
            DeterministicFakeRepositoryMaterializer(file_count=1, materialized_bytes=101),
            DeterministicFakeRepositoryMaterializer(file_count=1, materialized_bytes=10, symlink_count=1),
        ):
            with self.assertRaises(ContractError):
                fake.materialize(request(), policy)

    def test_network_free_fake_produces_provenance_receipt(self):
        fake = DeterministicFakeRepositoryMaterializer(file_count=12, materialized_bytes=1234)
        receipt = fake.materialize(request(), RepositoryMaterializationPolicy())
        self.assertEqual(receipt.observed_revision, REV)
        self.assertEqual(receipt.file_count, 12)
        self.assertFalse(receipt.safe_dict()["repository_content_in_receipt"])
        self.assertEqual(len(fake.requests), 1)

    def test_request_safe_projection_explicitly_disables_mutable_features(self):
        rendered = request().safe_dict()
        self.assertFalse(rendered["mutable_ref_input"])
        self.assertFalse(rendered["submodules"])
        self.assertFalse(rendered["lfs"])
        self.assertFalse(rendered["checkout_hooks"])
        self.assertFalse(rendered["credential_helper_inheritance"])

    def test_default_real_materializer_fails_closed(self):
        self.assertFalse(REAL_GIT_NETWORK_MATERIALIZATION_CONFIGURED)
        with self.assertRaises(ContractError):
            UnconfiguredRepositoryMaterializer().materialize(request(), RepositoryMaterializationPolicy())


if __name__ == "__main__":
    unittest.main()
