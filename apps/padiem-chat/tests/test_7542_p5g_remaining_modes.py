"""P5-G: bind/authorize pair, consent revoke, and the remaining call sites.

Off answers the session key exactly as today; shadow answers the session key
and never performs an account-side write (the comparison is only a recorded
consent read-back for the grant; the bind/authorize/revoke journal nothing
because an account bind or consume there would be a premature mutation);
key answers the account key built from this request's verified proof alone.

The bind and the consuming authorize move together, so the challenge can
always be found: a session-bound challenge cannot be found by the account
authorize and vice versa. The redeem race checks after the consuming
authorize only re-read the consent under the account key and never consume
the challenge a second time. Absent, expired or foreign proof refuses a
write with the same 401 an absent session gets, and closed authority codes
surface unchanged (a withdrawn subject refuses every account-key write with
``canonical_subject_deleted``).
"""
import asyncio
import time
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from app import connector_account_shadow as shadow
from app import connector_account_subject as proof
from app import pc_work_context as pc_scope_context
from app.canonical_connector_credential_handoff import (
    INSTALL_ACK_TRANSCRIPT_VERSION,
    DeviceCredentialInstallAck,
    installation_proof,
)
from app.canonical_connector_enrollment_async_host import (
    CanonicalConnectorEnrollmentAsyncHost,
)
from app.config import Settings
from app.control_plane_identity import IdentityBridgeError
from app.control_plane_identity_worker import CloudflareControlPlaneIdentityAuthority
from app.shared_auth_adapter import SharedChatAuth
from padiem_control_plane import CanonicalSubjectRef, SubjectType
from padiem_control_plane.auth_sessions import AuthSessionSnapshot
from starlette.requests import Request

PRIVATE = "sub_private_account_fixture"
OTHER_PRIVATE = "sub_private_other_fixture"
SID = "private-session-fixture"
TENANT = "private-tenant-fixture"
DEVICE = "private-device"
CHALLENGE = "pairing." + "a" * 32
CONSENT_ID = "private-consent"
NOW = datetime.now(UTC)
SESSION = AuthSessionSnapshot(session_id=SID, product_id="b62",
    subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id=PRIVATE),
    issued_at=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(minutes=10), tenant_id=TENANT)
CONSENT = {"consent_id": CONSENT_ID, "device_id": DEVICE, "owner_subject_id": PRIVATE,
    "account_ref": "private-account-scope", "workspace_ref": "private-workspace",
    "granted_at": NOW.isoformat(), "withdrawn_at": None}
REVOKED = {"consent_id": CONSENT_ID, "device_id": DEVICE,
    "granted_at": NOW.isoformat(), "withdrawn_at": NOW.isoformat(),
    "dispatch_authorized": False, "grants_read": False, "grants_write": False}
AUTHORIZED = {"challenge_id": CHALLENGE, "consent_id": CONSENT_ID, "device_id": DEVICE,
    "owner_subject_id": PRIVATE, "account_ref": "private-account-scope",
    "workspace_ref": "private-workspace", "authorized_at": NOW.isoformat(),
    "dispatch_authorized": False, "grants_read": False, "grants_write": False}
SESSION_BIND_RPC = "bind_connector_enrollment_challenge"
ACCOUNT_BIND_RPC = "bind_connector_enrollment_challenge_for_subject"
SESSION_AUTHORIZE_RPC = "authorize_connector_enrollment_redeem"
ACCOUNT_AUTHORIZE_RPC = "authorize_connector_enrollment_redeem_for_subject"
SESSION_REVOKE_RPC = "revoke_connector_enrollment_consent"
ACCOUNT_REVOKE_RPC = "revoke_connector_enrollment_consent_for_subject"
ACCOUNT_READ_RPC = "resolve_connector_enrollment_consent_for_subject_device"
ACCOUNT_SCOPE_RPC = "resolve_connector_owner_scope_for_subject"


