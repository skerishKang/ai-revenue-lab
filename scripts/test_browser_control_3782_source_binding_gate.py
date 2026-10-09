"""#3782 source-only deployment declaration graph; no D1/network mutation."""
from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from browser_control_3782_source_binding_gate import (
    CHAT_WRANGLER,
    ENGINE_WRANGLER,
    evaluate,
    inspect_source_config,
)

SCRIPT = Path(__file__).with_name("browser_control_3782_source_binding_gate.py")


def _complete():
    owner = "11111111-1111-4111-8111-111111111111"
    return (
        {
            "d1_databases": [
                {"binding": "PADIEM_CHAT_DB", "database_id": "33333333-3333-4333-8333-333333333333"},
                {"binding": "BROWSER_CONTROL_OWNER_P01_D1", "database_id": owner},
            ],
            "services": [
                {"binding": "P01_ENGINE_SERVICE", "service": "padiem-ai-engine"},
                {"binding": "IDENTITY_AUTHORITY_SERVICE", "service": "padiem-control-plane-identity"},
            ],
        },
        {
            "d1_databases": [
                {"binding": "ENGINE_CONTINUATION", "database_id": "22222222-2222-4222-8222-222222222222"},
                {"binding": "BROWSER_CONTROL_OWNER_P01_D1", "database_id": owner},
            ],
            "services": [
                {"binding": "CONTROL_PLANE_IDENTITY", "service": "padiem-control-plane-identity"},
            ],
        },
    )


def test_actual_repository_worker_source_declarations_are_blocked_without_provisioning():
    result = inspect_source_config()
    assert result.summary()["outcome"] == "BLOCKED"
    assert result.summary()["production_activation_authorized"] is False
    assert {
        "B54_PRIMARY_D1_MISSING_OR_NO_ID",
        "B54_INDEPENDENT_OWNER_D1_MISSING_OR_NO_ID",
        "ENGINE_INDEPENDENT_OWNER_D1_MISSING_OR_NO_ID",
        "B54_EXISTING_P01_ENGINE_SERVICE_MISSING",
        "B54_CURRENT_USER_IDENTITY_SERVICE_MISSING",
    }.issubset(result.blockers)
    assert CHAT_WRANGLER.exists() and ENGINE_WRANGLER.exists()
    assert "ENGINE_ORIGINAL_CONTINUATION_D1_MISSING_OR_NO_ID" not in result.blockers


def test_complete_source_graph_never_claims_live_remote_provision_or_p01():
    chat, engine = _complete()
    evaluated = evaluate(chat=chat, engine=engine)
    assert evaluated.blockers == ()
    assert evaluated.summary() == {
        "scope": "source_declarations_only",
        "outcome": "SOURCE_GRAPH_VALID_NOT_AUTHORIZED",
        "blockers": [],
        "remote_database_provision_verified": False,
        "owner_schema_applied_verified": False,
        "real_user_p01_verified": False,
        "production_activation_authorized": False,
    }


