"""P5-D: the PC bundle answers its connector reads per the account-key mode.

Off answers the session key exactly as today; shadow answers the session key
and only records the comparison; key answers the account key built from this
request's verified proof alone. Absent or expired proof refuses with the same
401 an absent session gets, and closed authority codes surface unchanged.
"""
import asyncio
import time
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from padiem_control_plane import CanonicalSubjectRef, SubjectType
from padiem_control_plane.auth_sessions import AuthSessionSnapshot
from starlette.requests import Request

from app import connector_account_shadow as shadow
from app import connector_account_subject as proof
from app.config import ConfigError, Settings
from app.control_plane_identity import IdentityBridgeError
from app.control_plane_identity_worker import CloudflareControlPlaneIdentityAuthority
from app.identity_call_cache import CachedIdentityAuthority
from app.shared_auth_adapter import SharedChatAuth

PRIVATE = "sub_private_account_fixture"
SID = "private-session-fixture"
TENANT = "private-tenant-fixture"
NOW = datetime.now(UTC)
SESSION = AuthSessionSnapshot(session_id=SID, product_id="b62",
    subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id=PRIVATE),
    issued_at=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(minutes=10), tenant_id=TENANT)
BASELINE = {
    "owner_scope": {"account_ref": "private-account-scope", "workspace_ref": "private-workspace", "owner_subject_id": PRIVATE},
    "consent": {"consent_id": "private-consent", "device_id": "private-device", "owner_subject_id": PRIVATE,
                "account_ref": "private-account-scope", "workspace_ref": "private-workspace",
                "granted_at": NOW.isoformat(), "withdrawn_at": None},
}


class Binding:
    _timeout = .03

    def __init__(self):
        self.calls = []
        self.alternate = deepcopy(BASELINE)
        self.original = deepcopy(BASELINE)
        self.tenants = [TENANT]
        self.error = None
        self.session_error = None
        self.wait = None
        self.started = asyncio.Event()
        self.session = SESSION
        self.session_wait = None

    def __getattr__(self, name):
        async def call(payload):
            self.calls.append((name, deepcopy(payload)))
            if name in {"resolve_auth_session", "resolve_current_auth_session"}:
                return {"ok": True, "session": self.session.to_public_dict()}
            if name == "resolve_product_user_for_subject":
                return {"ok": True, "product_user_id": "usr_fixture"}
            if name == "resolve_active_memberships":
                return {"ok": True, "tenant_ids": self.tenants}
            for kind, (account_name, field) in shadow.ACCOUNT_READS.items():
                if kind not in ("owner_scope", "consent"):
                    continue
                account = name == account_name
                if account or name == ("resolve_connector_owner_scope" if kind == "owner_scope"
                                        else "resolve_connector_enrollment_consent_for_device"):
                    if account:
                        self.started.set()
                        if self.wait is not None:
                            await self.wait()
                        if isinstance(self.error, BaseException):
                            raise self.error
                        if self.error is not None:
                            return deepcopy(self.error)
                    elif self.session_error is not None:
                        return {"ok": False, "error": {"code": self.session_error, "message": "unavailable"}}
                    elif self.session_wait is not None:
                        await self.session_wait()
                    return {"ok": True, field: deepcopy((self.alternate if account else self.original)[kind])}
            raise AssertionError("unexpected_fixture_rpc")
        return call


class Verifier:
    def verify(self, _token):
        return {"accountId": PRIVATE, "sessionId": "private-shared-session", "expiresAt": int(time.time()) + 600}


class NoAccountVerifier:
    def verify(self, _token):
        return {"sessionId": "private-shared-session", "expiresAt": int(time.time()) + 600}


