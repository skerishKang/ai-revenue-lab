"""P5-E: the connector bundle answers its reads per the account-key mode.

Off answers the session key exactly as today; shadow answers the session key
and only records the comparison; key answers the account key built from this
request's verified proof alone. The shadow journal carries the closed latency
band of the comparison. Absent or expired proof refuses with the same 401 an
absent session gets, and closed authority codes surface unchanged.

ENROLLMENT and approval sites are not in this bundle (they are P5-F) and no
session value from the request is ever an account-key input.
"""
import asyncio
import time
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app import connector_account_shadow as shadow
from app import connector_account_subject as proof
from app.config import Settings
from app.control_plane_identity import IdentityBridgeError
from app.control_plane_identity_worker import CloudflareControlPlaneIdentityAuthority
from app.shared_auth_adapter import SharedChatAuth
from padiem_control_plane import CanonicalSubjectRef, SubjectType
from padiem_control_plane.auth_sessions import AuthSessionSnapshot
from starlette.requests import Request

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
    "workspace": "private-workspace",
    "context": {"present": True, "product_id": "b62", "subject_id": PRIVATE,
                "actor_ref": "private-actor", "workspace_ref": "private-workspace"},
}
SESSION_RPC = {
    "owner_scope": "resolve_connector_owner_scope",
    "consent": "resolve_connector_enrollment_consent_for_device",
    "workspace": "resolve_connector_workspace",
    "context": "resolve_connector_context",
}
ACCOUNT_RPC = {
    "owner_scope": "resolve_connector_owner_scope_for_subject",
    "consent": "resolve_connector_enrollment_consent_for_subject_device",
    "workspace": "resolve_connector_workspace_for_subject",
    "context": "resolve_connector_context_for_subject",
}


def adopt(kind, value):
    """Wrap a projected answer in the wire envelope the adapter validates."""
    if kind == "workspace":
        return {"present": True, "workspace_ref": value}
    if kind == "context":
        return dict(value)
    return deepcopy(value)


class Binding:
    _timeout = .03

    def __init__(self):
        self.calls = []
        self.alternate = {k: adopt(k, v) for k, v in BASELINE.items()}
        self.original = {k: adopt(k, v) for k, v in BASELINE.items()}
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
            for kind in shadow.ACCOUNT_READS:
                account = name == ACCOUNT_RPC[kind]
                if account or name == SESSION_RPC[kind]:
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
                    field = shadow.ACCOUNT_READS[kind][1]
                    return {"ok": True, field: deepcopy((self.alternate if account else self.original)[kind])}
            raise AssertionError("unexpected_fixture_rpc")
        return call


class Verifier:
    def verify(self, _token):
        return {"accountId": PRIVATE, "sessionId": "private-shared-session", "expiresAt": int(time.time()) + 600}


class NoAccountVerifier:
    def verify(self, _token):
        return {"sessionId": "private-shared-session", "expiresAt": int(time.time()) + 600}


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


async def read(authority, kind, *, session_id=SID):
    kwargs = {"session_id": session_id}
    if kind == "consent":
        kwargs["device_id"] = "private-device"
    return await shadow.mode_connector_read(authority, kind, **kwargs)


def _latency_and_reason(line):
    reason = line.split("reason=", 1)[1].split(" ", 1)[0]
    latency = line.split("latency=", 1)[1].split(" ", 1)[0]
    return reason, latency


@pytest.mark.parametrize("seconds,bucket", [
    (0, "lt100ms"), (0.099, "lt100ms"), (0.1, "lt500ms"), (0.49, "lt500ms"),
    (0.5, "lt2s"), (1.99, "lt2s"), (2.0, "ge2s"), (30.0, "ge2s"),
])
def test_latency_buckets_are_the_four_closed_bands(seconds, bucket):
    assert shadow._latency_bucket(seconds) == bucket


@pytest.mark.parametrize("kind", tuple(BASELINE))
async def test_off_answers_the_session_key_exactly_as_today(kind):
    binding = Binding()
    answers = []

    async def call(authority, _request):
        answers.append(await read(authority, kind))

    await in_request(binding, call, enabled=False)
    await settled()
    assert answers[0] == BASELINE[kind]
    assert not any(name == ACCOUNT_RPC[kind] for name, _ in binding.calls)

    binding = Binding()

    async def call2(authority, _request):
        answers.append(await read(authority, kind))

    await in_request(binding, call2, enabled=True)
    await settled()
    assert answers[1] == BASELINE[kind]
    assert any(name == ACCOUNT_RPC[kind] for name, _ in binding.calls)
    assert any(name == SESSION_RPC[kind] for name, _ in binding.calls)


@pytest.mark.parametrize("kind", tuple(BASELINE))
async def test_shadow_only_records_the_comparison(kind, capsys):
    binding = Binding()
    answers = []

    async def call(authority, _request):
        answers.append(await read(authority, kind))

    await in_request(binding, call)
    await settled()
    assert answers[0] == BASELINE[kind]
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert lines[0] == ("connector_account_shadow method=" + kind + " reason=match latency=lt100ms")
    assert all(s not in lines[0] for s in (PRIVATE, SID, TENANT, "private-device"))


@pytest.mark.parametrize("kind", tuple(BASELINE))
async def test_key_answers_the_account_key_alone(kind):
    binding = Binding()
    answers = []

    async def call(authority, _request):
        answers.append(await read(authority, kind))

    await in_request(binding, call, key_mode=True)
    await settled()
    assert answers[0] == BASELINE[kind]
    assert not any(name == SESSION_RPC[kind] for name, _ in binding.calls)
    assert any(name == ACCOUNT_RPC[kind] for name, _ in binding.calls)


