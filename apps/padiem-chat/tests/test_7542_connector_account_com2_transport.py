"""P5-A reads cross the existing signed COM2 relay without bypassing authority gates."""
from __future__ import annotations

import ast
import asyncio
import importlib
import json
from pathlib import Path
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[3]
CONTROL = ROOT / "packages/padiem-control-plane"
SECRET = "synthetic-account-read-transport-secret-0123456789"
READS = frozenset({
    "resolve_connector_owner_scope_for_subject",
    "resolve_connector_enrollment_consent_for_subject_device",
    "resolve_connector_workspace_for_subject",
    "resolve_connector_context_for_subject",
})
LEGACY = frozenset({
    "resolve_or_create_product_link", "establish_auth_session",
    "resolve_auth_session", "resolve_current_auth_session",
    "revoke_auth_session", "revoke_all_auth_sessions",
    "resolve_product_user_for_subject", "resolve_connector_workspace",
    "resolve_connector_context", "resolve_connector_enrollment_consent_for_device",
    "bind_connector_enrollment_challenge", "authorize_connector_enrollment_redeem",
    "issue_google_connect_ticket", "create_tenant", "get_tenant",
    "assign_tenant_membership", "ensure_personal_tenant_membership",
    "revoke_tenant_membership", "resolve_active_memberships", "resolve_active_tenant_membership",
    "install_connector_enrollment_schema", "resolve_connector_owner_scope",
    "grant_connector_enrollment_consent", "revoke_connector_enrollment_consent",
})


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(CONTROL))
    return SimpleNamespace(
        ingress=importlib.import_module("com2_identity_rpc_ingress"),
        proxy=importlib.import_module("com2_identity_do_proxy"),
        account=importlib.import_module("canonical_connector_account_rpc"),
        proof=importlib.import_module("internal_rpc_ingress"),
    )


def _headers(modules, method, body, *, service_id, secret=SECRET):
    at = int(time.time())
    path = "/internal/rpc/" + method
    return {
        "x-padiem-service-at": str(at),
        modules.proof.SERVICE_ID_HEADER: service_id,
        "x-padiem-service-proof": modules.proof.proof_for_v2(
            secret, method="POST", path=path, at=at, service_id=service_id, body=body,
        ),
    }


def test_exact_account_reads_reuse_the_proxy_allowlist_and_worker_exports(modules):
    assert READS == modules.account.CONNECTOR_ACCOUNT_KEY_READ_METHODS
    assert LEGACY | READS <= modules.ingress.COM2_IDENTITY_RPC_METHODS
    assert modules.proxy.COM2_IDENTITY_RPC_METHODS is modules.ingress.COM2_IDENTITY_RPC_METHODS
    tree = ast.parse((CONTROL / "identity_authority_worker.py").read_text(encoding="utf-8"))
    ingress = next(node.value for node in tree.body if isinstance(node, ast.AnnAssign)
                   and isinstance(node.target, ast.Name) and node.target.id == "IDENTITY_RPC_INGRESS_METHODS")
    assert isinstance(ingress, ast.Call)
    assert READS <= set(ast.literal_eval(ingress.args[0]))
    entry = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Default")
    durable = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                   and node.name == "CanonicalIdentityDurableObject")
    assert any(isinstance(base, ast.Name) and base.id == "CanonicalIdentityAccountConnectorRPC"
               for base in durable.bases)
    for method in READS:
        matches = [node for node in entry.body if isinstance(node, ast.AsyncFunctionDef)
                   and node.name == method]
        assert len(matches) == 1
        assert ast.unparse(matches[0].body[-1]) == f"return await self._stub().{method}(payload)"


@pytest.mark.asyncio
@pytest.mark.parametrize("method", sorted(READS))
async def test_signed_account_read_preserves_disabled_authority_and_replay_guard(modules, tmp_path, method):
    # The real P5-A mixin must refuse before touching any account storage.
    authority = modules.account.CanonicalIdentityAccountConnectorRPC()
    authority.env = SimpleNamespace()
    forwarded = []

    def sender(url, body, headers):
        path = urlsplit(url).path
        assert path == "/internal/rpc/" + method
        service_id = headers[modules.proof.SERVICE_ID_HEADER]
        assert headers["x-padiem-service-proof"] == modules.proof.proof_for_v2(
            SECRET, method="POST", path=path, at=int(headers["x-padiem-service-at"]),
            service_id=service_id, body=body,
        )
        forwarded.append((service_id, json.loads(body)))
        return asyncio.run(getattr(authority, method)(json.loads(body)))

    proxy = modules.proxy.IdentityDoProxy("https://identity.example.invalid", SECRET, sender=sender)
    app = modules.ingress.create_app(
        authority=proxy, secret=SECRET, service_id_policy="required",
        replay_db=str(tmp_path / "request-ids.sqlite3"),
    )
    payload = {"product_id": "b62", "canonical_subject_id": "sub_synthetic_transport"}
    if method.endswith("_device"):
        payload["device_id"] = "fixture-device"
    body = json.dumps(payload).encode()
    request_id = "account-read-fixture-00000001"
    headers = _headers(modules, method, body, service_id=request_id)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                base_url="https://relay.example.invalid") as client:
        path = "/internal/rpc/" + method
        first = await client.post(path, content=body, headers=headers)
        replay = await client.post(path, content=body, headers=headers)
        missing = await client.post(path, content=body)
        wrong = await client.post(path, content=body, headers=_headers(
            modules, method, body, service_id="account-read-fixture-00000002", secret="wrong-test-proof"))
        changed = await client.post(path, content=body + b" ", headers=headers)
    assert first.status_code == 200
    assert first.json() == {"ok": False, "error": {
        "code": "connector_account_key_rpc_disabled",
        "message": "Canonical identity request was rejected",
    }}
    assert replay.status_code == 409
    assert replay.json()["error"]["code"] == "rpc_replay_detected"
    assert missing.status_code == wrong.status_code == changed.status_code == 403
    assert len(forwarded) == 1 and forwarded[0][1] == payload
    assert forwarded[0][0] != request_id


@pytest.mark.asyncio
@pytest.mark.parametrize("method", sorted(READS))
async def test_account_read_proxy_keeps_exact_wire_and_bounded_new_nonce_retry(modules, method):
    calls = []
    payload = {"product_id": "b62", "canonical_subject_id": "sub_synthetic_transport"}
    if method.endswith("_device"):
        payload["device_id"] = "fixture-device"
    answer = {"ok": True, "fixture": "canonical-response"}

    def sender(url, body, headers):
        calls.append((url, json.loads(body), headers[modules.proof.SERVICE_ID_HEADER]))
        if len(calls) == 1:
            raise modules.proxy.IdentityRpcReplayRefused("fixture replay refusal")
        return answer

    proxy = modules.proxy.IdentityDoProxy("https://identity.example.invalid", SECRET, sender=sender)
    assert await getattr(proxy, method)(payload) is answer
    assert len(calls) == 2 and calls[0][2] != calls[1][2]
    assert all(url.endswith("/internal/rpc/" + method) and body == payload for url, body, _ in calls)
    with pytest.raises(AttributeError):
        getattr(proxy, "unreviewed_account_mutation")
