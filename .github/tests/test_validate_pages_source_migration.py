from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "validate_pages_source_migration.py"
)
SPEC = importlib.util.spec_from_file_location("migration", SCRIPT)
assert SPEC and SPEC.loader
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)

OWNER = "skerishKang"
BUSINESS_ID = "14"
PROJECT = "ai-revenue-business-14-korean-ai-platform"
OLD_SOURCE = "reference/business-14-korean-ai-platform-v2"
NEW_SOURCE = "reference/business-14-korean-ai-platform-v3"
SHA = "a695046df2f5b736127b6a15034012290e2c010f"


def approval_body(**overrides: str) -> str:
    values = {
        "project_name": PROJECT,
        "old_source_directory": OLD_SOURCE,
        "new_source_directory": NEW_SOURCE,
        "approved_sha": SHA,
    }
    values.update(overrides)
    return "\n".join(
        (
            "SOURCE_MIGRATION_APPROVED",
            f"project_name: {values['project_name']}",
            f"old_source_directory: {values['old_source_directory']}",
            f"new_source_directory: {values['new_source_directory']}",
            f"approved_sha: {values['approved_sha']}",
        )
    )


def owner_comment(**overrides):
    comment = {
        "id": 5156000000,
        "body": approval_body(),
        "user": {"login": OWNER, "type": "User"},
        "author_association": "OWNER",
        "pull_request_review_id": None,
        "in_reply_to_id": None,
    }
    comment.update(overrides)
    return comment


class ContractTests(unittest.TestCase):
    def valid(self, **overrides: str) -> dict[str, str]:
        values = {
            "action": "verify-only",
            "business_id": BUSINESS_ID,
            "project_name": PROJECT,
            "source_directory": NEW_SOURCE,
            "expected_old_source_directory": "",
            "approved_sha": SHA,
            "approval_pr": "381",
            "production_branch": "main",
        }
        values.update(overrides)
        return values

    def test_verify_only_preserves_default_without_old_source(self) -> None:
        old_source, new_source = migration.validate_contract(**self.valid())
        self.assertIsNone(old_source)
        self.assertEqual(new_source, NEW_SOURCE)

    def test_verify_only_rejects_old_source_input(self) -> None:
        with self.assertRaises(migration.ValidationError):
            migration.validate_contract(
                **self.valid(expected_old_source_directory=OLD_SOURCE)
            )

    def test_migrate_source_requires_exact_old_source(self) -> None:
        old_source, new_source = migration.validate_contract(
            **self.valid(
                action="migrate-source",
                expected_old_source_directory=OLD_SOURCE,
            )
        )
        self.assertEqual(old_source, OLD_SOURCE)
        self.assertEqual(new_source, NEW_SOURCE)

    def test_migrate_source_rejects_missing_or_equal_old_source(self) -> None:
        for old_source in ("", NEW_SOURCE):
            with self.subTest(old_source=old_source), self.assertRaises(
                migration.ValidationError
            ):
                migration.validate_contract(
                    **self.valid(
                        action="migrate-source",
                        expected_old_source_directory=old_source,
                    )
                )

    def test_rejects_cross_business_source_and_project(self) -> None:
        with self.assertRaises(migration.ValidationError):
            migration.validate_contract(
                **self.valid(
                    action="migrate-source",
                    expected_old_source_directory=(
                        "reference/business-18-personal-audio-channel-v1"
                    ),
                )
            )
        with self.assertRaises(migration.ValidationError):
            migration.validate_contract(
                **self.valid(
                    project_name="ai-revenue-business-18-personal-audio-channel"
                )
            )

    def test_rejects_unknown_action_bad_sha_or_non_main(self) -> None:
        for changes in (
            {"action": "repair"},
            {"approved_sha": SHA[:12]},
            {"production_branch": "feat/source-migration"},
        ):
            with self.subTest(changes=changes), self.assertRaises(
                migration.ValidationError
            ):
                migration.validate_contract(**self.valid(**changes))


class AuthorityTests(unittest.TestCase):
    def test_exact_owner_top_level_comment_authorizes(self) -> None:
        authority = migration.find_authorizing_comment(
            [owner_comment()], OWNER, PROJECT, OLD_SOURCE, NEW_SOURCE, SHA
        )
        self.assertIsNotNone(authority)

    def test_rejects_wrong_values_or_duplicate_fields(self) -> None:
        bodies = (
            approval_body(project_name="ai-revenue-business-14-other"),
            approval_body(old_source_directory=NEW_SOURCE),
            approval_body(new_source_directory=OLD_SOURCE),
            approval_body(approved_sha="0" * 40),
            approval_body() + f"\nproject_name: {PROJECT}",
            approval_body().replace("SOURCE_MIGRATION_APPROVED", "UI_APPROVED"),
        )
        for body in bodies:
            with self.subTest(body=body):
                self.assertIsNone(
                    migration.find_authorizing_comment(
                        [owner_comment(body=body)],
                        OWNER,
                        PROJECT,
                        OLD_SOURCE,
                        NEW_SOURCE,
                        SHA,
                    )
                )

    def test_rejects_non_owner_bot_review_and_reply(self) -> None:
        fixtures = (
            owner_comment(user={"login": "other", "type": "User"}),
            owner_comment(author_association="COLLABORATOR"),
            owner_comment(user={"login": "worker[bot]", "type": "Bot"}),
            owner_comment(pull_request_review_id=9),
            owner_comment(in_reply_to_id=8),
        )
        for fixture in fixtures:
            with self.subTest(fixture=fixture):
                self.assertIsNone(
                    migration.find_authorizing_comment(
                        [fixture], OWNER, PROJECT, OLD_SOURCE, NEW_SOURCE, SHA
                    )
                )

    def test_comments_file_requires_owner_metadata_and_exact_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            comments_path = root / "comments.json"
            metadata_path = root / "metadata.json"
            comments_path.write_text(
                json.dumps([owner_comment()]), encoding="utf-8"
            )
            metadata_path.write_text(
                json.dumps({"owner_login": OWNER}), encoding="utf-8"
            )
            authority = migration.verify_comments_file(
                comments_path,
                metadata_path,
                PROJECT,
                OLD_SOURCE,
                NEW_SOURCE,
                SHA,
            )
            self.assertEqual(authority["id"], 5156000000)


class PatchPayloadTests(unittest.TestCase):
    def test_patch_payload_is_source_only_and_bounded(self) -> None:
        payload = migration.build_patch_payload(BUSINESS_ID, NEW_SOURCE)
        self.assertEqual(
            payload,
            {
                "build_config": {"root_dir": NEW_SOURCE},
                "source": {
                    "type": "github",
                    "config": {"path_includes": [f"{NEW_SOURCE}/**"]},
                },
            },
        )
        text = json.dumps(payload)
        for forbidden in (
            "name",
            "production_branch",
            "owner_id",
            "repo_id",
            "production_deployments_enabled",
            "preview_deployment_setting",
            "pr_comments_enabled",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(f'"{forbidden}"', text)

    def test_patch_payload_revalidates_same_business_source(self) -> None:
        for business_id, source in (
            ("14", "reference/business-18-personal-audio-channel-v1"),
            ("14", "../reference/business-14-korean-ai-platform-v3"),
            ("00", NEW_SOURCE),
        ):
            with self.subTest(business_id=business_id, source=source), self.assertRaises(
                migration.ValidationError
            ):
                migration.build_patch_payload(business_id, source)


if __name__ == "__main__":
    unittest.main()