@pytest.mark.parametrize("kind", ("workspace", "context"))
async def test_key_subject_comes_from_the_request_proof_alone(kind):
    """For workspace/context the request's verified subject is authoritative."""
    binding = Binding()

    async def call(authority, _request):
        answer = await shadow.mode_connector_read(authority, kind, session_id="private-other-session")
        assert answer == BASELINE[kind]

    await in_request(binding, call, key_mode=True)
    await settled()
    (_name, payload), = [c for c in binding.calls if c[0] == ACCOUNT_RPC[kind]]
    assert payload["canonical_subject_id"] == PRIVATE


@pytest.mark.parametrize("kind", tuple(BASELINE))
async def test_key_without_verified_proof_refuses_with_the_session_401(kind):
    binding = Binding()

    async def call(authority, _request):
        with pytest.raises(IdentityBridgeError) as caught:
            await read(authority, kind)
        assert caught.value.code == "canonical_auth_session_not_found"
        assert caught.value.status_code == 401

    await in_request(binding, call, key_mode=True, tolerate_auth_failure=True, verifier=NoAccountVerifier())
    await settled()
    assert not binding.calls or not any(name in (ACCOUNT_RPC[kind], SESSION_RPC[kind]) for name, _ in binding.calls)


@pytest.mark.parametrize("kind", tuple(BASELINE))
async def test_key_blocks_a_withdrawn_account(kind):
    binding = Binding()
    binding.error = {"ok": False, "error": {"code": "canonical_subject_deleted", "message": PRIVATE}}

    async def call(authority, _request):
        with pytest.raises(IdentityBridgeError) as caught:
            await read(authority, kind)
        assert caught.value.code == "canonical_subject_deleted"
        assert caught.value.status_code == 503
        assert PRIVATE not in repr(caught.value)

    await in_request(binding, call, key_mode=True)
    await settled()


@pytest.mark.parametrize("kind", ("owner_scope", "consent"))
async def test_key_blocks_an_unremembered_foreign_session(kind):
    """For the scope/consent reads a foreign session id is never consulted: it must be forgotten."""
    binding = Binding()

    async def call(authority, _request):
        with pytest.raises(IdentityBridgeError) as caught:
            await shadow.mode_connector_read(authority, kind, session_id="private-foreign-session",
                                             device_id="private-device" if kind == "consent" else None)
        assert caught.value.code == "canonical_auth_session_not_found"
        assert caught.value.status_code == 401

    await in_request(binding, call, key_mode=True)
    await settled()
    assert not any(name in (ACCOUNT_RPC[kind], SESSION_RPC[kind]) for name, _ in binding.calls)


@pytest.mark.parametrize("kind", ("workspace", "context"))
async def test_key_ignores_the_supplied_session_and_uses_verified_subject(kind):
    """For the workspace/context reads the session id never reaches the account call."""
    binding = Binding()

    async def call(authority, _request):
        await shadow.mode_connector_read(authority, kind, session_id="private-foreign-session")

    await in_request(binding, call, key_mode=True)
    await settled()
    (_name, payload), = [c for c in binding.calls if c[0] == ACCOUNT_RPC[kind]]
    assert "private-foreign-session" not in repr(payload)
    assert payload["canonical_subject_id"] == PRIVATE


@pytest.mark.parametrize("kind", tuple(BASELINE))
async def test_key_mode_transport_failure_maps_to_unavailable(kind):
    binding = Binding()
    binding.error = RuntimeError(PRIVATE)

    async def call(authority, _request):
        with pytest.raises(IdentityBridgeError) as caught:
            await read(authority, kind)
        assert caught.value.code == "control_plane_identity_unavailable"
        assert caught.value.status_code == 503
        assert PRIVATE not in repr(caught.value)

    await in_request(binding, call, key_mode=True)
    await settled()


@pytest.mark.parametrize("kind", tuple(BASELINE))
async def test_key_mode_malformed_account_answer_maps_to_invalid(kind):
    binding = Binding()
    binding.error = {"ok": True, "scope": {"account_ref": "private-account-scope", "workspace_ref": "private-workspace",
                                           "owner_subject_id": "private-other"},
                     "workspace": {"present": True, "workspace_ref": "private-workspace"},
                     "context": dict(BASELINE["context"]),
                     "consent": deepcopy(BASELINE["consent"])}

    async def call(authority, _request):
        with pytest.raises(IdentityBridgeError) as caught:
            await read(authority, kind)
        assert caught.value.code == "control_plane_rpc_invalid"
        assert caught.value.status_code == 503

    await in_request(binding, call, key_mode=True)
    await settled()


@pytest.mark.parametrize("kind", tuple(BASELINE))
async def test_shadow_never_changes_the_connector_answer(kind, capsys):
    binding = Binding()
    answers = []

    async def call(authority, _request):
        answers.append(await read(authority, kind))

    binding.error = RuntimeError(PRIVATE)
    await in_request(binding, call)
    await settled()
    assert answers[0] == BASELINE[kind]
    reason, latency = _latency_and_reason(capsys.readouterr().out.strip())
    assert reason == "account_unavailable"
    assert latency == "lt100ms"
    assert PRIVATE not in capsys.readouterr().out
