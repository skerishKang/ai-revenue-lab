from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_pages_provisioning.py"
SPEC = importlib.util.spec_from_file_location("validator", SCRIPT)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)

SHA = "4da83a879a861c8e80edd2d5f76ea4268de3d5ad"
OTHER_SHA = "12ead3c03a7355fcc364648bf0a6169ee86153a1"
SHA_37 = "1e5beecaea878611d27384dfb0ba86ff7c6d98a1"
MERGE_SHA_37 = "0142c41b1f159e532fd87c3b036b793271e60979"
OWNER_LOGIN = "skerishKang"
REPOSITORY = "skerishKang/ai-revenue-lab"
REPOSITORY_METADATA = {
    "owner_login": OWNER_LOGIN,
    "owner_id": "36503867",
    "repository_name": "ai-revenue-lab",
    "repository_id": "1306003434",
    "repository_full_name": REPOSITORY,
}
PROJECT_NAME = "ai-revenue-business-18-personal-audio-channel"
SOURCE_DIRECTORY = "reference/business-18-personal-audio-channel-v1"


class InputValidationTests(unittest.TestCase):
    def valid(self, **overrides: str) -> dict[str, str]:
        values = {
            "business_id": "18",
            "project_name": PROJECT_NAME,
            "source_directory": SOURCE_DIRECTORY,
            "approved_sha": SHA,
            "approval_pr": "203",
            "production_branch": "main",
        }
        values.update(overrides)
        return values

    def assert_invalid(self, **overrides: str) -> None:
        with self.assertRaises(validator.ValidationError):
            validator.validate_inputs(**self.valid(**overrides))

    def test_valid_contract(self) -> None:
        validator.validate_inputs(**self.valid())

    def test_rejects_malformed_project_name(self) -> None:
        self.assert_invalid(project_name="ai-revenue-world-feed")
        self.assert_invalid(project_name="ai-revenue-business-18-a;echo-pwned")

    def test_rejects_business_number_mismatch(self) -> None:
        self.assert_invalid(project_name="ai-revenue-business-20-personal-memory-novel")
        self.assert_invalid(source_directory="reference/business-20-personal-memory-novel-v1")

    def test_rejects_path_traversal_absolute_and_shell_path(self) -> None:
        self.assert_invalid(source_directory="reference/business-18-../apps")
        self.assert_invalid(source_directory="/reference/business-18-personal-audio-channel-v1")
        self.assert_invalid(source_directory="reference/business-18-a;rm-rf")

    def test_rejects_bad_sha(self) -> None:
        self.assert_invalid(approved_sha=SHA[:12])
        self.assert_invalid(approved_sha=SHA.upper())

    def test_rejects_bad_pr_and_branch(self) -> None:
        self.assert_invalid(approval_pr="0")
        self.assert_invalid(production_branch="feat/business-18")


class RepositoryMetadataTests(unittest.TestCase):
    def payload(self, **overrides):
        payload = {
            "id": 1306003434,
            "name": "ai-revenue-lab",
            "full_name": REPOSITORY,
            "owner": {"login": OWNER_LOGIN, "id": 36503867, "type": "User"},
        }
        payload.update(overrides)
        return payload

    def test_verifies_owner_and_repository_identity(self) -> None:
        self.assertEqual(
            validator.verify_repository_payload(self.payload(), REPOSITORY),
            REPOSITORY_METADATA,
        )

    def test_rejects_repository_owner_name_or_id_mismatch(self) -> None:
        with self.assertRaises(validator.ValidationError):
            validator.verify_repository_payload(
                self.payload(owner={"login": "other-owner", "id": 36503867}),
                REPOSITORY,
            )
        with self.assertRaises(validator.ValidationError):
            validator.verify_repository_payload(
                self.payload(name="other-repository"), REPOSITORY
            )
        with self.assertRaises(validator.ValidationError):
            validator.verify_repository_payload(self.payload(id=0), REPOSITORY)
        with self.assertRaises(validator.ValidationError):
            validator.verify_repository_payload(
                self.payload(owner={"login": OWNER_LOGIN, "id": 0}), REPOSITORY
            )