async def in_request(binding, callback, *, enabled=True, key_mode=False, cache=False, verifier=None,
                   tolerate_auth_failure=False):
    authority = CloudflareControlPlaneIdentityAuthority(binding)
    authority = CachedIdentityAuthority(authority) if cache else authority
    auth = SharedChatAuth(verifier=verifier or Verifier(), authority=authority, legacy=lambda _r: None)
    state = SimpleNamespace(auth_validation_cache=None, settings=Settings())
    scope = {"type": "http", "path": "/fixture", "headers": [], "app": SimpleNamespace(state=state)}
    request = Request(scope)

    from app.shared_auth_adapter import SharedAuthUnavailable

    async def app(scope, _receive, _send):
        try:
            await auth.user_id(request, "synthetic-signed-access")
        except SharedAuthUnavailable:
            assert tolerate_auth_failure, "test forgot to declare a failing verification"
        await authority.resolve_current_auth_session(product_id="b62", product_user_id="usr_fixture")
        await callback(authority, request)

    if enabled:
        await proof.ConnectorAccountShadowContextMiddleware(app, key_mode=key_mode)(scope, None, None)
    else:
        await app(scope, None, None)
    assert proof.shadow_context_enabled() is False
    assert proof.account_key_mode_enabled() is False
    return authority


async def settled():
    for _ in range(20):
        tasks = tuple(shadow._BACKGROUND)
        if not tasks:
            return
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.sleep(0)
    assert not shadow._BACKGROUND


async def read(authority, kind, *, session_id=SID):
    kwargs = {"session_id": session_id}
    if kind == "consent":
        kwargs["device_id"] = "private-device"
    return await shadow.pc_connector_read(authority, kind, **kwargs)


ACCOUNT_RPC = {"owner_scope": "resolve_connector_owner_scope_for_subject",
               "consent": "resolve_connector_enrollment_consent_for_subject_device"}
SESSION_RPC = {"owner_scope": "resolve_connector_owner_scope",
               "consent": "resolve_connector_enrollment_consent_for_device"}


@pytest.mark.parametrize("kind", ("owner_scope", "consent"))
async def test_off_answers_the_session_key_and_calls_no_account_rpc(kind, capsys):
    binding = Binding()
    answers = []

    async def call(authority, _request):
        answers.append(await read(authority, kind))

    await in_request(binding, call, enabled=False)
    await settled()
    assert answers[0] == BASELINE[kind]
    assert [name for name, _ in binding.calls] == [
        "resolve_product_user_for_subject", "resolve_current_auth_session", SESSION_RPC[kind]]
    assert "connector_account_shadow" not in capsys.readouterr().out


@pytest.mark.parametrize("kind", ("owner_scope", "consent"))
async def test_shadow_answers_the_session_key_and_records_only_the_comparison(kind, capsys):
    binding = Binding()
    binding.alternate[kind]["workspace_ref"] = "private-account-workspace"
    answers = []

    async def call(authority, _request):
        answers.append(await read(authority, kind))

    await in_request(binding, call)
    await settled()
    assert answers[0] == BASELINE[kind]
    assert capsys.readouterr().out.splitlines() == ["connector_account_shadow method=" + kind + " reason=scope_mismatch"]


@pytest.mark.parametrize("kind", ("owner_scope", "consent"))
async def test_key_answers_the_account_key_and_never_reads_the_session_key(kind, capsys):
    binding = Binding()
    binding.alternate[kind]["workspace_ref"] = "private-account-workspace"
    answers = []

    async def call(authority, _request):
        answers.append(await read(authority, kind))

    await in_request(binding, call, key_mode=True)
    await settled()
    assert answers[0] == {**BASELINE[kind], "workspace_ref": "private-account-workspace"}
    names = [name for name, _ in binding.calls]
    assert ACCOUNT_RPC[kind] in names
    assert SESSION_RPC[kind] not in names
    sent = next(payload for name, payload in binding.calls if name == ACCOUNT_RPC[kind])
    expected = {"product_id": "b62", "canonical_subject_id": PRIVATE}
    if kind == "consent":
        expected["device_id"] = "private-device"
    assert sent == expected
    assert "connector_account_shadow" not in capsys.readouterr().out


async def test_key_mode_bypasses_the_session_key_cache():
    binding = Binding()

    async def call(authority, _request):
        answer = await shadow.pc_connector_read(authority, "owner_scope", session_id=SID)
        assert answer == BASELINE["owner_scope"]

    authority = await in_request(binding, call, key_mode=True, cache=True)
    await settled()
    assert not any(key.startswith("ownerscope:") for key in authority._entries)


