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
DEPLOYMENT_URL = "https://abc12345.ai-revenue-business-18-personal-audio-channel.pages.dev"
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
    def test_accepts_valid_contract_and_optional_single_trailing_slash(self) -> None:
        validator.validate_inputs(**self.valid())
        validator.validate_inputs(**self.valid(source_directory=SOURCE_DIRECTORY + "/"))
    def test_rejects_malformed_and_one_digit_business_id(self) -> None:
        for value in ("7", "007", "aa", "18;", "18$(id)", "00"):
            with self.subTest(value=value):
                self.assert_invalid(business_id=value)
    def test_rejects_business_project_and_source_mismatch(self) -> None:
        self.assert_invalid(project_name="ai-revenue-business-20-personal-memory-novel")
        self.assert_invalid(source_directory="reference/business-20-personal-memory-novel-v1")
    def test_rejects_invalid_project_forms(self) -> None:
        values = (
            "ai-revenue-world-feed",
            "AI-revenue-business-18-audio",
            "ai revenue-business-18-audio",
            "ai-revenue-business-18/a",
            "ai-revenue-business-18-..-a",
            "ai-revenue-business-18-a;echo-pwned",
            "ai-revenue-business-18-$(id)",
        )
        for value in values:
            with self.subTest(value=value):
                self.assert_invalid(project_name=value)
    def test_rejects_traversal_absolute_root_and_shell_source_paths(self) -> None:
        values = (
            "reference/business-18-../apps",
            "/reference/business-18-personal-audio-channel-v1",
            "\\reference\\business-18-audio",
            "reference/business-18-a;rm-rf",
            "reference/business-18-$(id)",
            "reference",
            ".",
            "apps/business-18-audio",
            ".github/business-18-audio",
            SOURCE_DIRECTORY + "\nextra",
        )
        for value in values:
            with self.subTest(value=value):
                self.assert_invalid(source_directory=value)
    def test_rejects_malformed_uppercase_and_short_sha(self) -> None:
        for value in (SHA[:12], SHA.upper(), "main", "refs/heads/main", SHA + "0"):
            with self.subTest(value=value):
                self.assert_invalid(approved_sha=value)
    def test_rejects_invalid_pr_number(self) -> None:
        for value in ("0", "-1", "1.5", "abc", "$(id)", "owner/repo#203", "https://github.com/x/y/pull/1"):
            with self.subTest(value=value):
                self.assert_invalid(approval_pr=value)
    def test_rejects_non_main_production_branch(self) -> None:
        for value in ("master", "feat/business-18", "Main", "main;id"):
            with self.subTest(value=value):
                self.assert_invalid(production_branch=value)
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
    def test_verifies_exact_repository_identity(self) -> None:
        self.assertEqual(validator.verify_repository_payload(self.payload(), REPOSITORY), REPOSITORY_METADATA)
    def test_rejects_wrong_repository_owner_name_or_ids(self) -> None:
        bad = (
            self.payload(full_name="other/repo"),
            self.payload(name="other-repository"),
            self.payload(owner={"login": "other-owner", "id": 36503867}),
            self.payload(id=0),
            self.payload(owner={"login": OWNER_LOGIN, "id": 0}),
        )
        for payload in bad:
            with self.subTest(payload=payload), self.assertRaises(validator.ValidationError):
                validator.verify_repository_payload(payload, REPOSITORY)
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
            "body": f"## Web CTO final visual review\n\nUI_APPROVED\n\nApproved exact head: `{SHA}`",
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
                body=f"## Web CTO final visual review\n\nUI_APPROVED\n\nApproved exact head: `{approved_sha}`",
            )
            with self.subTest(pr=pr_number):
                self.assertIsNotNone(validator.find_authorizing_comment([comment], approved_sha, OWNER_LOGIN))
    def test_accepts_exact_status_and_sha_in_same_comment(self) -> None:
        self.assertTrue(validator.comment_authorizes(f"Web CTO approval\n\nUI_APPROVED\n\nApproved exact SHA: `{SHA}`", SHA))
    def test_rejects_missing_review_ready_partial_and_question_statuses(self) -> None:
        values = (
            f"UI_REVIEW_READY\n{SHA}",
            f"NOT_UI_APPROVED\n{SHA}",
            f"UI_APPROVED_PENDING\n{SHA}",
            f"UI_APPROVED?\n{SHA}",
            f"prefix UI_APPROVED suffix\n{SHA}",
            "UI_APPROVED",
        )
        for value in values:
            with self.subTest(value=value):
                self.assertFalse(validator.comment_authorizes(value, SHA))
    def test_rejects_code_example_only_approval_or_sha(self) -> None:
        bodies = (
            f"Example:\n```text\nUI_APPROVED\n{SHA}\n```",
            f"UI_APPROVED\n\n```text\n{SHA}\n```",
            f"    UI_APPROVED\n    {SHA}",
            f"> UI_APPROVED\n> {SHA}",
            f"> ```text\n> UI_APPROVED\n> {SHA}\n> ```",
        )
        for body in bodies:
            with self.subTest(body=body):
                self.assertFalse(validator.comment_authorizes(body, SHA))
    def test_rejects_wrong_sha_owner_bot_worker_and_association(self) -> None:
        fixtures = (
            self.owner_comment(body=f"UI_APPROVED\n{OTHER_SHA}"),
            self.owner_comment(user={"login": "outside-user", "type": "User"}, author_association="NONE"),
            self.owner_comment(user={"login": "collaborator", "type": "User"}, author_association="COLLABORATOR"),
            self.owner_comment(user={"login": "member", "type": "User"}, author_association="MEMBER"),
            self.owner_comment(user={"login": "worker", "type": "User"}, author_association="WRITE"),
            self.owner_comment(user={"login": "other-owner", "type": "User"}, author_association="OWNER"),
            self.owner_comment(user={"login": "worker[bot]", "type": "Bot"}, author_association="OWNER"),
            self.owner_comment(author_association=None),
        )
        for fixture in fixtures:
            with self.subTest(fixture=fixture):
                self.assertIsNone(validator.find_authorizing_comment([fixture], SHA, OWNER_LOGIN))
    def test_rejects_inline_review_reply_and_review_submission_only(self) -> None:
        fixtures = (
            self.owner_comment(pull_request_review_id=99),
            self.owner_comment(in_reply_to_id=88),
            {"body": f"UI_APPROVED\n{SHA}", "user": {"login": OWNER_LOGIN, "type": "User"}, "author_association": "OWNER", "pull_request_review_id": 77},
        )
        for fixture in fixtures:
            self.assertIsNone(validator.find_authorizing_comment([fixture], SHA, OWNER_LOGIN))
    def test_rejects_wrong_repository_sha_ready_closed_or_merged_pr(self) -> None:
        payloads = (
            self.pr_payload(base={"repo": {"full_name": "other/repo"}}),
            self.pr_payload(head={"sha": OTHER_SHA}),
            self.pr_payload(draft=False),
            self.pr_payload(state="closed"),
            self.pr_payload(merged=True, state="closed"),
        )
        for payload in payloads:
            with self.subTest(payload=payload), self.assertRaises(validator.ValidationError):
                validator.verify_pr_payload(payload, REPOSITORY, SHA)