class ApprovalAuthorityTests(unittest.TestCase):
    def pr_payload(self, **overrides):
        payload = {
            "base": {"repo": {"full_name": REPOSITORY}},
            "head": {"sha": SHA},
            "state": "open",
            "draft": True,
            "merged": False,
        }
        payload.update(overrides)
        return payload

    def owner_comment(self, **overrides):
        comment = {
            "id": 5085200000,
            "body": (
                "## Web CTO final visual review\n\n"
                "UI_APPROVED\n\n"
                f"Approved exact head: `{SHA}`"
            ),
            "user": {"login": OWNER_LOGIN, "type": "User"},
            "author_association": "OWNER",
            "pull_request_review_id": None,
            "in_reply_to_id": None,
        }
        comment.update(overrides)
        return comment

    def test_accepts_owner_authored_approval_fixtures_for_203_206_207(self) -> None:
        fixtures = (
            ("4da83a879a861c8e80edd2d5f76ea4268de3d5ad", "203"),
            ("12ead3c03a7355fcc364648bf0a6169ee86153a1", "206"),
            ("e5e6ca6a5342da30b553697f96484c35a64b22c6", "207"),
        )
        for approved_sha, pr_number in fixtures:
            comment = self.owner_comment(
                id=5_085_200_000 + int(pr_number),
                body=(
                    "## Web CTO final visual review\n\n"
                    "UI_APPROVED\n\n"
                    f"Approved exact head: `{approved_sha}`"
                ),
            )
            with self.subTest(pr=pr_number):
                authority = validator.find_authorizing_comment(
                    [comment], approved_sha, OWNER_LOGIN
                )
                self.assertIsNotNone(authority)

    def test_accepts_exact_status_and_sha_in_same_comment(self) -> None:
        body = f"Web CTO approval\n\nUI_APPROVED\n\nApproved exact SHA: `{SHA}`"
        self.assertTrue(validator.comment_authorizes(body, SHA))

    def test_rejects_ui_review_ready_without_approval(self) -> None:
        self.assertFalse(validator.comment_authorizes(f"UI_REVIEW_READY\n{SHA}", SHA))

    def test_rejects_status_embedded_in_other_text(self) -> None:
        self.assertFalse(validator.comment_authorizes(f"NOT_UI_APPROVED_YET\n{SHA}", SHA))

    def test_rejects_outside_user_collaborator_member_and_missing_association(self) -> None:
        fixtures = [
            self.owner_comment(
                user={"login": "outside-user", "type": "User"},
                author_association="NONE",
            ),
            self.owner_comment(
                user={"login": "collaborator-user", "type": "User"},
                author_association="COLLABORATOR",
            ),
            self.owner_comment(
                user={"login": "member-user", "type": "User"},
                author_association="MEMBER",
            ),
            self.owner_comment(author_association=None),
        ]
        for fixture in fixtures:
            with self.subTest(fixture=fixture):
                self.assertIsNone(
                    validator.find_authorizing_comment([fixture], SHA, OWNER_LOGIN)
                )

    def test_rejects_owner_name_mismatch_bot_and_other_sha(self) -> None:
        fixtures = [
            self.owner_comment(
                user={"login": "other-owner", "type": "User"},
                author_association="OWNER",
            ),
            self.owner_comment(
                user={"login": "worker[bot]", "type": "Bot"},
                author_association="OWNER",
            ),
            self.owner_comment(body=f"UI_APPROVED\n{OTHER_SHA}"),
        ]
        for fixture in fixtures:
            with self.subTest(fixture=fixture):
                self.assertIsNone(
                    validator.find_authorizing_comment([fixture], SHA, OWNER_LOGIN)
                )

    def test_rejects_non_top_level_comment(self) -> None:
        fixtures = [
            self.owner_comment(pull_request_review_id=99),
            self.owner_comment(in_reply_to_id=88),
        ]
        for fixture in fixtures:
            with self.subTest(fixture=fixture):
                self.assertIsNone(
                    validator.find_authorizing_comment([fixture], SHA, OWNER_LOGIN)
                )

    def test_rejects_different_pr_sha(self) -> None:
        with self.assertRaises(validator.ValidationError):
            validator.verify_pr_payload(
                self.pr_payload(head={"sha": OTHER_SHA}), REPOSITORY, SHA
            )

    def test_accepts_open_draft_unmerged_pr(self) -> None:
        validator.verify_pr_payload(self.pr_payload(), REPOSITORY, SHA)

    def test_accepts_closed_merged_pr_with_valid_merge_sha(self) -> None:
        validator.verify_pr_payload(
            self.pr_payload(
                state="closed", draft=False, merged=True, merge_commit_sha=MERGE_SHA_37
            ),
            REPOSITORY,
            SHA,
        )

    def test_accepts_business_37_post_merge(self) -> None:
        validator.verify_pr_payload(
            self.pr_payload(
                head={"sha": SHA_37},
                state="closed",
                draft=False,
                merged=True,
                merge_commit_sha=MERGE_SHA_37,
            ),
            REPOSITORY,
            SHA_37,
        )

    def test_rejects_closed_unmerged_pr(self) -> None:
        with self.assertRaises(validator.ValidationError):
            validator.verify_pr_payload(
                self.pr_payload(state="closed", draft=False, merged=False), REPOSITORY, SHA
            )

    def test_rejects_closed_draft_merged_pr(self) -> None:
        with self.assertRaises(validator.ValidationError):
            validator.verify_pr_payload(
                self.pr_payload(state="closed", draft=True, merged=True), REPOSITORY, SHA
            )

    def test_rejects_open_ready_pr(self) -> None:
        with self.assertRaises(validator.ValidationError):
            validator.verify_pr_payload(
                self.pr_payload(draft=False), REPOSITORY, SHA
            )

    def test_rejects_open_pr_with_merged_true(self) -> None:
        with self.assertRaises(validator.ValidationError):
            validator.verify_pr_payload(
                self.pr_payload(merged=True), REPOSITORY, SHA
            )

    def test_rejects_merged_pr_missing_merge_commit_sha(self) -> None:
        with self.assertRaises(validator.ValidationError):
            validator.verify_pr_payload(
                self.pr_payload(state="closed", draft=False, merged=True),
                REPOSITORY,
                SHA,
            )

    def test_rejects_merged_pr_with_null_merge_commit_sha(self) -> None:
        with self.assertRaises(validator.ValidationError):
            validator.verify_pr_payload(
                self.pr_payload(
                    state="closed", draft=False, merged=True, merge_commit_sha=None
                ),
                REPOSITORY,
                SHA,
            )

    def test_rejects_merged_pr_with_short_merge_commit_sha(self) -> None:
        with self.assertRaises(validator.ValidationError):
            validator.verify_pr_payload(
                self.pr_payload(
                    state="closed", draft=False, merged=True, merge_commit_sha="0142c41"
                ),
                REPOSITORY,
                SHA,
            )

    def test_rejects_merged_pr_with_uppercase_merge_commit_sha(self) -> None:
        with self.assertRaises(validator.ValidationError):
            validator.verify_pr_payload(
                self.pr_payload(
                    state="closed", draft=False, merged=True,
                    merge_commit_sha=MERGE_SHA_37.upper(),
                ),
                REPOSITORY,
                SHA,
            )

    def test_rejects_different_pr_sha_remains_rejected(self) -> None:
        with self.assertRaises(validator.ValidationError):
            validator.verify_pr_payload(
                self.pr_payload(head={"sha": OTHER_SHA}), REPOSITORY, SHA
            )

    def test_rejects_wrong_repository_remains_rejected(self) -> None:
        with self.assertRaises(validator.ValidationError):
            validator.verify_pr_payload(
                self.pr_payload(base={"repo": {"full_name": "other/repo"}}),
                REPOSITORY,
                SHA,
            )