@pytest.mark.parametrize("change,reason", [
    ("different_owner", "OWNER_D1_CROSS_SERVICE_DATABASE_ID_MISMATCH"),
    ("owner_aliases_engine", "OWNER_D1_ALIASES_PRIMARY_OR_ORIGINAL_ENGINE"),
    ("owner_aliases_chat", "OWNER_D1_ALIASES_PRIMARY_OR_ORIGINAL_ENGINE"),
    ("same_primary", "ENGINE_D1_ALIASES_CHAT_PRIMARY"),
    ("wrong_engine_target", "B54_EXISTING_P01_ENGINE_SERVICE_TARGET_MISMATCH"),
    ("missing_engine_target", "B54_EXISTING_P01_ENGINE_SERVICE_MISSING"),
    ("wrong_identity", "B54_CURRENT_USER_IDENTITY_SERVICE_TARGET_MISMATCH"),
    ("missing_owner", "ENGINE_INDEPENDENT_OWNER_D1_MISSING_OR_NO_ID"),
    ("duplicate_d1", "D1_BINDING_DECLARATIONS_INVALID"),
    ("duplicate_service", "SERVICE_BINDING_DECLARATIONS_INVALID"),
    ("missing_owner_id", "B54_INDEPENDENT_OWNER_D1_MISSING_OR_NO_ID"),
    ("invalid_matching_owner_ids", "B54_INDEPENDENT_OWNER_D1_MISSING_OR_NO_ID"),
])
def test_missing_foreign_or_aliased_binding_fails_closed(change, reason):
    chat, engine = _complete()
    chat, engine = deepcopy(chat), deepcopy(engine)
    if change == "different_owner":
        engine["d1_databases"][1]["database_id"] = "99999999-9999-4999-8999-999999999999"
    elif change == "owner_aliases_engine":
        engine["d1_databases"][1]["database_id"] = engine["d1_databases"][0]["database_id"]
        chat["d1_databases"][1]["database_id"] = engine["d1_databases"][1]["database_id"]
    elif change == "owner_aliases_chat":
        engine["d1_databases"][1]["database_id"] = chat["d1_databases"][0]["database_id"]
        chat["d1_databases"][1]["database_id"] = chat["d1_databases"][0]["database_id"]
    elif change == "same_primary":
        engine["d1_databases"][0]["database_id"] = chat["d1_databases"][0]["database_id"]
    elif change == "wrong_engine_target":
        chat["services"][0]["service"] = "other-engine"
    elif change == "missing_engine_target":
        chat["services"].pop(0)
    elif change == "wrong_identity":
        chat["services"][1]["service"] = "unrelated-identity"
    elif change == "missing_owner":
        engine["d1_databases"].pop()
    elif change == "duplicate_d1":
        engine["d1_databases"].append(dict(engine["d1_databases"][1]))
    elif change == "duplicate_service":
        chat["services"].append(dict(chat["services"][0]))
    elif change == "missing_owner_id":
        del chat["d1_databases"][1]["database_id"]
    elif change == "invalid_matching_owner_ids":
        engine["d1_databases"][1]["database_id"] = "not-a-cloudflare-d1-uuid"
        chat["d1_databases"][1]["database_id"] = "not-a-cloudflare-d1-uuid"
    result = evaluate(chat=chat, engine=engine)
    assert reason in result.blockers
    assert result.summary()["outcome"] == "BLOCKED"
    assert result.summary()["production_activation_authorized"] is False


def test_unreadable_config_fails_closed_without_echoing_path_or_secrets(tmp_path):
    missing = tmp_path / "user-private-token-is-never-leaked.toml"
    response = inspect_source_config(missing, ENGINE_WRANGLER)
    assert response.blockers == ("SOURCE_CONFIG_UNAVAILABLE_OR_INVALID",)
    assert "user-private-token" not in json.dumps(response.summary())
    response = subprocess.run(
        [sys.executable, str(SCRIPT), "--chat-config", str(missing)],
        capture_output=True, encoding="utf-8", timeout=10,
        check=False,
    )
    assert response.returncode == 2
    assert json.loads(response.stdout)["blockers"] == [
        "SOURCE_CONFIG_UNAVAILABLE_OR_INVALID"
    ]
    assert "user-private-token" not in response.stdout + response.stderr


def test_cli_real_source_uses_only_bounded_non_sensitive_reason_codes():
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, encoding="utf-8", timeout=10, check=False,
    )
    assert result.returncode == 2
    rendered = json.loads(result.stdout)
    assert rendered["outcome"] == "BLOCKED"
    assert all(reason.upper() == reason for reason in rendered["blockers"])
    assert rendered["remote_database_provision_verified"] is False
    # Database identifiers, credential values, physical Worker config, user
    # session references and action material MUST NEVER be echoed.
    assert "6b77ad02-bc27-488f-bb97-6325f6750cba" not in result.stdout
    assert "credential" not in result.stdout.lower()
