"""P5-F: enrollment consent grant answers per the account-key mode.

Off answers the session key exactly as today; shadow answers the session key,
grants exactly once, and only records a read-only account read-back comparison
(never a second grant); key answers the account key built from this request's
verified proof alone. Absent or expired proof refuses with the same 401 an
absent session gets, and closed authority codes surface unchanged. The
challenge bind/authorize pair and the revoke are not in this bundle; they stay
session-keyed in every mode (see the report).
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
from app.config import Settings
from app.control_plane_identity import IdentityBridgeError
from app.control_plane_identity_worker import CloudflareControlPlaneIdentityAuthority
from app.shared_auth_adapter import SharedChatAuth

PRIVATE = "sub_private_account_fixture"
OTHER_PRIVATE = "sub_private_other_fixture"
SID = "private-session-fixture"
TENANT = "private-tenant-fixture"
DEVICE = "private-device"
NOW = datetime.now(UTC)
SESSION = AuthSessionSnapshot(session_id=SID, product_id="b62",
    subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id=PRIVATE),
    issued_at=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(minutes=10), tenant_id=TENANT)
CONSENT = {"consent_id": "private-consent", "device_id": DEVICE, "owner_subject_id": PRIVATE,
    "account_ref": "private-account-scope", "workspace_ref": "private-workspace",
    "granted_at": NOW.isoformat(), "withdrawn_at": None}
GRANT = {"consent_id": "private-consent", "device_id": DEVICE,
    "granted_at": NOW.isoformat(), "withdrawn_at": None,
    "dispatch_authorized": False, "grants_read": False, "grants_write": False}
SESSION_GRANT_RPC = "grant_connector_enrollment_consent"
ACCOUNT_GRANT_RPC = "grant_connector_enrollment_consent_for_subject"
ACCOUNT_READ_RPC = "resolve_connector_enrollment_consent_for_subject_device"


class Binding:
    _timeout = .03

    def __init__(self):
        self.calls = []
        self.original = {"consent": deepcopy(CONSENT)}
        self.alternate = {"consent": deepcopy(CONSENT)}
        self.grants = deepcopy(GRANT)
        self.tenants = [TENANT]
        self.error = None
        self.error_rpc = None
        self.session = SESSION

    def __getattr__(self, name):
        async def call(payload):
            self.calls.append((name, deepcopy(payload)))
            if name in {"resolve_auth_session", "resolve_current_auth_session"}:
                return {"ok": True, "session": self.session.to_public_dict()}
            if name == "resolve_product_user_for_subject":
                return {"ok": True, "product_user_id": "usr_fixture"}
            if name == "resolve_active_memberships":
                return {"ok": True, "tenant_ids": self.tenants}
            if name in (SESSION_GRANT_RPC, ACCOUNT_GRANT_RPC):
                if self.error is not None and self.error_rpc == name:
                    if isinstance(self.error, BaseException):
                        raise self.error
                    return deepcopy(self.error)
                return {"ok": True, "consent": deepcopy(self.grants)}
            if name == ACCOUNT_READ_RPC:
                if self.error is not None and self.error_rpc is None:
                    if isinstance(self.error, BaseException):
                        raise self.error
                    return deepcopy(self.error)
                return {"ok": True, "consent": deepcopy(self.alternate["consent"])}
            raise AssertionError("unexpected_fixture_rpc")
        return call


class Verifier:
    def verify(self, _token):
        return {"accountId": PRIVATE, "sessionId": "private-shared-session", "expiresAt": int(time.time()) + 600}


class NoAccountVerifier:
    def verify(self, _token):
        return {"sessionId": "private-shared-session", "expiresAt": int(time.time()) + 600}


class ExpiredVerifier:
    def verify(self, _token):
        return {"accountId": PRIVATE, "sessionId": "private-shared-session", "expiresAt": int(time.time()) - 10}


async def in_request(binding, callback, *, enabled=True, key_mode=False, verifier=None,
                   tolerate_auth_failure=False):
    authority = CloudflareControlPlaneIdentityAuthority(binding)
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


def grants(binding):
    return [c for c in binding.calls if c[0] in (SESSION_GRANT_RPC, ACCOUNT_GRANT_RPC)]


def write_rpcs(binding, key=None):
    return [c for c in binding.calls if c[0] == ACCOUNT_GRANT_RPC]


async def grant(authority, *, confirmed=True, version="pc-enrollment-consent-v1", session_id=SID):
    return await shadow.mode_grant_consent(
        authority, session_id=session_id, device_id=DEVICE,
        confirmed=confirmed, confirmation_version=version,
    )


async def test_off_answers_the_session_grant_exactly_as_today():
    binding = Binding()
    answers = []

    async def call(authority, _request):
        answers.append(await grant(authority))

    await in_request(binding, call, enabled=False)
    await settled()
    assert answers[0] == GRANT
    assert [c[0] for c in grants(binding)] == [SESSION_GRANT_RPC]
    assert not write_rpcs(binding)


async def test_shadow_grants_exactly_once_and_reads_back(capsys):
    binding = Binding()
    answers = []

    async def call(authority, _request):
        answers.append(await grant(authority))

    await in_request(binding, call)
    await settled()
    assert answers[0] == GRANT
    # Exactly one write, and it is the session-key grant: the shadow comparison
    # is a read-back only (consent read + memberships), never a second grant.
    assert [c[0] for c in grants(binding)] == [SESSION_GRANT_RPC]
    assert [c[0] for c in binding.calls if c[0] == ACCOUNT_GRANT_RPC] == []
    assert any(c[0] == ACCOUNT_READ_RPC for c in binding.calls)
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert lines[0] == "connector_account_shadow method=grant reason=match latency=lt100ms"
    assert all(s not in lines[0] for s in (PRIVATE, SID, TENANT, DEVICE))


async def test_shadow_read_back_mismatch_is_recorded(capsys):
    binding = Binding()
    binding.alternate["consent"] = dict(CONSENT, consent_id="private-other-consent")
    answers = []

    async def call(authority, _request):
        answers.append(await grant(authority))

    await in_request(binding, call)
    await settled()
    assert answers[0] == GRANT
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert lines[0] == "connector_account_shadow method=grant reason=scope_mismatch latency=lt100ms"


async def test_shadow_read_back_outage_is_recorded(capsys):
    binding = Binding()
    binding.error = RuntimeError("unavailable")

    async def call(authority, _request):
        answers = await grant(authority)
        assert answers == GRANT

    await in_request(binding, call)
    await settled()
    assert [c[0] for c in grants(binding)] == [SESSION_GRANT_RPC]
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert lines[0] == "connector_account_shadow method=grant reason=account_unavailable latency=lt100ms"


async def test_key_answers_the_account_grant_alone():
    binding = Binding()
    answers = []

    async def call(authority, _request):
        answers.append(await grant(authority))

    await in_request(binding, call, key_mode=True)
    await settled()
    assert answers[0] == GRANT
    assert [c[0] for c in grants(binding)] == [ACCOUNT_GRANT_RPC]
    (_name, payload), = [c for c in binding.calls if c[0] == ACCOUNT_GRANT_RPC]
    # The subject comes from the request proof alone: the caller names device
    # and confirmation only, so no request value can select another account.
    assert payload == {"product_id": "b62", "canonical_subject_id": PRIVATE, "device_id": DEVICE,
                       "confirmed": True, "confirmation_version": "pc-enrollment-consent-v1"}


async def test_key_subject_cannot_be_named_by_the_caller():
    binding = Binding()
    # The request proof is this account only; a session that resolves to a
    # different account must never substitute for the verified subject.
    binding.session = AuthSessionSnapshot(session_id=SID, product_id="b62",
        subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id=OTHER_PRIVATE),
        issued_at=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(minutes=10), tenant_id=TENANT)

    async def call(authority, _request):
        with pytest.raises(IdentityBridgeError) as caught:
            await grant(authority)
        assert caught.value.code == "canonical_auth_session_not_found"
        assert caught.value.status_code == 401

    await in_request(binding, call, key_mode=True)
    await settled()
    assert not grants(binding)


async def test_key_without_verified_proof_refuses_with_the_session_401():
    binding = Binding()

    async def call(authority, _request):
        with pytest.raises(IdentityBridgeError) as caught:
            await grant(authority)
        assert caught.value.code == "canonical_auth_session_not_found"
        assert caught.value.status_code == 401

    await in_request(binding, call, key_mode=True, verifier=NoAccountVerifier(), tolerate_auth_failure=True)
    await settled()
    assert not grants(binding)


async def test_key_with_expired_proof_refuses_with_the_session_401():
    binding = Binding()

    async def call(authority, _request):
        with pytest.raises(IdentityBridgeError) as caught:
            await grant(authority)
        assert caught.value.code == "canonical_auth_session_not_found"
        assert caught.value.status_code == 401

    await in_request(binding, call, key_mode=True, verifier=ExpiredVerifier(), tolerate_auth_failure=True)
    await settled()
    assert not grants(binding)


async def test_key_blocks_a_withdrawn_account():
    binding = Binding()
    binding.error = {"ok": False, "error": {"code": "canonical_subject_deleted", "message": PRIVATE}}
    binding.error_rpc = ACCOUNT_GRANT_RPC

    async def call(authority, _request):
        with pytest.raises(IdentityBridgeError) as caught:
            await grant(authority)
        assert caught.value.code == "canonical_subject_deleted"
        assert caught.value.status_code == 503
        assert PRIVATE not in repr(caught.value)

    await in_request(binding, call, key_mode=True)
    await settled()
    assert [c[0] for c in grants(binding)] == [ACCOUNT_GRANT_RPC]


async def test_key_transport_failure_is_unavailable():
    binding = Binding()
    binding.error = RuntimeError("boom")
    binding.error_rpc = ACCOUNT_GRANT_RPC

    async def call(authority, _request):
        with pytest.raises(IdentityBridgeError) as caught:
            await grant(authority)
        assert caught.value.code == "control_plane_identity_unavailable"
        assert caught.value.status_code == 503

    await in_request(binding, call, key_mode=True)
    await settled()


async def test_key_malformed_answer_is_invalid():
    binding = Binding()
    binding.grants = dict(GRANT, consent_id="")

    async def call(authority, _request):
        with pytest.raises(IdentityBridgeError) as caught:
            await grant(authority)
        assert caught.value.code == "control_plane_rpc_invalid"
        assert caught.value.status_code == 503

    await in_request(binding, call, key_mode=True)
    await settled()


async def test_key_blocks_an_unremembered_foreign_session():
    binding = Binding()

    async def call(authority, _request):
        with pytest.raises(IdentityBridgeError) as caught:
            await shadow.mode_grant_consent(
                authority, session_id="private-foreign-session", device_id=DEVICE,
                confirmed=True, confirmation_version="pc-enrollment-consent-v1")
        assert caught.value.code == "canonical_auth_session_not_found"
        assert caught.value.status_code == 401

    await in_request(binding, call, key_mode=True)
    await settled()
    assert not grants(binding)


@pytest.mark.parametrize("confirmed,version", [
    (False, "pc-enrollment-consent-v1"), (True, "other-version"), (True, None),
])
async def test_falsy_confirmation_is_refused_before_any_rpc(confirmed, version):
    for key_mode in (False, True):
        binding = Binding()

        async def call(authority, _request):
            with pytest.raises(IdentityBridgeError) as caught:
                await shadow.mode_grant_consent(
                    authority, session_id=SID, device_id=DEVICE,
                    confirmed=confirmed, confirmation_version=version)
            assert caught.value.code == "connector_enrollment_explicit_consent_required"
            assert caught.value.status_code == 403

        await in_request(binding, call, key_mode=key_mode)
        await settled()
        assert not grants(binding)


async def test_the_android_ui_version_refuses_in_all_three_modes():
    """#7732: the Android app has no consent screen or reviewed text yet, so
    its version is outside the reviewed set — every switch mode refuses the
    grant before any RPC, exactly as an unknown version does."""
    for enabled, key_mode in ((False, False), (True, False), (True, True)):
        binding = Binding()

        async def call(authority, _request):
            with pytest.raises(IdentityBridgeError) as caught:
                await grant(authority, version="android-enrollment-consent-v1")
            assert caught.value.code == "connector_enrollment_explicit_consent_required"
            assert caught.value.status_code == 403

        await in_request(binding, call, enabled=enabled, key_mode=key_mode)
        await settled()
        assert not grants(binding)
