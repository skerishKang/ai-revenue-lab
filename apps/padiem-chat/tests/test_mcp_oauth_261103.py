"""MCP OAuth 2.1 web-connector contracts on the existing Chat login."""
from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from starlette.responses import Response

from app.mcp_oauth_metadata import authorization_challenge, canonical_resource
from app.shared_login_flow import (
    LOGIN_RETURN_COOKIE, clear_login_return_cookie, login_return_target,
    safe_login_return, set_login_return_cookie,
)
from test_5222_account_model_selection import BASE, client_for, session
from test_mcp_gateway_account import DEVICE, Pairing, account_app, setup


RESOURCE = BASE + "/api/mcp"
REDIRECT = "https://claude.test/callback"
OTHER_DEVICE = "node//other-owner-pc"


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


async def _tools_list(client, token):
    return await client.post("/api/mcp", headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-11-25",
    }, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})


@pytest.fixture
def app_ctx():
    db, owner, other, store = setup()
    app = account_app(db, owner, store)
    app.state.pc_device_pairing_store = Pairing(owner)
    return app, owner, other, store


@pytest.mark.asyncio
async def test_metadata_documents_and_401_challenge(app_ctx):
    app, _owner, _other, _store = app_ctx
    async with client_for(app) as client:
        resource = await client.get("/.well-known/oauth-protected-resource")
        assert resource.status_code == 200 and "no-store" in resource.headers["cache-control"]
        document = resource.json()
        assert document["resource"] == RESOURCE
        assert document["authorization_servers"] == [BASE]
        assert document["scopes_supported"] == ["mcp:pc"]
        path_document = await client.get("/.well-known/oauth-protected-resource/api/mcp")
        assert path_document.json()["resource"] == RESOURCE
        server = await client.get("/.well-known/oauth-authorization-server")
        assert server.status_code == 200
        metadata = server.json()
        assert metadata["issuer"] == BASE
        assert metadata["authorization_endpoint"] == BASE + "/oauth/authorize"
        assert metadata["token_endpoint"] == BASE + "/oauth/token"
        assert metadata["registration_endpoint"] == BASE + "/oauth/register"
        assert metadata["revocation_endpoint"] == BASE + "/oauth/revoke"
        assert metadata["code_challenge_methods_supported"] == ["S256"]
        assert metadata["authorization_response_iss_parameter_supported"] is True
        assert metadata["client_id_metadata_document_supported"] is False
        assert "none" in metadata["token_endpoint_auth_methods_supported"]
        denied = await client.post("/api/mcp", headers={
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-11-25",
        }, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        assert denied.status_code == 401
        assert 'resource_metadata="' + BASE + '/.well-known/oauth-protected-resource"' in denied.headers["www-authenticate"]
        assert 'scope="mcp:pc"' in denied.headers["www-authenticate"]
        invalid = await client.post("/api/mcp", headers={
            "Authorization": "Bearer mcp_" + "0" * 32 + ".invalid",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-11-25",
        }, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        assert invalid.status_code == 401
        assert 'error="invalid_token"' in invalid.headers["www-authenticate"]
    assert canonical_resource(app.state.settings) == RESOURCE
    assert 'resource_metadata="' + BASE + '/.well-known/oauth-protected-resource"' in authorization_challenge(app.state.settings)


@pytest.mark.asyncio
async def test_registration_validation_and_confidential_secret(app_ctx):
    app, _owner, _other, _store = app_ctx
    async with client_for(app) as client:
        public = await _register(client, name="Claude")
        assert public["client_id"].startswith("mcpc_")
        assert public["token_endpoint_auth_method"] == "none"
        assert "client_secret" not in public
        confidential = await _register(client, name="Secret Client", method="client_secret_post")
        assert confidential["client_secret"].startswith("mcs_")
        assert confidential["client_secret_expires_at"] == 0
        for body in (
            {"client_name": "Bad", "redirect_uris": ["http://evil.example/cb"]},
            {"client_name": "Bad", "redirect_uris": ["https://user:pass@client.example/cb"]},
            {"client_name": "Bad", "redirect_uris": ["https://client.example/cb#fragment"]},
            {"client_name": "", "redirect_uris": [REDIRECT]},
            {"client_name": "Bad", "redirect_uris": [REDIRECT], "token_endpoint_auth_method": "private_key_jwt"},
            {"client_name": "Bad", "redirect_uris": [REDIRECT], "grant_types": ["client_credentials"]},
        ):
            response = await client.post("/oauth/register", json=body)
            assert response.status_code == 400, body
            assert response.json()["error"] == "invalid_client_metadata"


@pytest.mark.asyncio
async def test_consent_page_and_info_list_only_the_signed_in_users_pc(app_ctx):
    app, owner, other, _store = app_ctx
    async with client_for(app) as external:
        registered = await _register(external)
        verifier, _ = _pkce()
        params = _params(registered["client_id"], verifier)
        async with client_for(app) as owner_ui:
            owner_ui.cookies.update(session(app, owner))
            page = await owner_ui.get("/oauth/authorize", params=params)
            assert page.status_code == 200
            assert 'data-locale-key="mcp-oauth-capability"' in page.text
            info = await owner_ui.get("/oauth/authorize/info", params=params)
            assert info.status_code == 200
            body = info.json()
            assert body["client_name"] == "Claude"
            assert [pc["device_id"] for pc in body["pcs"]] == [DEVICE]
            assert body["pcs"][0]["label"] == "Owner PC"
            assert body["scope"] == "mcp:pc"
            assert body["issuer"] == BASE
        async with client_for(app) as other_ui:
            other_ui.cookies.update(session(app, other))
            other_info = await other_ui.get("/oauth/authorize/info", params=params)
            assert other_info.status_code == 200
            assert other_info.json()["pcs"] == []


@pytest.mark.asyncio
async def test_full_pkce_code_token_refresh_revoke_and_pat_regression(app_ctx):
    app, owner, _other, store = app_ctx
    async with client_for(app) as external, client_for(app) as owner_ui:
        registered = await _register(external)
        client_id = registered["client_id"]
        verifier, _ = _pkce()
        params = _params(client_id, verifier)
        owner_ui.cookies.update(session(app, owner))
        approved = await _approve(owner_ui, params)
        assert approved.status_code == 200, approved.text
        code, redirect_query = _code_from(approved.json()["redirect_url"])
        assert redirect_query["state"] == ["state_fixture"]
        assert redirect_query["iss"] == [BASE]
        exchanged = await _exchange(external, client_id, code, verifier)
        assert exchanged.status_code == 200, exchanged.text
        tokens = exchanged.json()
        assert tokens["token_type"] == "Bearer"
        assert tokens["expires_in"] == 3600
        assert tokens["scope"] == "mcp:pc"
        assert tokens["refresh_token"] != tokens["access_token"]
        tools = await _tools_list(external, tokens["access_token"])
        assert tools.status_code == 200
        assert any(tool["name"] == "pc_list" for tool in tools.json()["result"]["tools"])
        refreshed = await external.post("/oauth/token", data={
            "grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
            "client_id": client_id,
        })
        assert refreshed.status_code == 200, refreshed.text
        rotated = refreshed.json()
        assert rotated["access_token"] != tokens["access_token"]
        assert rotated["refresh_token"] != tokens["refresh_token"]
        assert (await _tools_list(external, tokens["access_token"])).status_code == 401
        assert (await _tools_list(external, rotated["access_token"])).status_code == 200
        replay = await external.post("/oauth/token", data={
            "grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
            "client_id": client_id,
        })
        assert replay.status_code == 400 and replay.json()["error"] == "invalid_grant"
        revoked = await external.post("/oauth/revoke", data={
            "token": rotated["access_token"], "client_id": client_id,
        })
        assert revoked.status_code == 200
        assert (await _tools_list(external, rotated["access_token"])).status_code == 401
        pat = await store.issue_token(user_id=owner, device_id=DEVICE, name="Claude Code PAT")
        assert (await _tools_list(external, pat["token"])).status_code == 200
        assert await store.revoke_token(user_id=owner, token_id=pat["id"])
        assert (await _tools_list(external, pat["token"])).status_code == 401


@pytest.mark.asyncio
async def test_pkce_code_reuse_and_redirect_uri_rejections(app_ctx):
    app, owner, _other, _store = app_ctx
    async with client_for(app) as external, client_for(app) as owner_ui:
        registered = await _register(external)
        client_id = registered["client_id"]
        verifier, _ = _pkce()
        params = _params(client_id, verifier)
        owner_ui.cookies.update(session(app, owner))
        missing = await owner_ui.get("/oauth/authorize", params=_params(
            client_id, verifier, include_challenge=False))
        assert missing.status_code == 400 and missing.json()["error"] == "invalid_request"
        plain = await owner_ui.get("/oauth/authorize", params=_params(
            client_id, verifier, challenge_method="plain"))
        assert plain.status_code == 400
        wrong_redirect = await owner_ui.get("/oauth/authorize", params=_params(
            client_id, verifier, redirect="https://claude.test/other"))
        assert wrong_redirect.status_code == 400
        approved = await _approve(owner_ui, params)
        code, _ = _code_from(approved.json()["redirect_url"])
        wrong_verifier = await _exchange(external, client_id, code, secrets.token_urlsafe(48))
        assert wrong_verifier.status_code == 400
        assert wrong_verifier.json()["error"] == "invalid_grant"
        second = await _approve(owner_ui, params)
        code2, _ = _code_from(second.json()["redirect_url"])
        first_exchange = await _exchange(external, client_id, code2, verifier)
        assert first_exchange.status_code == 200
        reused = await _exchange(external, client_id, code2, verifier)
        assert reused.status_code == 400 and reused.json()["error"] == "invalid_grant"
        third = await _approve(owner_ui, params)
        code3, _ = _code_from(third.json()["redirect_url"])
        mismatched = await _exchange(external, client_id, code3, verifier,
                                     redirect="https://claude.test/other")
        assert mismatched.status_code == 400 and mismatched.json()["error"] == "invalid_grant"
        fourth = await _approve(owner_ui, params)
        code4, _ = _code_from(fourth.json()["redirect_url"])
        wrong_resource = await _exchange(external, client_id, code4, verifier,
                                         resource="https://other.example/mcp")
        assert wrong_resource.status_code == 400
        assert wrong_resource.json()["error"] == "invalid_target"


@pytest.mark.asyncio
async def test_confidential_client_secret_is_required(app_ctx):
    app, owner, _other, _store = app_ctx
    async with client_for(app) as external, client_for(app) as owner_ui:
        registered = await _register(external, name="Secret Client", method="client_secret_post")
        verifier, _ = _pkce()
        params = _params(registered["client_id"], verifier)
        owner_ui.cookies.update(session(app, owner))
        approved = await _approve(owner_ui, params)
        code, _ = _code_from(approved.json()["redirect_url"])
        absent = await _exchange(external, registered["client_id"], code, verifier)
        assert absent.status_code == 401 and absent.json()["error"] == "invalid_client"
        approved2 = await _approve(owner_ui, params)
        code2, _ = _code_from(approved2.json()["redirect_url"])
        wrong = await _exchange(external, registered["client_id"], code2, verifier,
                                secret="wrong-secret")
        assert wrong.status_code == 401
        approved3 = await _approve(owner_ui, params)
        code3, _ = _code_from(approved3.json()["redirect_url"])
        accepted = await _exchange(external, registered["client_id"], code3, verifier,
                                   secret=registered["client_secret"])
        assert accepted.status_code == 200


@pytest.mark.asyncio
async def test_other_users_pc_cannot_be_selected(app_ctx):
    app, owner, other, _store = app_ctx

    class TwoUserPairing:
        async def link_for(self, *, user_id, mesh_node_id):
            if user_id == owner and mesh_node_id == DEVICE:
                return {"mesh_node_id": DEVICE, "roots": [{"path": "C:/Documents"}]}
            return None

        async def links_for_owner(self, *, user_id):
            if user_id == owner:
                return [{"mesh_node_id": DEVICE, "label": "Owner PC", "roots": []}]
            if user_id == other:
                return [{"mesh_node_id": OTHER_DEVICE, "label": "Other PC", "roots": []}]
            return []

    app.state.pc_device_pairing_store = TwoUserPairing()
    async with client_for(app) as external, client_for(app) as owner_ui:
        registered = await _register(external)
        verifier, _ = _pkce()
        params = _params(registered["client_id"], verifier)
        owner_ui.cookies.update(session(app, owner))
        info = await owner_ui.get("/oauth/authorize/info", params=params)
        assert [pc["device_id"] for pc in info.json()["pcs"]] == [DEVICE]
        denied = await _approve(owner_ui, params, device_id=OTHER_DEVICE)
        assert denied.status_code == 403
        assert denied.json()["error"] == "pc_device_unavailable"
        assert (await _approve(owner_ui, params, device_id="not-a-device")).status_code == 403


@pytest.mark.asyncio
async def test_expired_oauth_access_token_is_rejected(app_ctx):
    app, owner, _other, store = app_ctx
    async with client_for(app) as external:
        registered = await _register(external)
        issued = await store.issue_oauth_tokens(
            client_name="Claude", client_id=registered["client_id"], user_id=owner,
            device_id=DEVICE, scope="mcp:pc", resource=RESOURCE,
            now=datetime.now(timezone.utc) - timedelta(hours=2))
        assert (await _tools_list(external, issued["access_token"])).status_code == 401


@pytest.mark.asyncio
async def test_oauth_token_for_another_resource_is_rejected(app_ctx):
    app, owner, _other, store = app_ctx
    async with client_for(app) as external:
        registered = await _register(external)
        issued = await store.issue_oauth_tokens(
            client_name="Claude", client_id=registered["client_id"], user_id=owner,
            device_id=DEVICE, scope="mcp:pc", resource="https://other.example/mcp")
        assert (await _tools_list(external, issued["access_token"])).status_code == 401


@pytest.mark.asyncio
async def test_authorize_login_redirect_and_info_login_required(app_ctx):
    app, _owner, _other, _store = app_ctx
    async with client_for(app) as external:
        registered = await _register(external)
        verifier, _ = _pkce()
        params = _params(registered["client_id"], verifier)
        async with client_for(app) as guest:
            page = await guest.get("/oauth/authorize", params=params)
            assert page.status_code == 200
            info = await guest.get("/oauth/authorize/info", params=params)
            assert info.status_code == 401
            assert info.headers["x-mcp-login-url"] == "/"
    app.state.shared_login_flow = SimpleNamespace()
    async with client_for(app) as external, client_for(app) as guest:
        registered = await _register(external)
        verifier, _ = _pkce()
        params = _params(registered["client_id"], verifier)
        redirected = await guest.get("/oauth/authorize", params=params)
        assert redirected.status_code == 302
        assert redirected.headers["location"] == "/auth/shared/start"
        assert "__Host-padiem-login-return" in redirected.headers.get("set-cookie", "")
        info = await guest.get("/oauth/authorize/info", params=params)
        assert info.status_code == 401
        assert info.headers["x-mcp-login-url"].startswith("/oauth/authorize?")


def test_consent_copy_is_localized_in_both_languages():
    static = Path(__file__).resolve().parents[1] / "static"
    locale = (static / "locale.js").read_text(encoding="utf-8")
    page = (static / "mcp-oauth-consent.html").read_text(encoding="utf-8")
    script = (static / "mcp-oauth-consent.js").read_text(encoding="utf-8")
    assert locale.count('"mcp-oauth-title"') == 2
    assert locale.count('"mcp-oauth-capability"') == 2
    assert "이 AI가 내 PC에서 파일·명령·브라우저 작업을 할 수 있습니다." in locale
    assert "This AI can work with files, commands, and the browser on my PC." in locale
    assert 'data-locale-key="mcp-oauth-capability"' in page
    assert "/locale.js" in page and "/mcp-oauth-consent.js" in page
    assert "/oauth/authorize/info" in script and "/oauth/authorize" in script


def test_login_return_cookie_is_same_origin_only():
    assert safe_login_return("/oauth/authorize?client_id=abc&state=1") == "/oauth/authorize?client_id=abc&state=1"
    for unsafe in ("//evil.example", "https://evil.example", "/\\evil", "", "  ", "/bad\x01"):
        assert safe_login_return(unsafe) == "/"
    assert safe_login_return("/" + "x" * 5000) == "/"
    response = Response()
    set_login_return_cookie(response, "/oauth/authorize?state=ok")
    cookie = response.headers["set-cookie"]
    assert LOGIN_RETURN_COOKIE in cookie and "Path=/" in cookie and "HttpOnly" in cookie and "Secure" in cookie
    request = SimpleNamespace(cookies={LOGIN_RETURN_COOKIE: "/oauth/authorize?state=ok"})
    assert login_return_target(request) == "/oauth/authorize?state=ok"
    cleared = clear_login_return_cookie(Response())
    assert LOGIN_RETURN_COOKIE in cleared.headers["set-cookie"]