class Binding:
    """Dual-namespace authority: the session-key RPCs (today) and the
    account-key RPCs (key mode), each with its own answer shape."""

    _timeout = .03

    def __init__(self):
        self.calls = []
        self.consent = deepcopy(CONSENT)
        self.error = None
        self.error_rpc = None
        self.tenants = [TENANT]
        self.session = SESSION
        self.account = {}

    def __getattr__(self, name):
        async def call(payload):
            self.calls.append((name, deepcopy(payload)))
            failure = self._maybe_error(name)
            if failure is not None:
                return deepcopy(failure)
            if name in ("resolve_auth_session", "resolve_current_auth_session"):
                return {"ok": True, "session": self.session.to_public_dict()}
            if name == "resolve_product_user_for_subject":
                return {"ok": True, "product_user_id": "usr_fixture"}
            if name == "resolve_active_memberships":
                return {"ok": True, "tenant_ids": self.tenants}
            if name == SESSION_BIND_RPC:
                return {"ok": True, "binding": {
                    "challenge_id": payload["challenge_id"],
                    "session_id_bound": True,
                    "raw_session_id_returned": False,
                    "expires_at": payload["expires_at"],
                }}
            if name == ACCOUNT_BIND_RPC:
                # The client carries only the challenge id; the authority
                # stamps the challenge row's own expiry (no caller clock).
                return {"ok": True, "binding": {
                    "challenge_id": payload["challenge_id"],
                    "account_bound": True,
                    "expires_at": (NOW + timedelta(minutes=10)).isoformat(),
                }}
            if name == SESSION_AUTHORIZE_RPC:
                return {"ok": True, "authorization": {
                    "challenge_id": payload["challenge_id"], "consent_id": payload["consent_id"],
                    "device_id": payload["device_id"], "owner_subject_id": payload["owner_ref"],
                    "account_ref": payload["account_ref"], "workspace_ref": payload["workspace_ref"],
                    "authorized_at": NOW.isoformat(),
                    "dispatch_authorized": False, "grants_read": False, "grants_write": False,
                }}
            if name == ACCOUNT_AUTHORIZE_RPC:
                return {"ok": True, "authorization": {
                    "challenge_id": payload["challenge_id"], "consent_id": payload["consent_id"],
                    "device_id": payload["device_id"], "owner_subject_id": payload["canonical_subject_id"],
                    "account_ref": "private-account-scope", "workspace_ref": "private-workspace",
                    "authorized_at": NOW.isoformat(),
                    "dispatch_authorized": False, "grants_read": False, "grants_write": False,
                }}
            if name == SESSION_REVOKE_RPC:
                return {"ok": True, "consent": deepcopy(REVOKED)}
            if name == ACCOUNT_REVOKE_RPC:
                return {"ok": True, "consent": deepcopy(REVOKED)}
            if name == ACCOUNT_READ_RPC:
                return {"ok": True, "consent": deepcopy(self.consent)}
            if name == "resolve_connector_owner_scope":
                return {"ok": True, "scope": {"account_ref": "private-account-scope",
                    "workspace_ref": "private-workspace", "owner_subject_id": PRIVATE}}
            if name == ACCOUNT_SCOPE_RPC:
                return {"ok": True, "scope": {"account_ref": "private-account-scope",
                    "workspace_ref": "private-workspace", "owner_subject_id": PRIVATE}}
            raise AssertionError("unexpected_fixture_rpc")
        return call

    def _maybe_error(self, name):
        if self.error is not None and (self.error_rpc is None or self.error_rpc == name):
            if isinstance(self.error, BaseException):
                raise self.error
            if isinstance(self.error, dict):
                return self.error
            raise AssertionError("unused")


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
    request.app.state.control_plane_identity_authority = authority
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


def rpc_calls(binding, name):
    return [c for c in binding.calls if c[0] == name]


WRITES = {SESSION_BIND_RPC: 0, ACCOUNT_BIND_RPC: 0, SESSION_AUTHORIZE_RPC: 0,
          ACCOUNT_AUTHORIZE_RPC: 0, SESSION_REVOKE_RPC: 0, ACCOUNT_REVOKE_RPC: 0}


def write_counts(binding):
    return {name: len(rpc_calls(binding, name)) for name in WRITES}


# --- off: everything answers the session key exactly as today --------------


async def test_off_bind_answers_the_session_key_and_never_the_account_key():
    binding = Binding()
    answers = []

    async def call(authority, _request):
        answers.append(await shadow.mode_bind_challenge(
            authority, session_id=SID, challenge_id=CHALLENGE, expires_at="2030-01-01T00:00:00Z"))

    await in_request(binding, call, enabled=False)
    await settled()
    assert answers[0]["session_id_bound"] is True
    assert len(rpc_calls(binding, SESSION_BIND_RPC)) == 1
    assert not rpc_calls(binding, ACCOUNT_BIND_RPC)


