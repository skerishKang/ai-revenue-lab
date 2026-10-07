from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / ".github" / "scripts" / "b62_public_origin_migration.py"
WORKFLOW = (ROOT / ".github" / "workflows" / "b62-public-origin-migration-gate.yml").read_text(encoding="utf-8")
AUTH_WORKFLOW = (ROOT / ".github" / "workflows" / "b62-google-auth-production-activation-gate.yml").read_text(encoding="utf-8")
DEPLOY_WORKFLOW = (ROOT / ".github" / "workflows" / "b62-production-code-deploy-gate.yml").read_text(encoding="utf-8")

spec = importlib.util.spec_from_file_location("b62_public_origin_migration", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def settings(origin: str = migration.OLD_ORIGIN) -> dict:
    return {
        "success": True,
        "result": {
            "bindings": [
                {"name": "ASSETS", "type": "assets"},
                {"name": "B14_SERVICE", "type": "service", "service": "padiem-b14"},
                {"name": "IDENTITY_AUTHORITY_SERVICE", "type": "service", "service": "padiem-control-plane-identity"},
                {"name": "PADIEM_CHAT_DB", "type": "d1", "id": "d1-id"},
                {"name": "PADIEM_WORKSPACE_FILES", "type": "r2_bucket", "bucket_name": "workspace-files"},
                {"name": "PADIEM_CHAT_AUTH_MODE", "type": "plain_text", "text": "google"},
                {"name": "PADIEM_CHAT_PUBLIC_BASE_URL", "type": "plain_text", "text": origin},
                {"name": "PADIEM_CHAT_GOOGLE_CLIENT_ID", "type": "plain_text", "text": "client-id"},
                {"name": "PADIEM_CHAT_GOOGLE_CLIENT_SECRET", "type": "secret_text"},
                {"name": "PADIEM_CHAT_SESSION_SECRET", "type": "secret_text"},
                {"name": "PADIEM_CHAT_QUOTA_SALT", "type": "secret_text"},
            ]
        },
    }


def test_prestate_requires_exact_legacy_origin_and_active_auth() -> None:
    migration.require_prestate(settings())
    with pytest.raises(migration.OriginMigrationError, match="NOT_LEGACY_EXPECTED"):
        migration.require_prestate(settings(migration.NEW_ORIGIN))

    broken = settings()
    broken["result"]["bindings"] = [
        b for b in broken["result"]["bindings"] if b["name"] != "PADIEM_CHAT_SESSION_SECRET"
    ]
    with pytest.raises(migration.OriginMigrationError, match="SESSION_SECRET"):
        migration.require_prestate(broken)


def test_target_patch_changes_only_public_origin_and_never_embeds_secrets() -> None:
    before = settings()
    patch = migration.build_patch(
        before,
        target_origin=migration.NEW_ORIGIN,
        message="test migration",
    )
    by_name = {b["name"]: b for b in patch["bindings"]}
    public = by_name["PADIEM_CHAT_PUBLIC_BASE_URL"]
    assert public == {
        "name": "PADIEM_CHAT_PUBLIC_BASE_URL",
        "type": "plain_text",
        "text": "https://chat.padiem.net",
    }

    for name, binding in by_name.items():
        if name == "PADIEM_CHAT_PUBLIC_BASE_URL":
            continue
        assert binding == {"name": name, "type": "inherit", "version_id": "latest"}
        assert "text" not in binding


def test_verify_target_allows_only_the_public_origin_transition() -> None:
    before = settings()
    after = copy.deepcopy(before)
    for binding in after["result"]["bindings"]:
        if binding["name"] == "PADIEM_CHAT_PUBLIC_BASE_URL":
            binding["text"] = migration.NEW_ORIGIN
    migration.verify_transition(before, after, expected_after=migration.NEW_ORIGIN)

    drift = copy.deepcopy(after)
    for binding in drift["result"]["bindings"]:
        if binding["name"] == "PADIEM_CHAT_AUTH_MODE":
            binding["text"] = "off"
    with pytest.raises(migration.OriginMigrationError, match="UNRELATED_BINDING_DRIFT"):
        migration.verify_transition(before, drift, expected_after=migration.NEW_ORIGIN)


def test_verify_transition_preserves_exact_secret_name_set() -> None:
    before = settings()
    after = copy.deepcopy(before)
    for binding in after["result"]["bindings"]:
        if binding["name"] == "PADIEM_CHAT_PUBLIC_BASE_URL":
            binding["text"] = migration.NEW_ORIGIN
    after["result"]["bindings"].append({"name": "UNEXPECTED_SECRET", "type": "secret_text"})
    with pytest.raises(migration.OriginMigrationError):
        migration.verify_transition(before, after, expected_after=migration.NEW_ORIGIN)


def test_workflow_is_exact_main_bounded_and_rollback_armed() -> None:
    assert "CONFIRM_MIGRATE_B62_PUBLIC_ORIGIN_TO_CHAT_PADIEM_NET" in WORKFLOW
    assert "PREMUTATION_EXACT_MAIN_SHA=PASS" in WORKFLOW
    assert "PUBLIC_ORIGIN_PRESTATE=OLD_EXPECTED" not in WORKFLOW
    assert "b62_public_origin_migration.py prestate" in WORKFLOW
    assert "b62_public_origin_migration.py verify-target" in WORKFLOW
    assert "b62_public_origin_migration.py build-rollback" in WORKFLOW
    assert "B62_PUBLIC_ORIGIN_ROLLBACK_READBACK=EXACT" in WORKFLOW
    assert "UNRELATED_BINDING_MUTATION=0" in SCRIPT_PATH.read_text(encoding="utf-8")
    assert "SECRET_BINDINGS_PRESERVED=PASS" in SCRIPT_PATH.read_text(encoding="utf-8")
    assert "FULL_SECRET_SET_EQUALITY=PASS" in SCRIPT_PATH.read_text(encoding="utf-8")
    assert "environment: production" in WORKFLOW
    assert "wrangler deploy" not in WORKFLOW
    assert "LOGIN_ATTEMPT=0" in WORKFLOW
    assert "PHASE_B_REQUEST=0" in WORKFLOW


def test_target_origin_smoke_checks_login_start_without_exposing_state() -> None:
    assert "https://chat.padiem.net/auth/google/callback" in WORKFLOW
    assert "AUTH_START_REDIRECT_URI_CANONICAL=PASS" in WORKFLOW
    assert "AUTH_START_STATE_COOKIE_CONTRACT=PASS" in WORKFLOW
    assert "OAUTH_STATE_VALUE_OUTPUT=0" in WORKFLOW
    assert "jq -e '.ready == true and .authenticated == false and .session_state == \"guest\"'" in WORKFLOW


def test_canonical_origin_is_updated_in_existing_auth_and_deploy_gates() -> None:
    assert 'default: "https://chat.padiem.net"' in AUTH_WORKFLOW
    assert "https://padiem-chat.charliekant.workers.dev" not in AUTH_WORKFLOW

    assert "B62_PUBLIC_BASE_URL: https://chat.padiem.net" in DEPLOY_WORKFLOW
    assert "B62_PUBLIC_ORIGIN=CHAT_PADIEM_NET" in DEPLOY_WORKFLOW
    assert "https://padiem-chat.charliekant.workers.dev" not in DEPLOY_WORKFLOW
