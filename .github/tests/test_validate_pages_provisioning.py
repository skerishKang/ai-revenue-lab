from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_pages_provisioning.py"
SPEC = importlib.util.spec_from_file_location("validator", SCRIPT)
assert SPEC and SPEC.loader
v = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v)

SHA = "4da83a879a861c8e80edd2d5f76ea4268de3d5ad"
OTHER_SHA = "12ead3c03a7355fcc364648bf0a6169ee86153a1"
PROJECT = "ai-revenue-business-18-personal-audio-channel"
SOURCE = "reference/business-18-personal-audio-channel-v1"
REPO = {
    "repository_full_name": "skerishKang/ai-revenue-lab",
    "repository_id": "1306003434",
    "repository_name": "ai-revenue-lab",
    "repository_owner_login": "skerishKang",
    "repository_owner_id": "36503867",
}


class InputTests(unittest.TestCase):
    def valid(self, **changes):
        data = dict(
            business_id="18",
            project_name=PROJECT,
            source_directory=SOURCE,
            approved_sha=SHA,
            approval_pr="203",
            production_branch="main",
        )
        data.update(changes)
        return data

    def reject(self, **changes):
        with self.assertRaises(v.ValidationError):
            v.validate_inputs(**self.valid(**changes))

    def test_valid_input(self):
        v.validate_inputs(**self.valid())

    def test_rejects_project_business_and_shell_mismatch(self):
        self.reject(project_name="ai-revenue-world-feed")
        self.reject(project_name="ai-revenue-business-20-memory")
        self.reject(project_name="ai-revenue-business-18-a;echo")

    def test_rejects_path_traversal_absolute_other_business_and_shell(self):
        for source in (
            "../apps",
            "/reference/business-18-x",
            "reference/business-20-x",
            "reference/business-18-a;rm-rf",
        ):
            with self.subTest(source=source):
                self.reject(source_directory=source)

    def test_rejects_bad_sha_pr_and_branch(self):
        self.reject(approved_sha=SHA[:12])
        self.reject(approved_sha=SHA.upper())
        self.reject(approval_pr="0")
        self.reject(production_branch="feature")