async def test_off_mode_through_the_cache_still_uses_the_session_cache():
    binding = Binding()

    async def call(authority, _request):
        answer = await shadow.pc_connector_read(authority, "owner_scope", session_id=SID)
        assert answer == BASELINE["owner_scope"]

    authority = await in_request(binding, call, enabled=False, cache=True)
    assert any(key.startswith("ownerscope:") for key in authority._entries)


async def test_key_mode_expired_verified_proof_refuses_like_an_expired_session():
    binding = Binding()

    async def call(authority, _request):
        with pytest.raises(IdentityBridgeError) as caught:
            await shadow.pc_connector_read(authority, "owner_scope", session_id=SID)
        assert caught.value.code == "canonical_auth_session_not_found"
        assert caught.value.status_code == 401

    class StaleVerifier:
        def verify(self, _token):
            return {"accountId": PRIVATE, "sessionId": "private-shared-session", "expiresAt": int(time.time()) - 1}

    await in_request(binding, call, key_mode=True, verifier=StaleVerifier(), tolerate_auth_failure=True)
    assert ACCOUNT_RPC["owner_scope"] not in [name for name, _ in binding.calls]


async def test_key_mode_without_verified_proof_refuses_like_an_absent_session():
    binding = Binding()

    async def call(authority, _request):
        with pytest.raises(IdentityBridgeError) as caught:
            await shadow.pc_connector_read(authority, "owner_scope", session_id=SID)
        assert caught.value.code == "canonical_auth_session_not_found"
        assert caught.value.status_code == 401

    await in_request(binding, call, key_mode=True, verifier=NoAccountVerifier(), tolerate_auth_failure=True)
    assert ACCOUNT_RPC["owner_scope"] not in [name for name, _ in binding.calls]


@pytest.mark.parametrize("kind", ("owner_scope", "consent"))
async def test_key_mode_refuses_an_unremembered_session(kind):
    binding = Binding()

    async def call(authority, _request):
        with pytest.raises(IdentityBridgeError) as caught:
            await shadow.pc_connector_read(authority, kind, session_id="private-other-session",
                                           **({"device_id": "private-device"} if kind == "consent" else {}))
        assert caught.value.code == "canonical_auth_session_not_found"
        assert caught.value.status_code == 401

    await in_request(binding, call, key_mode=True)


@pytest.mark.parametrize("code", ("canonical_subject_deleted", "canonical_tenant_membership_ambiguous"))
async def test_key_mode_surfaces_closed_withdrawal_and_ambiguity_codes(code):
    binding = Binding()
    binding.error = {"ok": False, "error": {"code": code, "message": PRIVATE}}

    async def call(authority, _request):
        with pytest.raises(IdentityBridgeError) as caught:
            await shadow.pc_connector_read(authority, "owner_scope", session_id=SID)
        assert caught.value.code == code
        assert caught.value.status_code == 503
        assert PRIVATE not in repr(caught.value)

    await in_request(binding, call, key_mode=True)


async def test_key_mode_transport_failure_maps_to_unavailable():
    binding = Binding()
    binding.error = RuntimeError(PRIVATE)

    async def call(authority, _request):
        with pytest.raises(IdentityBridgeError) as caught:
            await shadow.pc_connector_read(authority, "owner_scope", session_id=SID)
        assert caught.value.code == "control_plane_identity_unavailable"
        assert caught.value.status_code == 503
        assert PRIVATE not in repr(caught.value)

    await in_request(binding, call, key_mode=True)


async def test_key_mode_malformed_account_answer_maps_to_invalid():
    binding = Binding()
    binding.error = {"ok": True, "scope": {"workspace_ref": "private-workspace", "extra": PRIVATE}}

    async def call(authority, _request):
        with pytest.raises(IdentityBridgeError) as caught:
            await shadow.pc_connector_read(authority, "owner_scope", session_id=SID)
        assert caught.value.code == "control_plane_rpc_invalid"
        assert caught.value.status_code == 503

    await in_request(binding, call, key_mode=True)


