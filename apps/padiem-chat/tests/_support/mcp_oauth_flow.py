"""#8061: shared MCP OAuth flow helpers used by several Chat OAuth tests.

These fixtures were previously defined in ``test_mcp_oauth_261103.py`` and imported
by sibling test modules. They live here so test modules no longer import each other.
Contracts, values and assertions are unchanged — only the module location moved.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlsplit

from _support.account_selection import BASE
from _support.mcp_gateway_account import DEVICE

RESOURCE = BASE + "/api/mcp"
REDIRECT = "https://claude.test/callback"


def _pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _params(client_id, verifier, *, redirect=REDIRECT, state="state_fixture",
            resource=RESOURCE, include_challenge=True, challenge_method="S256",
            scope="mcp:pc"):
    _, challenge = _pkce()
    if verifier is not None:
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
    result = {
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect,
        "state": state, "resource": resource, "scope": scope,
    }
    if include_challenge:
        result["code_challenge"] = challenge
        result["code_challenge_method"] = challenge_method
    return result


async def _register(client, *, name="Claude", redirect=REDIRECT, method="none"):
    response = await client.post("/oauth/register", json={
        "client_name": name, "redirect_uris": [redirect],
        "token_endpoint_auth_method": method,
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"], "scope": "mcp:pc",
    })
    assert response.status_code == 201, response.text
    return response.json()


async def _approve(owner_ui, params, *, device_id=DEVICE):
    return await owner_ui.post("/oauth/authorize", json={
        **params, "decision": "approve", "device_id": device_id,
    }, headers={"Origin": BASE})


def _code_from(redirect_url):
    query = parse_qs(urlsplit(redirect_url).query)
    return query["code"][0], query


async def _exchange(client, client_id, code, verifier, *, redirect=REDIRECT, secret=None,
                    resource=RESOURCE):
    data = {
        "grant_type": "authorization_code", "code": code, "redirect_uri": redirect,
        "client_id": client_id, "code_verifier": verifier, "resource": resource,
    }
    if secret is not None:
        data["client_secret"] = secret
    return await client.post("/oauth/token", data=data)
