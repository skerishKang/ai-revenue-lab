"""Real product-owner browser setup: active B54 session, exact routes, no cache."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx

from app import connector_owner_setup_page as setup
from app.app_factory import create_app
from app.config import Settings
from app.connector_owner_runtime_mount import compose_owner_enrollment_from_worker
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType
from app.worker_config import (
    IDENTITY_AUTHORITY_SERVICE_BINDING_NAME as I,
    LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME as B,
)


class PrivateBinding:
    def __getattr__(self, name):
        if name in {
            "grant_connector_enrollment_consent", "revoke_connector_enrollment_consent",
            "resolve_connector_enrollment_consent_for_device",
            "bind_connector_enrollment_challenge", "authorize_connector_enrollment_redeem",
            "issue_enrollment_challenge", "get_enrollment_binding",
            "verify_enrollment_bootstrap", "redeem_enrollment", "revoke_binding",
        }:
            async def placeholder(*args, **kwargs):
                raise AssertionError("no private RPC in GET page")
            return placeholder
        raise AttributeError(name)


def app():
    env = {
        "PADIEM_CONNECTOR_OWNER_ENROLLMENT_ENABLED": "enabled",
        "PADIEM_CONNECTOR_GATEWAY_RELEASE_SCOPE": "isolated-operator-acceptance-4139",
        I: PrivateBinding(), B: PrivateBinding(),
    }
    settings = replace(Settings.from_env(), public_base_url="https://chat.padiem.net")
    return create_app(settings=settings, connector_owner_enrollment=compose_owner_enrollment_from_worker(env))


def get(application, path):
    async def call():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="https://chat.padiem.net",
        ) as client:
            return await client.get(path)
    return asyncio.run(call())


def signed():
    now = datetime.now(timezone.utc)
    return AuthSessionSnapshot(
        session_id="session.owner.1", product_id="b54-padiem-claw",
        subject=CanonicalSubjectRef(
            subject_type=SubjectType.USER, subject_id="canonical.owner.1",
        ),
        issued_at=now-timedelta(minutes=1),
        expires_at=now+timedelta(hours=1),
        state=AuthSessionState.ACTIVE, tenant_id="tenant.1",
    )


def test_browser_setup_requires_canonical_signed_owner(monkeypatch):
    application = app()
    assert get(application, setup.SETUP_PATH).status_code == 401
    monkeypatch.setattr(setup, "auth_ready", lambda request: True)
    monkeypatch.setattr(setup, "current_user_id", lambda request: "product.owner.1")
    async def other(request):
        return SimpleNamespace(product_user_id="product.owner.2", auth_session=signed())
    monkeypatch.setattr(setup, "resolve_current_b54_canonical_session", other)
    assert get(application, setup.SETUP_PATH).status_code == 401

    async def verified(request):
        return SimpleNamespace(product_user_id="product.owner.1", auth_session=signed())
    monkeypatch.setattr(setup, "resolve_current_b54_canonical_session", verified)
    response = get(application, setup.SETUP_PATH)
    assert response.status_code == 200
    assert "PADIEM Connector" in response.text
    assert "setup.js" in response.text
    assert 'id="verify" disabled' in response.text
    assert response.headers["cache-control"].startswith("no-store")
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_script_does_not_persist_pairing_code_or_use_untrusted_owner_scope():
    application = app()
    script = get(application, setup.SCRIPT_PATH)
    assert script.status_code == 200
    assert script.headers["cache-control"].startswith("no-store")
    assert "localStorage.setItem" not in script.text
    assert "sessionStorage" not in script.text
    assert "console.log" not in script.text
    assert "navigator.clipboard" not in script.text
    assert "credentials: \"same-origin\"" in script.text
    assert "consent/grant" in script.text and "enrollments/issue" in script.text
    assert "enrollments/redeem" not in script.text
    assert "pagehide" in script.text
    assert "/api/claw/local-access/devices" in script.text
    assert "ownerScoped" in script.text
    assert 'matched.state === "OFFLINE"' in script.text
    assert 'matched.state === "CONNECTED"' in script.text
    assert "verify.disabled" in script.text


def test_default_product_app_has_no_setup_page_or_script():
    ordinary = create_app(settings=replace(Settings.from_env(), public_base_url="https://chat.padiem.net"))
    assert not any(getattr(r, "path", "") in {setup.SETUP_PATH, setup.SCRIPT_PATH} for r in ordinary.routes)


def test_signed_owner_page_has_single_native_launch_not_an_account_login():
    # The page is still owner-session gated by the existing tests above.
    assert 'id="native-launch"' in setup._HTML
    assert 'id="operator-restore"' in setup._HTML
    assert setup._HTML.index('id="native-launch"') < setup._HTML.index('id="operator-restore"')
    assert 'padiem-connector://start' in setup._SCRIPT
    assert '"padiem-connector://start"' in setup._SCRIPT
    assert 'location.href' in setup._SCRIPT
    assert 'padiem-connector://start?' not in setup._SCRIPT
    assert 'padiem-connector://start#' not in setup._SCRIPT
    assert 'id="secret" hidden' in setup._HTML
    assert '"enrollments/redeem"' not in setup._SCRIPT
    assert "navigator.clipboard" not in setup._SCRIPT
    assert "localStorage.setItem" not in setup._SCRIPT


def test_native_browser_launch_script_has_real_javascript_syntax_if_node_available():
    import shutil
    import subprocess
    import pytest

    if shutil.which("node") is None:
        pytest.skip("Node not present; script syntax checked in Node-enabled CI")
    process = subprocess.run(
        ["node", "--check"], input=setup._SCRIPT, text=True,
        capture_output=True, timeout=15, check=False,
    )
    assert process.returncode == 0, process.stderr


def test_one_click_owner_ui_requires_explicit_click_and_nonsecret_exact_offer_ref():
    """Node exercises real setup.js interactions without browser credentials."""
    import json
    import shutil
    import subprocess
    import pytest

    if shutil.which("node") is None:
        pytest.skip("Node unavailable; browser script behavior covered on CI")

    script = r"""