async def test_off_authorize_answers_the_session_key_and_never_the_account_key():
    binding = Binding()
    answers = []

    async def call(authority, _request):
        answers.append(await shadow.mode_authorize_redeem(
            authority, session_id=SID, challenge_id=CHALLENGE, consent_id=CONSENT_ID,
            device_id=DEVICE, owner_ref=PRIVATE, account_ref="private-account-scope",
            workspace_ref="private-workspace"))

    await in_request(binding, call, enabled=False)
    await settled()
    assert answers[0]["owner_subject_id"] == PRIVATE
    assert len(rpc_calls(binding, SESSION_AUTHORIZE_RPC)) == 1
    assert not rpc_calls(binding, ACCOUNT_AUTHORIZE_RPC)


async def test_off_recheck_answers_the_session_key_and_never_the_account_key():
    binding = Binding()
    answers = []

    async def call(authority, _request):
        answers.append(await shadow.mode_recheck_challenge(
            authority, session_id=SID, challenge_id=CHALLENGE, consent_id=CONSENT_ID,
            device_id=DEVICE, owner_ref=PRIVATE, account_ref="private-account-scope",
            workspace_ref="private-workspace"))

    await in_request(binding, call, enabled=False)
    await settled()
    assert answers[0]["owner_subject_id"] == PRIVATE
    assert len(rpc_calls(binding, SESSION_AUTHORIZE_RPC)) == 1
    assert not rpc_calls(binding, ACCOUNT_AUTHORIZE_RPC)


async def test_off_revoke_answers_the_session_key_and_never_the_account_key():
    binding = Binding()
    answers = []

    async def call(authority, _request):
        answers.append(await shadow.mode_revoke_consent(
            authority, session_id=SID, consent_id=CONSENT_ID,
            confirmed=True, confirmation_version="pc-enrollment-consent-v1"))

    await in_request(binding, call, enabled=False)
    await settled()
    assert answers[0]["withdrawn_at"] is not None
    assert len(rpc_calls(binding, SESSION_REVOKE_RPC)) == 1
    assert not rpc_calls(binding, ACCOUNT_REVOKE_RPC)


# --- shadow: session key only; the account key never writes -----------------


async def test_shadow_writes_only_via_the_session_key_and_never_via_the_account_key(capsys):
    binding = Binding()
    answers = []

    async def call(authority, _request):
        answers.append(await shadow.mode_bind_challenge(
            authority, session_id=SID, challenge_id=CHALLENGE, expires_at="2030-01-01T00:00:00Z"))
        answers.append(await shadow.mode_revoke_consent(
            authority, session_id=SID, consent_id=CONSENT_ID,
            confirmed=True, confirmation_version="pc-enrollment-consent-v1"))
        answers.append(await shadow.mode_authorize_redeem(
            authority, session_id=SID, challenge_id=CHALLENGE, consent_id=CONSENT_ID,
            device_id=DEVICE, owner_ref=PRIVATE, account_ref="private-account-scope",
            workspace_ref="private-workspace"))
        answers.append(await shadow.mode_recheck_challenge(
            authority, session_id=SID, challenge_id=CHALLENGE, consent_id=CONSENT_ID,
            device_id=DEVICE, owner_ref=PRIVATE, account_ref="private-account-scope",
            workspace_ref="private-workspace"))

    await in_request(binding, call, enabled=True, key_mode=False)
    await settled()
    # Every write happens exactly once and only through the session key; the
    # account-key mutations are never invoked in shadow (they would bind or
    # consume prematurely). The pair has no shadow read-back journal either:
    # only the grant records one, via a consent read-back.
    assert len(rpc_calls(binding, SESSION_BIND_RPC)) == 1
    assert len(rpc_calls(binding, SESSION_REVOKE_RPC)) == 1
    assert len(rpc_calls(binding, SESSION_AUTHORIZE_RPC)) == 2
    for name in (ACCOUNT_BIND_RPC, ACCOUNT_AUTHORIZE_RPC, ACCOUNT_REVOKE_RPC):
        assert not rpc_calls(binding, name), name
    lines = capsys.readouterr().out.splitlines()
    assert lines == [], lines
    assert all(s not in "".join(lines) for s in (PRIVATE, SID, TENANT, DEVICE, CHALLENGE))


# --- key mode: account key only; the pair switches together -----------------