class CloudflareProjectContractTests(unittest.TestCase):
    def response(self):
        return {
            "success": True,
            "result": {
                "name": PROJECT_NAME,
                "production_branch": "main",
                "build_config": {
                    "build_command": "",
                    "destination_dir": ".",
                    "root_dir": SOURCE_DIRECTORY,
                },
                "source": {
                    "type": "github",
                    "config": {
                        "owner": OWNER_LOGIN,
                        "owner_id": "36503867",
                        "repo_name": "ai-revenue-lab",
                        "repo_id": "1306003434",
                        "production_branch": "main",
                        "production_deployments_enabled": True,
                        "preview_deployment_setting": "none",
                        "pr_comments_enabled": False,
                        "path_includes": [f"{SOURCE_DIRECTORY}/**"],
                    },
                },
            },
        }

    def verify(self, payload):
        return validator.verify_cloudflare_project_response(
            payload,
            PROJECT_NAME,
            SOURCE_DIRECTORY,
            "main",
            REPOSITORY_METADATA,
        )

    def test_github_source_create_payload(self) -> None:
        payload = validator.build_cloudflare_project_payload(
            PROJECT_NAME, SOURCE_DIRECTORY, "main", REPOSITORY_METADATA
        )
        self.assertEqual(payload, self.response()["result"])

    def test_new_project_response_source_verification(self) -> None:
        project = self.verify(self.response())
        self.assertEqual(project["source"]["type"], "github")

    def test_existing_project_full_contract_verification(self) -> None:
        project = self.verify(self.response())
        self.assertEqual(project["build_config"]["root_dir"], SOURCE_DIRECTORY)

    def test_rejects_existing_direct_upload_project(self) -> None:
        payload = self.response()
        payload["result"]["source"] = None
        with self.assertRaises(validator.ValidationError):
            self.verify(payload)

        payload = self.response()
        payload["result"]["source"]["type"] = "gitlab"
        with self.assertRaises(validator.ValidationError):
            self.verify(payload)

    def test_rejects_wrong_repository(self) -> None:
        for field, value in (
            ("owner", "other-owner"),
            ("owner_id", "1"),
            ("repo_name", "other-repo"),
            ("repo_id", "2"),
        ):
            payload = self.response()
            payload["result"]["source"]["config"][field] = value
            with self.subTest(field=field), self.assertRaises(validator.ValidationError):
                self.verify(payload)

    def test_rejects_wrong_root_destination_or_build_command(self) -> None:
        for field, value in (
            ("root_dir", "reference/other"),
            ("destination_dir", "dist"),
            ("build_command", "npm run build"),
        ):
            payload = self.response()
            payload["result"]["build_config"][field] = value
            with self.subTest(field=field), self.assertRaises(validator.ValidationError):
                self.verify(payload)

    def test_rejects_production_deployment_disabled(self) -> None:
        payload = self.response()
        payload["result"]["source"]["config"]["production_deployments_enabled"] = False
        with self.assertRaises(validator.ValidationError):
            self.verify(payload)

    def test_rejects_preview_policy_pr_comments_and_path_mismatch(self) -> None:
        mutations = (
            ("preview_deployment_setting", "all"),
            ("pr_comments_enabled", True),
            ("path_includes", ["reference/**"]),
        )
        for field, value in mutations:
            payload = self.response()
            payload["result"]["source"]["config"][field] = value
            with self.subTest(field=field), self.assertRaises(validator.ValidationError):
                self.verify(payload)


