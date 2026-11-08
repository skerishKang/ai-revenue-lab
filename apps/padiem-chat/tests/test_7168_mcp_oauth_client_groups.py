"""#7168: MCP OAuth grants grouped by the AI client, with one bulk revoke.

The design follows the issue comment: no schema change, owner-scoped reads and
writer, no token/secret/hash in any response. UI wiring is explicitly out of
scope (comes after #7159).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.mcp_gateway_account_routes import (
    MCP_OAUTH_CLIENT_PATH,
    MCP_OAUTH_CLIENTS_PATH,
)
from app.mcp_oauth_metadata import MCP_OAUTH_SCOPE

from test_5222_account_model_selection import client_for, session
from test_mcp_gateway_account import BASE, DEVICE, NOW, account_app, setup

RESOURCE = "https://chat.example.test/api/mcp"
FORBIDDEN_KEY_PARTS = ("token", "secret", "sha", "hash", "refresh", "credential")


async def _client_registered(store, *, name: str = "Claude Desktop"):
    return await store.register_oauth_client(
        client_name=name, redirect_uris=["https://ai.example/callback"],
        token_endpoint_auth_method="none", now=NOW,
    )


async def _grant(store, *, owner: str, client: dict, minute: int = 0):
    return await store.issue_oauth_tokens(
        client_name=client["client_name"], client_id=client["client_id"],
        user_id=owner, device_id=DEVICE, scope=MCP_OAUTH_SCOPE,
        resource=RESOURCE, now=NOW + timedelta(minutes=minute), device_scope="all",
    )


def _assert_no_secret_material(value) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            assert not any(part in lowered for part in FORBIDDEN_KEY_PARTS), key
            _assert_no_secret_material(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_secret_material(item)


@pytest.mark.asyncio
async def test_three_authorizations_from_one_ai_are_one_group_and_revoke_at_once():
    db, owner, other, store = setup()
    client = await _client_registered(store)
    for minute in range(3):
        await _grant(store, owner=owner, client=client, minute=minute)

    groups = await store.list_oauth_clients(user_id=owner)
    assert len(groups) == 1
    group = groups[0]
    assert group["client_id"] == client["client_id"]
    assert group["client_name"] == "Claude Desktop"
    assert group["active_grants"] == 3
    assert group["devices"] == [DEVICE]
    assert group["scopes"] == [MCP_OAUTH_SCOPE]
    assert group["created_at"] and group["latest_grant_at"]
    _assert_no_secret_material(groups)

    app = account_app(db, owner, store)
    async with client_for(app) as http:
        assert (await http.get(MCP_OAUTH_CLIENTS_PATH)).status_code == 401
        http.cookies.update(session(app, owner))
        listed = await http.get(MCP_OAUTH_CLIENTS_PATH)
        assert listed.status_code == 200, listed.text
        body = listed.json()
        assert body["ok"] is True and body["clients"] == groups
        assert "no-store" in listed.headers["cache-control"]
        _assert_no_secret_material(body)

        denied = await http.delete(
            MCP_OAUTH_CLIENT_PATH.replace("{client_id}", client["client_id"]),
            headers={"Origin": "https://other.example.test"},
        )
        assert denied.status_code == 403

        revoked = await http.delete(
            MCP_OAUTH_CLIENT_PATH.replace("{client_id}", client["client_id"]),
            headers={"Origin": BASE},
        )
        assert revoked.status_code == 200, revoked.text
        assert revoked.json() == {"ok": True, "revoked": 3}
        again = await http.delete(
            MCP_OAUTH_CLIENT_PATH.replace("{client_id}", client["client_id"]),
            headers={"Origin": BASE},
        )
        assert again.status_code == 200
        assert again.json() == {"ok": True, "revoked": 0}
        assert (await http.get(MCP_OAUTH_CLIENTS_PATH)).json()["clients"] == []

    # The same client id used by another account is untouched.
    await _grant(store, owner=other, client=client, minute=5)
    assert await store.list_oauth_clients(user_id=owner) == []
    other_groups = await store.list_oauth_clients(user_id=other)
    assert len(other_groups) == 1 and other_groups[0]["active_grants"] == 1


@pytest.mark.asyncio
async def test_a_client_id_from_another_account_can_never_be_revoked_cross_owner():
    db, owner, other, store = setup()
    client = await _client_registered(store)
    await _grant(store, owner=owner, client=client)
    await _grant(store, owner=other, client=client, minute=1)

    app = account_app(db, owner, store)
    async with client_for(app) as http:
        http.cookies.update(session(app, owner))
        path = MCP_OAUTH_CLIENT_PATH.replace("{client_id}", client["client_id"])
        assert (await http.delete(path, headers={"Origin": BASE})).json()["revoked"] == 1
        # The other account's grant survives the owner's bulk revoke.
        http.cookies.update(session(app, other))
        groups = (await http.get(MCP_OAUTH_CLIENTS_PATH)).json()["clients"]
        assert len(groups) == 1 and groups[0]["active_grants"] == 1

        # Unknown client id: idempotent 200 with 0 revoked.
        unknown = MCP_OAUTH_CLIENT_PATH.replace("{client_id}", "mcpc_" + "a" * 32)
        response = await http.delete(unknown, headers={"Origin": BASE})
        assert response.status_code == 200
        assert response.json() == {"ok": True, "revoked": 0}
        # Malformed id is not a client id at all.
        malformed = MCP_OAUTH_CLIENT_PATH.replace("{client_id}", "not-a-client")
        assert (await http.delete(malformed, headers={"Origin": BASE})).status_code == 404


@pytest.mark.asyncio
async def test_delete_requires_the_signed_in_owner_and_same_origin():
    db, owner, _other, store = setup()
    client = await _client_registered(store)
    app = account_app(db, owner, store)
    async with client_for(app) as http:
        path = MCP_OAUTH_CLIENT_PATH.replace("{client_id}", client["client_id"])
        assert (await http.delete(path, headers={"Origin": BASE})).status_code == 401
        http.cookies.update(session(app, owner))
        assert (await http.delete(path, headers={'x-test-no-origin': '1'})).status_code == 403