async def test_key_bind_and_authorize_switch_together_off_the_account_key():
    binding = Binding()
    answers = []

    async def call(authority, _request):
        answers.append(await shadow.mode_bind_challenge(
            authority, session_id=SID, challenge_id=CHALLENGE, expires_at="2030-01-01T00:00:00Z"))
        answers.append(await shadow.mode_authorize_redeem(
            authority, session_id=SID, challenge_id=CHALLENGE, consent_id=CONSENT_ID,
            device_id=DEVICE, owner_ref=PRIVATE, account_ref="private-account-scope",
            workspace_ref="private-workspace"))

    await in_request(binding, call, enabled=True, key_mode=True)
    await settled()
    bind_payload = rpc_calls(binding, ACCOUNT_BIND_RPC)[0][1]
    assert bind_payload["canonical_subject_id"] == PRIVATE
    assert bind_payload["challenge_id"] == CHALLENGE
    authorize_payload = rpc_calls(binding, ACCOUNT_AUTHORIZE_RPC)[0][1]
    assert authorize_payload["canonical_subject_id"] == PRIVATE
    assert authorize_payload["challenge_id"] == CHALLENGE
    # No caller-supplied account/workspace ref is an input to the account key.
    for payload in (bind_payload, authorize_payload):
        assert not (set(payload) & {"account_ref", "workspace_ref", "owner_ref"})
    assert answers[0]["account_bound"] is True
    assert answers[1]["owner_subject_id"] == PRIVATE
    # The session key is never used for the pair in key mode.
    assert not rpc_calls(binding, SESSION_BIND_RPC)
    assert not rpc_calls(binding, SESSION_AUTHORIZE_RPC)


async def test_key_recheck_reads_the_consent_and_never_consumes_the_challenge():
    binding = Binding()
    answers = []

    async def call(authority, _request):
        answers.append(await shadow.mode_recheck_challenge(
            authority, session_id=SID, challenge_id=CHALLENGE, consent_id=CONSENT_ID,
            device_id=DEVICE, owner_ref=PRIVATE, account_ref="private-account-scope",
            workspace_ref="private-workspace"))

    await in_request(binding, call, enabled=True, key_mode=True)
    await settled()
    assert answers[0]["owner_subject_id"] == PRIVATE
    assert answers[0]["dispatch_authorized"] is False
    assert len(rpc_calls(binding, ACCOUNT_READ_RPC)) == 1
    # A recheck never invokes the consuming authorize (redeem's race checks).
    assert not rpc_calls(binding, ACCOUNT_AUTHORIZE_RPC)
    assert not rpc_calls(binding, SESSION_AUTHORIZE_RPC)


async def test_key_recheck_refuses_when_the_consent_no_longer_matches():
    binding = Binding()
    binding.consent = dict(CONSENT, consent_id="some-other-private-consent")
    errors = []

    async def call(authority, _request):
        try:
            await shadow.mode_recheck_challenge(
                authority, session_id=SID, challenge_id=CHALLENGE, consent_id=CONSENT_ID,
                device_id=DEVICE, owner_ref=PRIVATE, account_ref="private-account-scope",
                workspace_ref="private-workspace")
        except IdentityBridgeError as error:
            errors.append(error)

    await in_request(binding, call, enabled=True, key_mode=True)
    await settled()
    assert errors and errors[0].code == "enrollment_consent_withdrawn"
    assert errors[0].status_code == 403


async def test_key_revoke_revokes_via_the_account_key_once(capsys):
    binding = Binding()
    answers = []

    async def call(authority, _request):
        answers.append(await shadow.mode_revoke_consent(
            authority, session_id=SID, consent_id=CONSENT_ID,
            confirmed=True, confirmation_version="pc-enrollment-consent-v1"))

    await in_request(binding, call, enabled=True, key_mode=True)
    await settled()
    payload = rpc_calls(binding, ACCOUNT_REVOKE_RPC)[0][1]
    assert payload["canonical_subject_id"] == PRIVATE
    assert payload["consent_id"] == CONSENT_ID
    assert answers[0]["consent_id"] == CONSENT_ID
    assert answers[0]["withdrawn_at"] is not None
    assert not rpc_calls(binding, SESSION_REVOKE_RPC)
    assert capsys.readouterr().out == ""


# --- key mode: proof, denial and shape guards -------------------------------