class AuthorityTests(unittest.TestCase):
    def repository_payload(self, **changes):
        payload = {
            "id": 1306003434,
            "name": "ai-revenue-lab",
            "full_name": "skerishKang/ai-revenue-lab",
            "owner": {"login": "skerishKang", "id": 36503867},
        }
        payload.update(changes)
        return payload

    def comment(self, **changes):
        result = {
            "id": 5085221938,
            "body": f"UI_APPROVED\n{SHA}",
            "author_association": "OWNER",
            "pull_request_review_id": None,
            "in_reply_to_id": None,
            "user": {"login": "skerishKang", "id": 36503867, "type": "User"},
        }
        result.update(changes)
        return result

    def test_repository_metadata_passes(self):
        self.assertEqual(
            v.repository_metadata(self.repository_payload(), REPO["repository_full_name"]),
            REPO,
        )

    def test_repository_metadata_mismatch_fails(self):
        for payload in (
            self.repository_payload(full_name="other/repo"),
            self.repository_payload(name="other"),
            self.repository_payload(owner={"login": "other", "id": 36503867}),
            self.repository_payload(id=0),
            self.repository_payload(owner={"login": "skerishKang", "id": 0}),
        ):
            with self.subTest(payload=payload), self.assertRaises(v.ValidationError):
                v.repository_metadata(payload, REPO["repository_full_name"])

    def test_owner_authored_approval_passes(self):
        self.assertTrue(v.owner_comment_authorizes(self.comment(), SHA, REPO))
        self.assertIsNotNone(v.find_owner_approval([self.comment()], SHA, REPO))

    def test_external_collaborator_member_and_missing_association_fail(self):
        fixtures = (
            self.comment(
                user={"login": "external", "id": 1, "type": "User"},
                author_association="NONE",
            ),
            self.comment(
                user={"login": "external", "id": 1, "type": "User"},
                author_association="COLLABORATOR",
            ),
            self.comment(
                user={"login": "external", "id": 1, "type": "User"},
                author_association="MEMBER",
            ),
            self.comment(author_association=None),
        )
        for comment in fixtures:
            with self.subTest(comment=comment):
                self.assertFalse(v.owner_comment_authorizes(comment, SHA, REPO))

    def test_owner_login_mismatch_fails(self):
        self.assertFalse(
            v.owner_comment_authorizes(
                self.comment(
                    user={"login": "other", "id": 36503867, "type": "User"}
                ),
                SHA,
                REPO,
            )
        )

    def test_owner_id_mismatch_and_missing_id_fail(self):
        for user in (
            {"login": "skerishKang", "id": 1, "type": "User"},
            {"login": "skerishKang", "type": "User"},
        ):
            with self.subTest(user=user):
                self.assertFalse(
                    v.owner_comment_authorizes(self.comment(user=user), SHA, REPO)
                )

    def test_bot_other_sha_and_non_top_level_fail(self):
        fixtures = (
            self.comment(
                user={"login": "skerishKang", "id": 36503867, "type": "Bot"}
            ),
            self.comment(body=f"UI_APPROVED\n{OTHER_SHA}"),
            self.comment(body=f"UI_REVIEW_READY\n{SHA}"),
            self.comment(pull_request_review_id=1),
            self.comment(in_reply_to_id=1),
        )
        for comment in fixtures:
            with self.subTest(comment=comment):
                self.assertFalse(v.owner_comment_authorizes(comment, SHA, REPO))

    def test_pr_exact_repository_sha_and_state_pass(self):
        payload = {
            "base": {
                "repo": {
                    "full_name": REPO["repository_full_name"],
                    "id": 1306003434,
                }
            },
            "head": {
                "repo": {
                    "full_name": REPO["repository_full_name"],
                    "id": 1306003434,
                },
                "sha": SHA,
            },
            "state": "open",
            "draft": True,
            "merged": False,
        }
        v.verify_pr(payload, REPO, SHA)

    def test_pr_repository_sha_ready_and_merged_fail(self):
        base = {
            "base": {
                "repo": {
                    "full_name": REPO["repository_full_name"],
                    "id": 1306003434,
                }
            },
            "head": {
                "repo": {
                    "full_name": REPO["repository_full_name"],
                    "id": 1306003434,
                },
                "sha": SHA,
            },
            "state": "open",
            "draft": True,
            "merged": False,
        }
        mutations = (
            {
                "head": {
                    "repo": {
                        "full_name": REPO["repository_full_name"],
                        "id": 1306003434,
                    },
                    "sha": OTHER_SHA,
                }
            },
            {"draft": False},
            {"state": "closed", "merged": True},
            {"base": {"repo": {"full_name": "other/repo", "id": 1306003434}}},
            {
                "head": {
                    "repo": {"full_name": REPO["repository_full_name"], "id": 1},
                    "sha": SHA,
                }
            },
        )
        for changes in mutations:
            payload = dict(base)
            payload.update(changes)
            with self.subTest(changes=changes), self.assertRaises(v.ValidationError):
                v.verify_pr(payload, REPO, SHA)


