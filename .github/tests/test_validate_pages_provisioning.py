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


class InputValidationTests(unittest.TestCase):
    def valid(self, **overrides: str) -> dict[str, str]:
        values = {
            "business_id": "18",
            "project_name": "ai-revenue-business-18-personal-audio-channel",
            "source_directory": "reference/business-18-personal-audio-channel-v1",
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

    def test_rejects_path_traversal_and_absolute_path(self) -> None:
        self.assert_invalid(source_directory="reference/business-18-../apps")
        self.assert_invalid(source_directory="/reference/business-18-personal-audio-channel-v1")
        self.assert_invalid(source_directory="reference/business-18-a;rm-rf")

    def test_rejects_bad_sha(self) -> None:
        self.assert_invalid(approved_sha=SHA[:12])
        self.assert_invalid(approved_sha=SHA.upper())

    def test_rejects_bad_pr_and_branch(self) -> None:
        self.assert_invalid(approval_pr="0")
        self.assert_invalid(production_branch="feat/business-18")


class ApprovalAuthorityTests(unittest.TestCase):
    def pr_payload(self, **overrides):
        payload = {
            "base": {"repo": {"full_name": "skerishKang/ai-revenue-lab"}},
            "head": {"sha": SHA},
            "state": "open",
            "draft": True,
            "merged": False,
        }
        payload.update(overrides)
        return payload

    def test_accepts_exact_status_and_sha_in_same_comment(self) -> None:
        body = f"Web CTO approval\n\nUI_APPROVED\n\nApproved exact SHA: `{SHA}`"
        self.assertTrue(validator.comment_authorizes(body, SHA))

    def test_rejects_ui_review_ready_without_approval(self) -> None:
        self.assertFalse(validator.comment_authorizes(f"UI_REVIEW_READY\n{SHA}", SHA))

    def test_rejects_approval_for_different_sha(self) -> None:
        self.assertFalse(validator.comment_authorizes(f"UI_APPROVED\n{OTHER_SHA}", SHA))

    def test_rejects_status_embedded_in_other_text(self) -> None:
        self.assertFalse(validator.comment_authorizes(f"NOT_UI_APPROVED_YET\n{SHA}", SHA))

    def test_rejects_bot_authority(self) -> None:
        comments = [
            {
                "body": f"UI_APPROVED\n{SHA}",
                "user": {"login": "worker[bot]", "type": "Bot"},
            }
        ]
        self.assertIsNone(validator.find_authorizing_comment(comments, SHA))

    def test_rejects_different_pr_sha(self) -> None:
        with self.assertRaises(validator.ValidationError):
            validator.verify_pr_payload(
                self.pr_payload(head={"sha": OTHER_SHA}),
                "skerishKang/ai-revenue-lab",
                SHA,
            )

    def test_rejects_ready_or_merged_pr(self) -> None:
        with self.assertRaises(validator.ValidationError):
            validator.verify_pr_payload(
                self.pr_payload(draft=False), "skerishKang/ai-revenue-lab", SHA
            )
        with self.assertRaises(validator.ValidationError):
            validator.verify_pr_payload(
                self.pr_payload(merged=True, state="closed"),
                "skerishKang/ai-revenue-lab",
                SHA,
            )

    def test_rejects_wrong_repository(self) -> None:
        with self.assertRaises(validator.ValidationError):
            validator.verify_pr_payload(
                self.pr_payload(base={"repo": {"full_name": "other/repo"}}),
                "skerishKang/ai-revenue-lab",
                SHA,
            )


class SourceIsolationTests(unittest.TestCase):
    def test_accepts_regular_source_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "reference/business-18-personal-audio-channel-v1"
            source.mkdir(parents=True)
            (source / "index.html").write_text("ok", encoding="utf-8")
            validator.check_source_isolation(
                root, "reference/business-18-personal-audio-channel-v1"
            )

    def test_rejects_escaping_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "reference/business-18-personal-audio-channel-v1"
            source.mkdir(parents=True)
            (source / "index.html").write_text("ok", encoding="utf-8")
            outside = root / "outside.txt"
            outside.write_text("secret", encoding="utf-8")
            (source / "escape.txt").symlink_to(outside)
            with self.assertRaises(validator.ValidationError):
                validator.check_source_isolation(
                    root, "reference/business-18-personal-audio-channel-v1"
                )


if __name__ == "__main__":
    unittest.main()