async def test_key_write_without_the_remembered_session_is_401():
    binding = Binding()
    errors = []

    async def call(authority, _request):
        for run in (
            lambda: shadow.mode_bind_challenge(authority, session_id=SID, challenge_id=CHALLENGE, expires_at="2030-01-01T00:00:00Z"),
            lambda: shadow.mode_authorize_redeem(authority, session_id=SID, challenge_id=CHALLENGE, consent_id=CONSENT_ID, device_id=DEVICE, owner_ref=PRIVATE, account_ref="private-account-scope", workspace_ref="private-workspace"),
            lambda: shadow.mode_revoke_consent(authority, session_id=SID, consent_id=CONSENT_ID, confirmed=True, confirmation_version="pc-enrollment-consent-v1"),
        ):
            try:
                await run()
            except IdentityBridgeError as error:
                errors.append(error)

    await in_request(binding, call, enabled=True, key_mode=True,
                     verifier=NoAccountVerifier(), tolerate_auth_failure=True)
    await settled()
    assert len(errors) == 3
    assert {e.status_code for e in errors} == {401}
    assert {e.code for e in errors} == {"canonical_auth_session_not_found"}
    assert not any(rpc_calls(binding, name) for name in WRITES)


async def test_key_write_uses_only_the_proof_subject_never_a_caller_named_account():
    binding = Binding()
    errors = []

    async def call(authority, request):
        # A caller-supplied account string is never an input to the account
        # key: the subject comes from this request's verified proof alone.
        answers = await shadow.mode_revoke_consent(
            authority, session_id=SID, consent_id=CONSENT_ID,
            confirmed=True, confirmation_version="pc-enrollment-consent-v1")
        assert answers["consent_id"] == CONSENT_ID
        assert rpc_calls(binding, ACCOUNT_REVOKE_RPC)[0][1]["canonical_subject_id"] == PRIVATE
        errors.append("ok")

    await in_request(binding, call, enabled=True, key_mode=True)
    await settled()
    assert errors == ["ok"]


async def test_key_write_with_an_expired_proof_is_401():
    binding = Binding()
    errors = []

    async def call(authority, _request):
        try:
            await shadow.mode_revoke_consent(
                authority, session_id=SID, consent_id=CONSENT_ID,
                confirmed=True, confirmation_version="pc-enrollment-consent-v1")
        except IdentityBridgeError as error:
            errors.append(error)

    await in_request(binding, call, enabled=True, key_mode=True,
                     verifier=ExpiredVerifier(), tolerate_auth_failure=True)
    await settled()
    assert errors and errors[0].status_code == 401
    assert not rpc_calls(binding, ACCOUNT_REVOKE_RPC)


async def test_key_revoke_withdrawn_subject_refuses_with_canonical_subject_deleted():
    binding = Binding()
    binding.error = {"ok": False, "error": {"code": "canonical_subject_deleted", "message": "refused"}}
    binding.error_rpc = ACCOUNT_REVOKE_RPC
    errors = []

    async def call(authority, _request):
        try:
            await shadow.mode_revoke_consent(
                authority, session_id=SID, consent_id=CONSENT_ID,
                confirmed=True, confirmation_version="pc-enrollment-consent-v1")
        except IdentityBridgeError as error:
            errors.append(error)

    await in_request(binding, call, enabled=True, key_mode=True)
    await settled()
    assert errors and errors[0].code == "canonical_subject_deleted"
    assert errors[0].status_code == 503


async def test_key_write_malformed_answer_is_503_invalid():
    binding = Binding()
    binding.error = {"ok": True, "consent": {"consent_id": "x"}}
    binding.error_rpc = ACCOUNT_REVOKE_RPC
    errors = []

    async def call(authority, _request):
        try:
            await shadow.mode_revoke_consent(
                authority, session_id=SID, consent_id=CONSENT_ID,
                confirmed=True, confirmation_version="pc-enrollment-consent-v1")
        except IdentityBridgeError as error:
            errors.append(error)

    await in_request(binding, call, enabled=True, key_mode=True)
    await settled()
    assert errors and errors[0].code == "control_plane_rpc_invalid"
    assert errors[0].status_code == 503


async def test_key_revoke_falsy_confirmation_refused_before_any_rpc():
    binding = Binding()
    errors = []

    async def call(authority, _request):
        try:
            await shadow.mode_revoke_consent(
                authority, session_id=SID, consent_id=CONSENT_ID,
                confirmed=False, confirmation_version="pc-enrollment-consent-v1")
        except IdentityBridgeError as error:
            errors.append(error)

    await in_request(binding, call, enabled=True, key_mode=True)
    await settled()
    assert errors and errors[0].code == "connector_enrollment_explicit_consent_required"
    assert errors[0].status_code == 403
    assert not rpc_calls(binding, ACCOUNT_REVOKE_RPC)
    assert not rpc_calls(binding, SESSION_REVOKE_RPC)