class CloudflareProjectContractTests(unittest.TestCase):
    def response(self):
        return {
            "success": True,
            "result": {
                "name": PROJECT_NAME,
                "production_branch": "main",
                "build_config": {"build_command": "", "destination_dir": ".", "root_dir": SOURCE_DIRECTORY},
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
        return validator.verify_cloudflare_project_response(payload, PROJECT_NAME, SOURCE_DIRECTORY, "main", REPOSITORY_METADATA)
    def test_create_payload_contains_exact_github_source_and_build_contract(self) -> None:
        self.assertEqual(validator.build_cloudflare_project_payload(PROJECT_NAME, SOURCE_DIRECTORY, "main", REPOSITORY_METADATA), self.response()["result"])
    def test_accepts_new_or_existing_exact_project_contract(self) -> None:
        project = self.verify(self.response())
        self.assertEqual(project["name"], PROJECT_NAME)
    def test_rejects_api_failure_invalid_result_wrong_project_or_branch(self) -> None:
        payloads = []
        for mutation in ("success", "result", "name", "production_branch"):
            payload = self.response()
            if mutation == "success":
                payload["success"] = False
            elif mutation == "result":
                payload["result"] = []
            elif mutation == "name":
                payload["result"]["name"] = "ai-revenue-business-20-wrong"
            else:
                payload["result"]["production_branch"] = "develop"
            payloads.append(payload)
        for payload in payloads:
            with self.subTest(payload=payload), self.assertRaises(validator.ValidationError):
                self.verify(payload)
    def test_rejects_direct_upload_wrong_repository_and_source_policy(self) -> None:
        mutations = (
            ("source", None),
            ("source_type", "gitlab"),
            ("owner", "other-owner"),
            ("owner_id", "1"),
            ("repo_name", "other-repo"),
            ("repo_id", "2"),
            ("production_deployments_enabled", False),
            ("preview_deployment_setting", "all"),
            ("pr_comments_enabled", True),
            ("path_includes", ["reference/**"]),
        )
        for field, value in mutations:
            payload = self.response()
            if field == "source":
                payload["result"]["source"] = value
            elif field == "source_type":
                payload["result"]["source"]["type"] = value
            else:
                payload["result"]["source"]["config"][field] = value
            with self.subTest(field=field), self.assertRaises(validator.ValidationError):
                self.verify(payload)
    def test_rejects_wrong_root_destination_or_build_command(self) -> None:
        for field, value in (("root_dir", "reference/other"), ("destination_dir", "dist"), ("build_command", "npm run build")):
            payload = self.response()
            payload["result"]["build_config"][field] = value
            with self.subTest(field=field), self.assertRaises(validator.ValidationError):
                self.verify(payload)
class CloudflareLookupTests(unittest.TestCase):
    def test_accepts_verified_200_and_404_only(self) -> None:
        self.assertEqual(validator.classify_cloudflare_project_lookup("200", {"success": True, "result": {"name": PROJECT_NAME}, "errors": []}), "exists")
        self.assertEqual(validator.classify_cloudflare_project_lookup("404", {"success": False, "result": None, "errors": [{"code": 8000007, "message": "not found"}]}), "missing")
    def test_rejects_401_403_409_429_500_and_other_failures(self) -> None:
        for status in ("401", "403", "409", "429", "500", "502", "503", "504"):
            with self.subTest(status=status), self.assertRaises(validator.ValidationError):
                validator.classify_cloudflare_project_lookup(status, {"success": False, "result": None, "errors": [{"code": 1}]})
    def test_rejects_invalid_json_shapes_and_fake_not_found(self) -> None:
        bad = (
            ("200", "not-json-object"),
            ("200", {"success": False, "result": {}}),
            ("404", {"success": True, "result": None, "errors": []}),
            ("404", {"success": False, "result": {"name": PROJECT_NAME}, "errors": [{"code": 1}]}),
            ("404", {"success": False, "result": None, "errors": []}),
        )
        for status, payload in bad:
            with self.subTest(status=status, payload=payload), self.assertRaises(validator.ValidationError):
                validator.classify_cloudflare_project_lookup(status, payload)
class CloudflareDeploymentTests(unittest.TestCase):
    def deployment(self, **overrides):
        value = {
            "id": "12345678-1234-1234-1234-123456789abc",
            "project_name": PROJECT_NAME,
            "url": DEPLOYMENT_URL,
            "environment": "production",
            "latest_stage": {"name": "deploy", "status": "success"},
            "deployment_trigger": {"metadata": {"commit_hash": SHA, "branch": "main"}},
        }
        value.update(overrides)
        return value
    def verify(self, payload):
        return validator.verify_cloudflare_deployment(payload, PROJECT_NAME, SHA, "main", DEPLOYMENT_URL)
    def test_accepts_exact_successful_deployment(self) -> None:
        self.assertEqual(self.verify(self.deployment())["deployment_status"], "success")
    def test_rejects_wrong_project_url_environment_status_sha_and_branch(self) -> None:
        payloads = (
            self.deployment(project_name="wrong-project"),
            self.deployment(url="https://wrong.pages.dev"),
            self.deployment(environment="preview"),
            self.deployment(latest_stage={"name": "deploy", "status": "failure"}),
            self.deployment(deployment_trigger={"metadata": {"commit_hash": OTHER_SHA, "branch": "main"}}),
            self.deployment(deployment_trigger={"metadata": {"commit_hash": SHA, "branch": "develop"}}),
            self.deployment(id=""),
        )
        for payload in payloads:
            with self.subTest(payload=payload), self.assertRaises(validator.ValidationError):
                self.verify(payload)
class PublicByteTests(unittest.TestCase):
    def test_accepts_exact_bytes_and_rejects_wrong_business_html(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = root / "expected.html"
            actual = root / "actual.html"
            expected.write_bytes(b"<html data-business-id='18'>approved</html>")
            actual.write_bytes(expected.read_bytes())
            validator.verify_public_bytes(expected, actual)
            actual.write_bytes(b"<html data-business-id='20'>wrong</html>")
            with self.assertRaises(validator.ValidationError):
                validator.verify_public_bytes(expected, actual)
    def test_rejects_empty_approved_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = root / "expected.html"
            actual = root / "actual.html"
            expected.write_bytes(b"")
            actual.write_bytes(b"")
            with self.assertRaises(validator.ValidationError):
                validator.verify_public_bytes(expected, actual)
class SourceIsolationTests(unittest.TestCase):
    def source_tree(self, root: Path) -> Path:
        source = root / SOURCE_DIRECTORY
        source.mkdir(parents=True)
        (source / "index.html").write_text("ok", encoding="utf-8")
        return source
    def test_accepts_regular_source_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.source_tree(root)
            validator.check_source_isolation(root, SOURCE_DIRECTORY)
    def test_rejects_missing_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / SOURCE_DIRECTORY).mkdir(parents=True)
            with self.assertRaises(validator.ValidationError):
                validator.check_source_isolation(root, SOURCE_DIRECTORY)
    def test_rejects_source_directory_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "actual"
            target.mkdir()
            (target / "index.html").write_text("ok")
            link_parent = root / "reference"
            link_parent.mkdir()
            (link_parent / "business-18-personal-audio-channel-v1").symlink_to(target, target_is_directory=True)
            with self.assertRaises(validator.ValidationError):
                validator.check_source_isolation(root, SOURCE_DIRECTORY)
    def test_rejects_escaping_broken_and_external_index_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source_tree(root)
            outside = root / "outside.txt"
            outside.write_text("secret")
            (source / "escape.txt").symlink_to(outside)
            with self.assertRaises(validator.ValidationError):
                validator.check_source_isolation(root, SOURCE_DIRECTORY)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source_tree(root)
            (source / "broken.txt").symlink_to(root / "missing")
            with self.assertRaises(validator.ValidationError):
                validator.check_source_isolation(root, SOURCE_DIRECTORY)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source_tree(root)
            outside = root / "outside.html"
            outside.write_text("outside")
            (source / "index.html").unlink()
            (source / "index.html").symlink_to(outside)
            with self.assertRaises(validator.ValidationError):
                validator.check_source_isolation(root, SOURCE_DIRECTORY)
class WorkflowStaticContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = (Path(__file__).resolve().parents[1] / "workflows" / "provision-approved-business-pages.yml").read_text(encoding="utf-8")
    def test_manual_only_trigger_and_required_inputs(self) -> None:
        self.assertIn("workflow_dispatch:", self.workflow)
        for forbidden in ("\n  push:", "\n  pull_request:", "\n  schedule:", "\n  workflow_run:", "\n  repository_dispatch:"):
            self.assertNotIn(forbidden, self.workflow)
        for name in ("business_id:", "project_name:", "source_directory:", "approved_sha:", "approval_pr:", "production_branch:"):
            self.assertIn(name, self.workflow)
        self.assertIn("default: main", self.workflow)
    def test_read_only_permissions_and_no_write_permissions(self) -> None:
        for marker in ("contents: read", "pull-requests: read", "issues: read"):
            self.assertIn(marker, self.workflow)
        for marker in ("contents: write", "pull-requests: write", "issues: write", "actions: write", "deployments: write", "id-token: write", "packages: write", "security-events: write"):
            self.assertNotIn(marker, self.workflow)
    def test_concurrency_timeout_checkout_and_wrangler_contract(self) -> None:
        for marker in (
            "group: provision-approved-business-pages-${{ inputs.project_name }}",
            "cancel-in-progress: false",
            "timeout-minutes: 20",
            "persist-credentials: false",
            "ref: ${{ inputs.approved_sha }}",
            "npx --yes wrangler@4 pages deploy",
            '--branch "${PRODUCTION_BRANCH}"',
            '--commit-hash "${APPROVED_SHA}"',
            "--commit-dirty=false",
        ):
            self.assertIn(marker, self.workflow)
    def test_full_validation_and_fail_closed_cloudflare_contract(self) -> None:
        for marker in ("cloudflare-lookup", "cloudflare-payload", "cloudflare-project", "cloudflare-deployment", "public-bytes", "--max-time 60", "--connect-timeout 15"):
            self.assertIn(marker, self.workflow)
        for forbidden in ("--request PATCH", "--request DELETE", "pages project delete", "eval ", "set -x"):
            self.assertNotIn(forbidden, self.workflow)
    def test_summary_runs_always_and_sanitizes_values(self) -> None:
        self.assertIn("if: ${{ always() }}", self.workflow)
        self.assertIn("safe_value()", self.workflow)
        self.assertIn("Job status", self.workflow)
if __name__ == "__main__":
    unittest.main()