async def test_key_mode_missing_account_port_fails_closed():
    binding = Binding()

    async def call(authority, _request):
        authority.resolve_connector_owner_scope_for_subject = None
        try:
            with pytest.raises(IdentityBridgeError) as caught:
                await shadow.pc_connector_read(authority, "owner_scope", session_id=SID)
            assert caught.value.code == "control_plane_identity_unavailable"
            assert caught.value.status_code == 503
        finally:
            del authority.resolve_connector_owner_scope_for_subject

    await in_request(binding, call, key_mode=True)


async def test_off_mode_withdrawn_account_refuses_on_the_session_key():
    binding = Binding()
    binding.session_error = "canonical_subject_deleted"

    async def call(authority, _request):
        with pytest.raises(IdentityBridgeError) as caught:
            await shadow.pc_connector_read(authority, "owner_scope", session_id=SID)
        assert caught.value.code == "canonical_subject_deleted"

    await in_request(binding, call, enabled=False)


async def test_shadow_failure_never_changes_the_pc_answer(capsys):
    binding = Binding()
    binding.error = RuntimeError(PRIVATE)

    async def call(authority, _request):
        assert await shadow.pc_connector_read(authority, "owner_scope", session_id=SID) == BASELINE["owner_scope"]

    await in_request(binding, call)
    await settled()
    assert capsys.readouterr().out.splitlines() == ["connector_account_shadow method=owner_scope reason=account_unavailable"]


async def test_slow_shadow_never_holds_the_pc_response(capsys):
    binding = Binding()
    release = asyncio.Event()

    async def stubborn():
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()

    binding.wait = stubborn

    async def call(authority, _request):
        assert await shadow.pc_connector_read(authority, "owner_scope", session_id=SID) == BASELINE["owner_scope"]
        assert not binding.started.is_set(), "comparison starts after the existing response path returns"

    await in_request(binding, call)
    await binding.started.wait()
    await asyncio.sleep(.06)
    assert "reason=timeout" in capsys.readouterr().out
    release.set()
    await settled()


async def test_key_mode_outside_a_request_context_keeps_the_session_answer():
    # Non-HTTP callers have no proof context; the helper must not invent key
    # mode from nothing.
    binding = Binding()
    authority = CloudflareControlPlaneIdentityAuthority(binding)
    assert proof.account_key_mode_enabled() is False
    answer = await shadow.pc_connector_read(authority, "owner_scope", session_id=SID)
    assert answer == BASELINE["owner_scope"]
    assert ACCOUNT_RPC["owner_scope"] not in [name for name, _ in binding.calls]


async def test_helper_rejects_a_non_pc_method():
    binding = Binding()
    authority = CloudflareControlPlaneIdentityAuthority(binding)
    with pytest.raises(ValueError, match="pc_connector_read_method_invalid"):
        await shadow.pc_connector_read(authority, "workspace", session_id=SID)
    assert not binding.calls


def test_key_mode_setting_default_off_and_projects_through_host_and_worker(monkeypatch):
    from app.worker_config import settings_from_worker_bindings
    assert Settings().connector_account_key_enabled is False
    assert Settings.from_values().connector_account_key_enabled is False
    monkeypatch.delenv("PADIEM_CHAT_CONNECTOR_ACCOUNT_KEY_ENABLED", raising=False)
    assert Settings.from_env().connector_account_key_enabled is False
    monkeypatch.setenv("PADIEM_CHAT_CONNECTOR_ACCOUNT_KEY_ENABLED", "true")
    assert Settings.from_env().connector_account_key_enabled is True
    monkeypatch.setenv("PADIEM_CHAT_CONNECTOR_ACCOUNT_KEY_ENABLED", "maybe")
    with pytest.raises(ConfigError):
        Settings.from_env()
    monkeypatch.delenv("PADIEM_CHAT_CONNECTOR_ACCOUNT_KEY_ENABLED", raising=False)
    assert settings_from_worker_bindings(SimpleNamespace(PADIEM_CHAT_CONNECTOR_ACCOUNT_KEY_ENABLED="true")).connector_account_key_enabled is True


async def test_middleware_carries_the_key_mode_flag():
    binding = Binding()
    seen = []

    async def call(_authority, _request):
        seen.append(proof.account_key_mode_enabled())
        assert await shadow.pc_connector_read(_authority, "owner_scope", session_id=SID)

    await in_request(binding, call, key_mode=True)
    assert seen == [True]