# --- mcp_oauth: the server-side scope read answers the current mode --------


@pytest.mark.parametrize("key_mode", [False, True])
async def test_mcp_oauth_scope_read_follows_the_mode(key_mode):
    binding = Binding()
    answers = []

    async def call(authority, request):
        from app import chat_pc_drive as drives
        from app import mcp_oauth as oauth

        async def resolver(_request, _user_id):
            return SimpleNamespace(session_id=SID), PRIVATE, TENANT

        with patch.object(drives, "_resolve_chat_owner", resolver):
            answers.append(await oauth._converted_owner_id(request, "usr_fixture"))

    await in_request(binding, call, enabled=True, key_mode=key_mode)
    await settled()
    # The consent screen's owner conversion answers from the same scope in
    # each mode: the session key in off/shadow, the account key in key mode.
    assert answers and answers[-1] == PRIVATE
    if key_mode:
        assert rpc_calls(binding, ACCOUNT_SCOPE_RPC)
        assert not rpc_calls(binding, "resolve_connector_owner_scope")
    else:
        # The session key answers; the shadow decorator only records a
        # comparison read-behind, it never answers from the account key.
        assert rpc_calls(binding, "resolve_connector_owner_scope")
        assert rpc_calls(binding, ACCOUNT_SCOPE_RPC)


# --- pending_pc: server-owned signed session keeps the session key ---------



class Broker:
    def __init__(self):
        self.calls = []
        self.credential = b"one-time-secret-with-length"

    async def issue_enrollment_challenge(self, **kwargs):
        self.calls.append(("issue", kwargs))
        return {
            "challenge_id": CHALLENGE, "account_ref": "private-account-scope",
            "workspace_ref": "private-workspace",
            "issued_at": NOW.isoformat(), "expires_at": (NOW + timedelta(minutes=10)).isoformat(),
        }, "f" * 32

    async def get_enrollment_binding(self, *, challenge_id):
        assert challenge_id == CHALLENGE
        return {"challenge_id": CHALLENGE, "consent_ref": CONSENT_ID,
                "owner_ref": PRIVATE, "account_ref": "private-account-scope",
                "workspace_ref": "private-workspace", "device_id": DEVICE,
                "bound_at": NOW.isoformat()}

    async def verify_enrollment_bootstrap(self, **kwargs):
        self.calls.append(("preflight", kwargs))
        return {"challenge_id": CHALLENGE, "device_id": DEVICE,
                "proof_valid": True, "challenge_consumed": False}

    async def redeem_enrollment(self, **kwargs):
        self.calls.append(("redeem", kwargs))
        return {"binding_ref": "pairing-binding.1", "device_id": DEVICE,
                "account_ref": "private-account-scope", "workspace_ref": "private-workspace",
                "credential_generation": 1,
                "credential_expires_at": (NOW + timedelta(days=30)).isoformat()}, self.credential

    async def revoke_binding(self, *, binding_ref):
        return {"binding_ref": binding_ref, "state": "revoked"}


class Handoff:
    async def ready(self, *, challenge_id, device_id):
        return True

    async def deliver_once(self, *, challenge_id, device_id, credential, enrollment, now):
        assert credential == b"one-time-secret-with-length"
        return DeviceCredentialInstallAck(
            challenge_id=challenge_id, device_id=device_id,
            binding_ref=enrollment["binding_ref"],
            credential_generation=enrollment["credential_generation"],
            proof_kind="protected_store_save_readback",
            transcript_version=INSTALL_ACK_TRANSCRIPT_VERSION,
            local_store_confirmed=True,
            proof_hex=installation_proof(
                credential=credential, challenge_id=challenge_id, device_id=device_id,
                binding_ref=enrollment["binding_ref"],
                credential_generation=enrollment["credential_generation"],
            ),
        )

    async def verify_authenticated_ack(self, *, challenge_id, device_id, ack):
        assert ack.challenge_id == challenge_id and ack.device_id == device_id
        return True


def host_for(binding, broker, handoff):
    return CanonicalConnectorEnrollmentAsyncHost(
        identity=CloudflareControlPlaneIdentityAuthority(binding),
        broker=broker, credential_handoff=handoff,
    )