const fs=require('node:fs');
const assert=require('node:assert/strict');
const source=fs.readFileSync(0,'utf8');
const hooks={};
const fields={};
function field(id){
  if(!fields[id]){
    fields[id]={
      checked:false,disabled:true,hidden:id==='pending-pc',
      value:'',textContent:'',
      addEventListener(event, fn){hooks[id+':'+event]=fn;},
    };
  }
  return fields[id];
}
const ref='link.'+'a'.repeat(32);
let calls=[];
globalThis.document={getElementById:field};
globalThis.window={
  location:{href:'https://chat.padiem.net/api/claw/connector/enrollments/setup?request_ref='+ref},
  addEventListener(){},
};
globalThis.fetch=async (url,options)=>{
  calls.push({url, options});
  return {
    ok:true, json:async()=>({
      ok:true,state:'awaiting_device_confirmation',device_id:'windows.device.1',
      registered:false,connected:false,dispatch_authorized:false,
    }),
  };
};
eval(source);
(async()=>{
  assert.equal(field('pending-pc').hidden,false);
  assert.equal(calls.length,0,'must not POST on page load');
  await hooks['pending-approve:click']();
  assert.equal(calls.length,0,'must not POST without explicit consent');
  field('pending-consent').checked=true;
  hooks['pending-consent:change']();
  assert.equal(field('pending-approve').disabled,false);
  await hooks['pending-approve:click']();
  assert.equal(calls.length,1);
  assert.equal(calls[0].url,'/api/claw/connector/enrollments/approve-link');
  assert.deepEqual(JSON.parse(calls[0].options.body),{
    request_ref:ref,confirmed:true,confirmation_version:'pc-enrollment-consent-v1'
  });
  assert.equal(calls[0].options.credentials,'same-origin');
  assert.equal(calls[0].options.redirect,'error');
  assert.equal(field('pending-approve').disabled,true);
  await hooks['pending-approve:click']();
  assert.equal(calls.length,1,'cannot auto retry one-use approval');
  assert.ok(!field('pending-state').textContent.includes('연결 완료'));
})().catch(e=>{process.stderr.write(String(e.stack));process.exitCode=1;});
"""
    result = subprocess.run(
        ["node", "-e", script], input=setup._SCRIPT,
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_one_click_owner_ui_contains_no_automatic_authorization_or_url_secret():
    # Browser launches only with a nonsecret referral reference from the
    # already-verified outbound PC socket; no hidden grants on page load.
    assert 'id="pending-pc" hidden' in setup._HTML
    assert 'id="pending-approve" disabled' in setup._HTML
    assert 'id="pending-consent" type="checkbox"' in setup._HTML
    assert 'query.size === 1' in setup._SCRIPT
    assert 'pendingConsent.checked' in setup._SCRIPT
    assert '"awaiting_device_confirmation"' in setup._SCRIPT
    assert 'reply.connected !== false' in setup._SCRIPT
    assert 'reply.registered !== false' in setup._SCRIPT
    assert '/api/claw/connector/enrollments/approve-link' in setup._SCRIPT
    assert 'padiem-connector://start?' not in setup._SCRIPT
    assert 'localStorage.setItem' not in setup._SCRIPT