class CloudflareContractTests(unittest.TestCase):
    def expected(self):
        return v.project_payload(PROJECT, SOURCE, "main", REPO)

    def response(self):
        return {"success": True, "result": self.expected()}

    def test_github_source_create_payload_passes(self):
        payload = self.expected()
        self.assertEqual(payload["source"]["type"], "github")
        self.assertEqual(
            payload["source"]["config"]["owner_id"],
            REPO["repository_owner_id"],
        )
        self.assertEqual(
            payload["source"]["config"]["repo_id"], REPO["repository_id"]
        )
        self.assertEqual(
            payload["source"]["config"]["path_includes"], [f"{SOURCE}/**"]
        )
        self.assertEqual(
            payload["build_config"],
            {"build_command": "", "destination_dir": ".", "root_dir": SOURCE},
        )

    def test_new_project_response_contract_passes(self):
        v.verify_project(self.response(), PROJECT, SOURCE, "main", REPO)

    def assert_field_rejected(self, group, field, value):
        response = self.response()
        target = response["result"][group]
        if group == "source":
            target = target["config"]
        target[field] = value
        with self.assertRaises(v.ValidationError):
            v.verify_project(response, PROJECT, SOURCE, "main", REPO)

    def test_direct_upload_existing_project_fails(self):
        response = self.response()
        response["result"]["source"] = None
        with self.assertRaises(v.ValidationError):
            v.verify_project(response, PROJECT, SOURCE, "main", REPO)

    def test_wrong_repository_or_owner_existing_project_fails(self):
        for field, value in (
            ("owner", "other"),
            ("owner_id", "1"),
            ("repo_name", "other"),
            ("repo_id", "2"),
        ):
            with self.subTest(field=field):
                self.assert_field_rejected("source", field, value)

    def test_wrong_root_destination_or_build_command_fails(self):
        for field, value in (
            ("root_dir", "reference/other"),
            ("destination_dir", "dist"),
            ("build_command", "npm build"),
        ):
            with self.subTest(field=field):
                self.assert_field_rejected("build_config", field, value)

    def test_production_disabled_preview_enabled_or_pr_comments_fail(self):
        for field, value in (
            ("production_deployments_enabled", False),
            ("preview_deployment_setting", "all"),
            ("pr_comments_enabled", True),
        ):
            with self.subTest(field=field):
                self.assert_field_rejected("source", field, value)

    def test_wrong_paths_and_branch_fail(self):
        for field, value in (
            ("path_includes", ["reference/**"]),
            ("path_excludes", ["apps/**"]),
            ("production_branch", "feature"),
        ):
            with self.subTest(field=field):
                self.assert_field_rejected("source", field, value)


class SourceTests(unittest.TestCase):
    def test_escaping_symlink_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(
                ["git", "-C", str(root), "config", "user.email", "test@example.com"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(root), "config", "user.name", "Test"],
                check=True,
            )
            source = root / SOURCE
            source.mkdir(parents=True)
            (source / "index.html").write_text("ok", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(root), "commit", "-qm", "fixture"], check=True
            )
            sha = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            outside = root / "outside"
            outside.write_text("x", encoding="utf-8")
            (source / "escape").symlink_to(outside)
            with self.assertRaises(v.ValidationError):
                v.verify_source(root, SOURCE, sha)


class WorkflowStaticTests(unittest.TestCase):
    def setUp(self):
        self.workflow = (
            Path(__file__).resolve().parents[1]
            / "workflows"
            / "provision-approved-business-pages.yml"
        ).read_text(encoding="utf-8")

    def test_manual_only_permissions_and_concurrency(self):
        self.assertIn("workflow_dispatch:", self.workflow)
        self.assertNotIn("\n  push:", self.workflow)
        self.assertNotIn("\n  pull_request:", self.workflow)
        for marker in (
            "contents: read",
            "pull-requests: read",
            "issues: read",
            "cancel-in-progress: false",
        ):
            self.assertIn(marker, self.workflow)

    def test_git_integrated_project_validation_and_no_repair_path(self):
        for marker in (
            "cloudflare-payload",
            "cloudflare-project",
            "Ensure the exact GitHub-integrated Pages project exists",
        ):
            self.assertIn(marker, self.workflow)
        for marker in ("--request PATCH", "--request DELETE", "pages project delete"):
            self.assertNotIn(marker, self.workflow)

    def test_exact_head_deploy_contract(self):
        for marker in (
            "npx --yes wrangler@4 pages deploy",
            "--project-name",
            "--commit-hash",
            "--commit-dirty=false",
        ):
            self.assertIn(marker, self.workflow)


if __name__ == "__main__":
    unittest.main()