@pytest.mark.parametrize("key_mode", [False, True])
async def test_redeem_moves_the_pair_together_and_consumes_once(key_mode):
    binding, broker, handoff = Binding(), Broker(), Handoff()
    result = {}

    async def call(authority, _request):
        host = CanonicalConnectorEnrollmentAsyncHost(
            identity=authority, broker=broker, credential_handoff=handoff)
        result.update(await host.redeem(
            challenge_id=CHALLENGE, device_id=DEVICE, proof_ref="pairing-proof:" + "a" * 64,
            session_id=SID))

    await in_request(binding, call, enabled=True, key_mode=key_mode)
    await settled()
    assert result["device_id"] == DEVICE
    assert result["lifecycle"] == "paired_offline"
    account_authorize = rpc_calls(binding, ACCOUNT_AUTHORIZE_RPC)
    session_authorize = rpc_calls(binding, SESSION_AUTHORIZE_RPC)
    if key_mode:
        # Exactly one consuming authorize, through the account key, after an
        # account-bound challenge; the race checks only re-read consent.
        assert len(account_authorize) == 1
        assert not session_authorize
        consent_read = rpc_calls(binding, ACCOUNT_READ_RPC)
        assert len(consent_read) >= 2
    else:
        # Exactly the three session-key authorizes (authorize + two rechecks).
        assert not account_authorize
        assert len(session_authorize) == 3
    assert [c[0] for c in broker.calls].count("redeem") == 1
    assert "credential" not in result


async def test_redeem_without_session_id_fails_closed_in_key_mode():
    binding = Binding()
    errors = []

    async def call(authority, _request):
        host = CanonicalConnectorEnrollmentAsyncHost(
            identity=authority, broker=Broker(), credential_handoff=Handoff())
        try:
            await host.redeem(challenge_id=CHALLENGE, device_id=DEVICE, proof_ref="pairing-proof:" + "b" * 64)
        except IdentityBridgeError as error:
            errors.append(error)

    await in_request(binding, call, enabled=True, key_mode=True)
    await settled()
    assert errors and errors[0].status_code == 401
    assert errors[0].code == "canonical_auth_session_not_found"
    assert not rpc_calls(binding, ACCOUNT_AUTHORIZE_RPC)
    assert not rpc_calls(binding, SESSION_AUTHORIZE_RPC)

PENDING_OWNER = AuthSessionSnapshot(session_id=SID, product_id="b54-padiem-claw",
    subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id=PRIVATE),
    issued_at=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(minutes=10), tenant_id=TENANT)


class PendingPcBroker:
    def __init__(self):
        self.calls = []

    async def reserve_pending_pc_owner_intent(self, payload):
        self.calls.append(("reserve", deepcopy(payload)))
        return {
            "request_ref": payload["request_ref"],
            "device_id": "pending-pc-device.1",
            "device_possession_verified": True,
            "connected_to_outbound_channel": True,
            "reserved_once": True,
            "expires_at": (NOW + timedelta(minutes=1)).isoformat(),
        }

    async def deliver_pending_pc_link(self, payload):
        self.calls.append(("deliver", deepcopy(payload)))
        return {}


async def test_pending_pc_owner_reserve_keeps_the_session_key_in_key_mode():
    """The server-owned signed session (conservative approach) never uses the
    account key: in key mode it still reads the owner scope through the
    session key and is not refused with 401 by the account subject
    derivation.
    """
    from app.connector_pending_pc_owner_rpc import CanonicalBrokerOwnerPendingPcPort

    binding = Binding()
    broker = PendingPcBroker()
    receipts = []

    async def call(authority, _request):
        port = CanonicalBrokerOwnerPendingPcPort(
            signed_owner=PENDING_OWNER, canonical_broker_binding=broker, identity=authority)
        receipt = await port.reserve_once(request_ref="link." + "a" * 32)
        receipts.append(receipt)

    await in_request(binding, call, enabled=True, key_mode=True)
    await settled()
    assert receipts and receipts[-1]["reserved_once"] is True
    # The signed owner's scope is read through the session key, exactly as
    # today; the account-key scope RPC is never invoked on this path.
    assert rpc_calls(binding, "resolve_connector_owner_scope")
    assert not rpc_calls(binding, ACCOUNT_SCOPE_RPC)

    # The off mode behaves the same way.
    binding_off = Binding()
    receipts_off = []

    async def call_off(authority, _request):
        port = CanonicalBrokerOwnerPendingPcPort(
            signed_owner=PENDING_OWNER, canonical_broker_binding=PendingPcBroker(), identity=authority)
        receipts_off.append(await port.reserve_once(request_ref="link." + "b" * 32))

    await in_request(binding_off, call_off, enabled=False)
    await settled()
    assert receipts_off and receipts_off[-1]["reserved_once"] is True
    assert rpc_calls(binding_off, "resolve_connector_owner_scope")


