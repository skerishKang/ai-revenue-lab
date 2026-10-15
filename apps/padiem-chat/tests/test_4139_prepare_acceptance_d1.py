"""Connector staging D1 cannot be replaced by production or another QA D1."""
from __future__ import annotations

import tomllib

import pytest

from scripts.prepare_connector_acceptance import (
    DB_NAME, OUTPUT, StageRefused,
    dedicated_d1, render, trusted_template,
)

UUID = "fedcba98-7654-3210-acde-1234567890ab"


def test_stage_database_missing_and_exact_nonproduction_match():
    inventory = [
        {"name": "padiem-chat-db", "uuid": "12345678-1234-1234-1234-123456789001"},
        {"name": "padiem-b66-cgi-qa-261011", "uuid": "12345678-1234-1234-1234-123456789002"},
    ]
    with pytest.raises(StageRefused, match="dedicated_d1_missing"):
        dedicated_d1(inventory)
    assert dedicated_d1(inventory + [{"name": DB_NAME, "uuid": UUID}]) == {
        "name": DB_NAME, "uuid": UUID,
    }


def test_stage_database_ambiguity_and_other_db_alias_denied():
    with pytest.raises(StageRefused, match="ambiguous"):
        dedicated_d1([{"name": DB_NAME, "uuid": UUID}] * 2)
    with pytest.raises(StageRefused, match="invalid_uuid"):
        dedicated_d1([{"name": DB_NAME, "uuid": "not-a-uuid"}])
    with pytest.raises(StageRefused, match="aliases"):
        dedicated_d1([
            {"name": DB_NAME, "uuid": UUID},
            {"name": "padiem-chat-db", "uuid": UUID},
        ])


def test_stage_overlay_is_only_password_auth_and_dedicated_d1():
    cfg = tomllib.loads(render({"name": DB_NAME, "uuid": UUID}, trusted_template()))
    assert cfg["name"] == "padiem-chat-connector-acceptance-4139"
    assert cfg["workers_dev"] is False
    assert cfg["preview_urls"] is False
    assert "routes" not in cfg and "route" not in cfg
    assert cfg["vars"]["PADIEM_CHAT_RUNTIME_MODE"] == "mock"
    assert cfg["vars"]["PADIEM_CHAT_LIVE_ENABLED"] == "false"
    assert cfg["vars"]["PADIEM_CHAT_AUTH_MODE"] == "password"
    assert "PADIEM_CHAT_SESSION_SECRET" not in cfg["vars"]
    assert "PADIEM_CHAT_GOOGLE_CLIENT_SECRET" not in cfg["vars"]
    assert cfg["d1_databases"] == [{
        "binding": "PADIEM_CHAT_DB",
        "database_name": DB_NAME,
        "database_id": UUID,
        "migrations_dir": "migrations",
    }]
    assert OUTPUT.name == "wrangler.connector-acceptance-4139.local.toml"


def test_stage_overlay_rejects_unreviewed_resource():
    template = trusted_template()
    with pytest.raises(StageRefused, match="unreviewed_d1_resource"):
        render({"name": "padiem-chat-db", "uuid": UUID}, template)
    with pytest.raises(StageRefused, match="unreviewed_d1_resource"):
        render({"name": DB_NAME, "uuid": "invalid"}, template)
