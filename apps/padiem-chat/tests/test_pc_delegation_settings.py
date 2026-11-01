"""Real settings persistence and owner/transport boundaries for PC delegation."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from padiem_ai_core.pc_delegation import normalize_pc_delegation_path, parse_pc_delegation
from app.pc_delegation_routes import PC_DELEGATION_PATH, load_pc_delegation
from app.pc_delegation_store import D1PcDelegationStore, PcDelegationStoreError
from test_5222_account_model_selection import build_app, client_for, seed_db, session, BASE


MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "081_pc_delegations.sql"
RULE = {"id": "rule-a", "device_id": "node/pc-a", "folder": "C:/Documents",
        "actions": ["write", "move"], "mode": "allow", "enabled": True}
POLICY = {"version": 1, "rules": [RULE]}


def setup_db():
    db, owner, other, _ = seed_db()
    db.conn.executescript(MIGRATION.read_text())
    return db, owner, other


@pytest.mark.asyncio
async def test_real_database_is_owner_scoped_and_disable_survives_reload():
    db, owner, other = setup_db()
    store = D1PcDelegationStore(db)
    assert await store.load(owner) == {"version": 1, "rules": [], "updated_at": None}
    saved = await store.save(owner, POLICY)
    assert saved["rules"] == [RULE]
    assert (await store.load(other))["rules"] == []
    disabled = deepcopy(POLICY)
    disabled["rules"][0]["enabled"] = False
    await store.save(owner, disabled)
    reloaded = await D1PcDelegationStore(db).load(owner)
    assert reloaded["rules"] == disabled["rules"]
    assert reloaded["updated_at"]
    # The migration is additive and repeatable; it does not reset delegation.
    db.conn.executescript(MIGRATION.read_text())
    assert (await store.load(owner))["rules"] == disabled["rules"]


@pytest.mark.asyncio
async def test_store_cannot_persist_send_or_internal_availability():
    db, owner, _ = setup_db()
    store = D1PcDelegationStore(db)
    invalid = deepcopy(POLICY)
    invalid["rules"][0]["actions"] = ["send"]
    for policy in (invalid, {**POLICY, "available": True}):
        with pytest.raises(PcDelegationStoreError):
            await store.save(owner, policy)
    assert (await store.load(owner))["rules"] == []


@pytest.mark.asyncio
async def test_settings_api_round_trip_and_other_account_cannot_address_owner():
    db, owner, other = setup_db()
    app = build_app(db)
    async with client_for(app) as client:
        client.cookies.update(session(app, owner))
        response = await client.put(PC_DELEGATION_PATH, headers={"Origin": BASE}, json=POLICY)
        assert response.status_code == 200, response.text
        assert response.json()["rules"] == [RULE]
        read = await client.get(PC_DELEGATION_PATH)
        assert read.json() == response.json()
        assert "no-store" in read.headers["cache-control"]
        client.cookies.update(session(app, other))
        assert (await client.get(PC_DELEGATION_PATH)).json()["rules"] == []
        forged = await client.put(PC_DELEGATION_PATH, headers={"Origin": BASE}, json={**POLICY, "owner_id": owner})
        assert forged.status_code == 422
        assert (await app.state.pc_delegation_store.load(owner))["rules"] == [RULE]
        assert (await app.state.pc_delegation_store.load(other))["rules"] == []


@pytest.mark.asyncio
async def test_settings_api_requires_session_and_same_origin():
    db, owner, _ = setup_db()
    app = build_app(db)
    async with client_for(app) as client:
        assert (await client.get(PC_DELEGATION_PATH)).status_code == 401
        assert (await client.put(PC_DELEGATION_PATH, headers={"Origin": BASE}, json=POLICY)).status_code == 401
        client.cookies.update(session(app, owner))
        cross_site = await client.put(PC_DELEGATION_PATH, headers={"Origin": "https://other.example.test"}, json=POLICY)
        assert cross_site.status_code == 403
        assert (await app.state.pc_delegation_store.load(owner))["rules"] == []


@pytest.mark.asyncio
async def test_unmigrated_database_is_unknown_for_execution_and_503_for_settings():
    db, owner, _, _ = seed_db()
    app = build_app(db)
    request = SimpleNamespace(app=app)
    assert await load_pc_delegation(request, owner) == {"version": 1, "available": False, "rules": []}
    async with client_for(app) as client:
        client.cookies.update(session(app, owner))
        assert (await client.get(PC_DELEGATION_PATH)).status_code == 503
        assert (await client.put(PC_DELEGATION_PATH, headers={"Origin": BASE}, json=POLICY)).status_code == 503


@pytest.mark.asyncio
async def test_real_no_rule_is_default_but_corrupt_or_missing_store_is_not_default():
    db, owner, _ = setup_db()
    store = D1PcDelegationStore(db)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pc_delegation_store=store)))
    assert await load_pc_delegation(request, owner) == {"version": 1, "rules": []}
    await store.save(owner, POLICY)
    assert await load_pc_delegation(request, owner) == POLICY
    db.conn.execute("UPDATE padiem_pc_delegations SET settings_json=? WHERE user_id=?", (json.dumps({"version": 1, "rules": "broken"}), owner))
    assert (await load_pc_delegation(request, owner))["available"] is False
    request.app.state.pc_delegation_store = None
    assert (await load_pc_delegation(request, owner))["available"] is False


@pytest.mark.asyncio
async def test_loader_does_not_strip_an_unknown_store_availability_into_default():
    class UnavailableStore:
        async def load(self, _owner):
            return {"version": 1, "rules": [], "available": False}

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pc_delegation_store=UnavailableStore())))
    assert (await load_pc_delegation(request, "owner"))["available"] is False


@pytest.mark.parametrize("folder,expected", [
    ("C:\\Documents\\Work\\", "C:/Documents/Work"),
    ("d:/", "D:/"), ("docs/./child/", "docs/child"),
    (".", "."), ("//server/share/work", "//server/share/work"),
])
def test_folder_normalization_preserves_scope(folder, expected):
    assert normalize_pc_delegation_path(folder) == expected


@pytest.mark.parametrize("folder", ["docs/../private", "docs/*", "C:relative", "file:stream", "https://host/path", "docs/a. ", "//server", "folder\x00name"])
def test_ambiguous_or_non_filesystem_folder_cannot_be_delegated(folder):
    policy = deepcopy(POLICY)
    policy["rules"][0]["folder"] = folder
    with pytest.raises(ValueError):
        parse_pc_delegation(policy)


@pytest.mark.parametrize("mutate", [
    lambda value: value.update(version=True),
    lambda value: value.update(available="yes"),
    lambda value: value["rules"].append(deepcopy(RULE)),
    lambda value: value["rules"][0].update(enabled=1),
    lambda value: value["rules"][0].update(actions=["write", "send"]),
    lambda value: value["rules"][0].update(actions=["write", "write"]),
    lambda value: value["rules"][0].update(mode="skip_checks"),
    lambda value: value["rules"][0].update(owner_id="someone-else"),
])
def test_closed_schema_cannot_mint_other_authority(mutate):
    value = deepcopy(POLICY)
    mutate(value)
    with pytest.raises(ValueError):
        parse_pc_delegation(value)


def test_internal_availability_is_preserved_without_mutating_input():
    value = {**deepcopy(POLICY), "available": False}
    parsed = parse_pc_delegation(value)
    parsed["rules"][0]["actions"].append("delete")
    assert value["rules"][0]["actions"] == ["write", "move"]
    assert parsed["available"] is False
    assert parse_pc_delegation(None) is None