# --- pc connector scope: key mode uses the single tenant check -------------

async def test_key_pc_scope_reads_the_current_b54_session_only():
    """Key mode: the PC-scope resolution reads the owner's current B54
    canonical session only (no B62 session read) and answers from the
    account-key scope RPC; the tenant-only verdict carries no B62 read."""
    binding = Binding()

    async def call(authority, request):
        async def b54(_authority, _owner_id):
            return SimpleNamespace(auth_session=SimpleNamespace(
                session_id=SID, tenant_id=TENANT,
                subject=SimpleNamespace(subject_id=PRIVATE)))

        b62_calls = []

        async def unexpected_b62(_request, _owner_id):
            b62_calls.append(True)
            raise AssertionError("the B62 session read must not run in key mode")

        with (
            patch("app.pc_work_context._resolve_owner_session", side_effect=unexpected_b62),
            patch(
                "padiem_control_plane.b54_identity_bridge.resolve_current_b54_canonical_session",
                side_effect=b54,
            ),
        ):
            result = await pc_scope_context._resolve_connector_scope_now(
                request, owner_id="usr_fixture", workspace_id=TENANT,
            )
        assert result.ready is True
        assert result.session_id == SID
        assert result.account_ref == "private-account-scope"
        assert not b62_calls
        assert rpc_calls(binding, ACCOUNT_SCOPE_RPC)
        assert not rpc_calls(binding, "resolve_connector_owner_scope")

    await in_request(binding, call, key_mode=True)
    await settled()


async def test_off_pc_scope_answers_the_crosscheck_and_records_nothing(capsys):
    """Off (shadow context absent): the cross-check verdict stands and no
    pc_scope comparison is recorded."""
    binding = Binding()

    async def call(authority, request):
        async def b54(_authority, _owner_id):
            return SimpleNamespace(auth_session=SimpleNamespace(
                session_id=SID, tenant_id=TENANT,
                subject=SimpleNamespace(subject_id=PRIVATE)))

        async def owner_session(_request, _owner_id):
            return TENANT, SimpleNamespace(
                session_id=SID, subject=SimpleNamespace(subject_id=PRIVATE))

        with (
            patch("app.pc_work_context._resolve_owner_session", side_effect=owner_session),
            patch(
                "padiem_control_plane.b54_identity_bridge.resolve_current_b54_canonical_session",
                side_effect=b54,
            ),
        ):
            result = await pc_scope_context._resolve_connector_scope_now(
                request, owner_id="usr_fixture", workspace_id=TENANT,
            )
        assert result.ready is True
        assert rpc_calls(binding, "resolve_connector_owner_scope")

    await in_request(binding, call, enabled=False)
    await settled()
    out = capsys.readouterr().out
    assert "method=pc_scope" not in out


async def test_the_android_ui_version_revokes_in_all_three_modes():
    """#7732 option 1: the reviewed Android UI consent version revokes in
    every switch mode, carried to the authority exactly as sent."""
    for enabled, key_mode in ((False, False), (True, False), (True, True)):
        binding = Binding()
        answers = []

        async def call(authority, _request):
            answers.append(await shadow.mode_revoke_consent(
                authority, session_id=SID, consent_id=CONSENT_ID,
                confirmed=True, confirmation_version="android-enrollment-consent-v1"))

        await in_request(binding, call, enabled=enabled, key_mode=key_mode)
        await settled()
        assert answers[0]["withdrawn_at"] is not None
        expected = ACCOUNT_REVOKE_RPC if key_mode else SESSION_REVOKE_RPC
        revokes = [c for c in binding.calls if c[0] in (SESSION_REVOKE_RPC, ACCOUNT_REVOKE_RPC)]
        assert [c[0] for c in revokes] == [expected]
        ((_name, payload),) = revokes
        assert payload["confirmation_version"] == "android-enrollment-consent-v1"