class SourceIsolationTests(unittest.TestCase):
    def test_accepts_regular_source_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / SOURCE_DIRECTORY
            source.mkdir(parents=True)
            (source / "index.html").write_text("ok", encoding="utf-8")
            validator.check_source_isolation(root, SOURCE_DIRECTORY)

    def test_rejects_escaping_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / SOURCE_DIRECTORY
            source.mkdir(parents=True)
            (source / "index.html").write_text("ok", encoding="utf-8")
            outside = root / "outside.txt"
            outside.write_text("secret", encoding="utf-8")
            (source / "escape.txt").symlink_to(outside)
            with self.assertRaises(validator.ValidationError):
                validator.check_source_isolation(root, SOURCE_DIRECTORY)


class WorkflowStaticContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = (
            Path(__file__).resolve().parents[1]
            / "workflows"
            / "provision-approved-business-pages.yml"
        ).read_text(encoding="utf-8")

    def test_manual_only_and_read_only_permissions(self) -> None:
        self.assertIn("workflow_dispatch:", self.workflow)
        self.assertNotIn("\n  push:", self.workflow)
        self.assertNotIn("\n  pull_request:", self.workflow)
        self.assertIn("contents: read", self.workflow)
        self.assertIn("pull-requests: read", self.workflow)
        self.assertIn("issues: read", self.workflow)

    def test_uses_verified_metadata_and_full_cloudflare_contract(self) -> None:
        required = (
            "--repository-metadata-output",
            "cloudflare-payload",
            "cloudflare-project",
            "Ensure the exact GitHub-integrated Pages project exists",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, self.workflow)

    def test_never_mutates_mismatched_project(self) -> None:
        forbidden = ("--request PATCH", "--request DELETE", "pages project delete")
        for marker in forbidden:
            with self.subTest(marker=marker):
                self.assertNotIn(marker, self.workflow)


if __name__ == "__main__":
    unittest.main()
