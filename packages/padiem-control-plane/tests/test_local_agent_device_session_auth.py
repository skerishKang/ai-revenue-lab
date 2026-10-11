"""#3436 B2c — the canonical device-session authentication projection.

Unit coverage for the read-only ``authenticate_device_session`` seam: the
canonical verifier preamble (binding digest/expiry/revocation, then the full
session/binding scope correlation), the closed safe projection, read-only
behaviour, and every deny shape the Desktop conversation read must refuse.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.local_agent_broker_auth import (
    StateBackedLocalAgentBindingAuthenticator,
    authenticate_local_agent_device_session,
    authenticated_device_session_projection,
)
from padiem_control_plane.local_agent_broker_state import (
    InMemoryLocalAgentBrokerStatePort,
    StateBackedLocalAgentBrokerAuthority,
)


BASE = datetime(2026, 10, 3, 2, 0, tzinfo=timezone.utc)
AUTHORITY_REF = "control-plane.local-agent-broker.session-auth-test.v1"
PEPPER = b"device-session-auth-test-pepper-value"
CREDENTIAL = b"device-session-auth-test-credential"
ROTATED_CREDENTIAL = b"device-session-auth-test-rotated-credential"
BINDING_REF = "bind.session-auth.1"
DEVICE_ID = "device.session-auth.1"
ACCOUNT_REF = "usr_session_auth_owner"
WORKSPACE_REF = "ws.session-auth.1"
SESSION_ID = "sess.session-auth.1"


class _DurableMemoryStatePort(InMemoryLocalAgentBrokerStatePort):
    durable = True


def _fixture() -> tuple[_DurableMemoryStatePort, StateBackedLocalAgentBrokerAuthority, StateBackedLocalAgentBindingAuthenticator]:
    state = _DurableMemoryStatePort()
    authority = StateBackedLocalAgentBrokerAuthority(
        pepper=PEPPER,
        authority_ref=AUTHORITY_REF,
        state_port=state,
    )
    authority.register_binding(
        binding_ref=BINDING_REF,
        device_id=DEVICE_ID,
        account_ref=ACCOUNT_REF,
        workspace_ref=WORKSPACE_REF,
        credential=CREDENTIAL,
        now=BASE,
        credential_ttl_seconds=3600,
    )
    authority.open_session(
        session_id=SESSION_ID,
        binding_ref=BINDING_REF,
        credential=CREDENTIAL,
        account_ref=ACCOUNT_REF,
        workspace_ref=WORKSPACE_REF,
        now=BASE + timedelta(seconds=1),
        ttl_seconds=900,
    )
    authenticator = StateBackedLocalAgentBindingAuthenticator(
        pepper=PEPPER,
        authority_ref=AUTHORITY_REF,
        state_port=state,
    )
    return state, authority, authenticator


def _authenticate(authenticator: StateBackedLocalAgentBindingAuthenticator, **overrides):
    return authenticator.authenticate_device_session(
        session_id=overrides.get("session_id", SESSION_ID),
        binding_ref=overrides.get("binding_ref", BINDING_REF),
        credential=overrides.get("credential", CREDENTIAL),
        now=overrides.get("now", BASE + timedelta(seconds=2)),
    )


def test_valid_current_broker_session_authenticates_with_server_derived_identity() -> None:
    _, _, authenticator = _fixture()

    projection = _authenticate(authenticator)

    assert projection["authenticated"] is True
    assert projection["session_id"] == SESSION_ID
    assert projection["binding_ref"] == BINDING_REF
    assert projection["device_id"] == DEVICE_ID
    # The identity is derived from the verified canonical binding state, never
    # from caller input.
    assert projection["account_ref"] == ACCOUNT_REF
    assert projection["workspace_ref"] == WORKSPACE_REF
    assert projection["credential_generation"] == 1
    assert projection["session_expires_at"] == (BASE + timedelta(seconds=901)).isoformat()


def test_projection_never_carries_raw_credential_or_digest() -> None:
    _, _, authenticator = _fixture()

    projection = _authenticate(authenticator)

    assert projection["raw_device_credential"] is False
    assert projection["credential_digest_exposed"] is False
    assert CREDENTIAL.decode("utf-8") not in str(sorted(projection))
    assert "credential_digest" not in projection


def test_authentication_is_read_only_over_canonical_state() -> None:
    state, _, authenticator = _fixture()
    before = state.load(authority_ref=AUTHORITY_REF)

    _authenticate(authenticator)

    after = state.load(authority_ref=AUTHORITY_REF)
    assert after.version == before.version
    assert after.snapshot == before.snapshot


def test_wrong_credential_is_denied() -> None:
    _, _, authenticator = _fixture()

    with pytest.raises(ControlPlaneContractError) as excinfo:
        _authenticate(authenticator, credential=b"completely-wrong-credential")
    assert excinfo.value.code == "invalid_device_credential"


def test_expired_credential_is_denied() -> None:
    _, _, authenticator = _fixture()

    with pytest.raises(ControlPlaneContractError) as excinfo:
        _authenticate(authenticator, now=BASE + timedelta(hours=2))
    assert excinfo.value.code == "device_credential_expired"


def test_revoked_binding_is_denied() -> None:
    state, authority, authenticator = _fixture()
    authority.revoke_binding(BINDING_REF, now=BASE + timedelta(seconds=2))

    with pytest.raises(ControlPlaneContractError) as excinfo:
        _authenticate(authenticator, now=BASE + timedelta(seconds=3))
    assert excinfo.value.code == "device_binding_revoked"


def test_revocation_denies_a_previously_valid_session_immediately() -> None:
    state, authority, authenticator = _fixture()

    first = _authenticate(authenticator, now=BASE + timedelta(seconds=2))
    assert first["authenticated"] is True
    authority.revoke_binding(BINDING_REF, now=BASE + timedelta(seconds=3))
    with pytest.raises(ControlPlaneContractError):
        _authenticate(authenticator, now=BASE + timedelta(seconds=4))


def test_expired_broker_session_is_denied() -> None:
    _, _, authenticator = _fixture()

    # Session TTL is 900s; the credential is still valid at this instant.
    with pytest.raises(ControlPlaneContractError) as excinfo:
        _authenticate(authenticator, now=BASE + timedelta(seconds=1_800))
    assert excinfo.value.code == "device_session_expired"


def test_wrong_binding_ref_is_denied() -> None:
    state, authority, authenticator = _fixture()
    # A second device and binding, with its own session.
    authority.register_binding(
        binding_ref="bind.session-auth.2",
        device_id="device.session-auth.2",
        account_ref="usr_session_auth_other_owner",
        workspace_ref="ws.session-auth.2",
        credential=b"device-session-auth-test-other-credential",
        now=BASE,
        credential_ttl_seconds=3600,
    )
    authority.open_session(
        session_id="sess.session-auth.2",
        binding_ref="bind.session-auth.2",
        credential=b"device-session-auth-test-other-credential",
        account_ref="usr_session_auth_other_owner",
        workspace_ref="ws.session-auth.2",
        now=BASE + timedelta(seconds=1),
        ttl_seconds=900,
    )

    # Present session 1's id and credential against the other binding.
    with pytest.raises(ControlPlaneContractError):
        _authenticate(
            authenticator,
            binding_ref="bind.session-auth.2",
            credential=CREDENTIAL,
        )


def test_stale_credential_generation_session_correlation_is_denied() -> None:
    _, authority, authenticator = _fixture()

    authority.rotate_credential(
        BINDING_REF,
        expected_generation=1,
        new_credential=ROTATED_CREDENTIAL,
        now=BASE + timedelta(seconds=2),
    )
    # The pre-rotation credential no longer verifies at all.
    with pytest.raises(ControlPlaneContractError) as old_credential:
        _authenticate(authenticator, now=BASE + timedelta(seconds=3))
    assert old_credential.value.code == "invalid_device_credential"
    # Rotation purged the pre-rotation sessions, so the old session id is no
    # longer a live session for any credential: the stale correlation is gone.
    with pytest.raises(ControlPlaneContractError) as stale_session:
        _authenticate(
            authenticator,
            session_id=SESSION_ID,
            credential=ROTATED_CREDENTIAL,
            now=BASE + timedelta(seconds=3),
        )
    assert stale_session.value.code == "device_session_not_found"
    # A fresh session on the rotated generation authenticates cleanly.
    authority.open_session(
        session_id="sess.session-auth.1.gen2",
        binding_ref=BINDING_REF,
        credential=ROTATED_CREDENTIAL,
        account_ref=ACCOUNT_REF,
        workspace_ref=WORKSPACE_REF,
        now=BASE + timedelta(seconds=3),
        ttl_seconds=900,
    )
    projection = _authenticate(
        authenticator,
        session_id="sess.session-auth.1.gen2",
        credential=ROTATED_CREDENTIAL,
        now=BASE + timedelta(seconds=4),
    )
    assert projection["credential_generation"] == 2


def test_caller_supplied_identity_fields_cannot_alter_owner_or_scope() -> None:
    """The seam accepts no identity input at all: material names only itself."""

    _, _, authenticator = _fixture()

    projection = _authenticate(authenticator)

    # The projection's owner/scope are the binding's, and the call signature
    # carries no user_id/account_ref/workspace_ref/tenant/product parameter —
    # proven structurally by the refused keyword below.
    assert projection["account_ref"] == ACCOUNT_REF
    assert projection["workspace_ref"] == WORKSPACE_REF
    with pytest.raises(TypeError):
        authenticator.authenticate_device_session(  # type: ignore[call-arg]
            session_id=SESSION_ID,
            binding_ref=BINDING_REF,
            credential=CREDENTIAL,
            now=BASE + timedelta(seconds=2),
            account_ref="usr_attacker_chosen",  # type: ignore[call-arg]
            workspace_ref="ws_attacker_chosen",  # type: ignore[call-arg]
            user_id="usr_attacker_chosen",  # type: ignore[call-arg]
        )


def test_in_memory_seam_matches_state_backed_projection() -> None:
    state, _, authenticator = _fixture()
    stored = state.load(authority_ref=AUTHORITY_REF)
    authority = stored.snapshot.restore(pepper=PEPPER)

    session = authenticate_local_agent_device_session(
        authority,
        session_id=SESSION_ID,
        binding_ref=BINDING_REF,
        credential=CREDENTIAL,
        now=BASE + timedelta(seconds=2),
    )
    assert authenticated_device_session_projection(session) == _authenticate(authenticator)


# ---------------------------------------------------------------------------
# Runtime level: the durable-object RPC surface the trusted service binding
# exposes to padiem-chat.
# ---------------------------------------------------------------------------

import asyncio
import base64
import importlib.util
from pathlib import Path
import sqlite3
import sys
import types


class _FakeResponse:
    def __init__(self, body="", *, status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = headers or {}


class _FakeWorkerEntrypoint:
    def __init__(self, env=None):
        self.env = env


class _FakeDurableObject:
    def __init__(self, ctx, env):
        self.ctx = ctx
        self.env = env


_workers = types.ModuleType("workers")
_workers.Response = _FakeResponse
_workers.WorkerEntrypoint = _FakeWorkerEntrypoint
_workers.DurableObject = _FakeDurableObject
sys.modules.setdefault("workers", _workers)

_WORKER_PATH = Path(__file__).parents[1] / "local_agent_broker_worker.py"
_WORKER_SPEC = importlib.util.spec_from_file_location("padiem_local_agent_device_session_auth_test", _WORKER_PATH)
assert _WORKER_SPEC is not None and _WORKER_SPEC.loader is not None
broker_worker = importlib.util.module_from_spec(_WORKER_SPEC)
sys.modules[_WORKER_SPEC.name] = broker_worker
_WORKER_SPEC.loader.exec_module(broker_worker)


RPC_AUTHORITY_REF = "control-plane.local-agent-broker.session-auth-rpc-test.v1"
RPC_PEPPER = "cloudflare-do-session-auth-rpc-test-pepper"
RPC_CREDENTIAL = b"cloudflare-do-session-auth-rpc-credential"
RPC_ACCOUNT_REF = "usr_session_auth_rpc_owner"
RPC_WORKSPACE_REF = "ws.session-auth.rpc.1"
RPC_SESSION_ID = "sess.session-auth.rpc.1"
RPC_BINDING_REF = "bind.session-auth.rpc.1"


class _Cursor:
    def __init__(self, rows: list[dict], rows_written: int) -> None:
        self._rows = rows
        self.rowsWritten = rows_written

    def toArray(self):
        return list(self._rows)

    def one(self):
        if len(self._rows) != 1:
            raise RuntimeError("expected exactly one row")
        return self._rows[0]


class _Sql:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def exec(self, query: str, *bindings):
        cursor = self.connection.execute(query, bindings)
        rows: list[dict] = []
        if cursor.description is not None:
            names = [item[0] for item in cursor.description]
            rows = [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
        rows_written = cursor.rowcount if cursor.rowcount >= 0 else 0
        return _Cursor(rows, rows_written)


class _Storage:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:", isolation_level=None)
        self.sql = _Sql(self.connection)

    def transactionSync(self, callback):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            value = callback()
            self.connection.execute("COMMIT")
            return value
        except Exception:
            self.connection.execute("ROLLBACK")
            raise


class _Context:
    def __init__(self, storage: _Storage) -> None:
        self.storage = storage


class _RpcEnv:
    def __init__(self) -> None:
        self.LOCAL_AGENT_BROKER_AUTHORITY_REF = RPC_AUTHORITY_REF
        self.LOCAL_AGENT_BROKER_PEPPER = RPC_PEPPER
        self.LOCAL_AGENT_BROKER_STATE = None


def _rpc_broker() -> object:
    return broker_worker.LocalAgentBrokerDurableObject(_Context(_Storage()), _RpcEnv())


def _rpc_payload(**overrides) -> dict:
    payload = {
        "session_id": RPC_SESSION_ID,
        "binding_ref": RPC_BINDING_REF,
        "credential_b64": base64.b64encode(RPC_CREDENTIAL).decode("ascii"),
    }
    payload.update(overrides)
    for key, value in list(payload.items()):
        if value is None:
            del payload[key]
    return payload


def _provision_rpc_device(durable_object, *, now: datetime) -> None:
    registered = asyncio.run(
        durable_object.register_binding(
            {
                "binding_ref": RPC_BINDING_REF,
                "device_id": "device.session-auth.rpc.1",
                "account_ref": RPC_ACCOUNT_REF,
                "workspace_ref": RPC_WORKSPACE_REF,
                "credential_b64": base64.b64encode(RPC_CREDENTIAL).decode("ascii"),
                "now": now.isoformat(),
            }
        )
    )
    assert registered["ok"] is True
    opened = asyncio.run(
        durable_object.open_session(
            {
                "session_id": RPC_SESSION_ID,
                "binding_ref": RPC_BINDING_REF,
                "credential_b64": base64.b64encode(RPC_CREDENTIAL).decode("ascii"),
                "account_ref": RPC_ACCOUNT_REF,
                "workspace_ref": RPC_WORKSPACE_REF,
                "now": now.isoformat(),
                "ttl_seconds": 900,
            }
        )
    )
    assert opened["ok"] is True


def test_runtime_rpc_authenticates_a_current_device_session() -> None:
    durable_object = _rpc_broker()
    # The runtime authenticates against its own server clock, so the fixture
    # provisions relative to the real current time.
    now = datetime.now(timezone.utc)
    _provision_rpc_device(durable_object, now=now)

    result = asyncio.run(durable_object.authenticate_device_session(_rpc_payload()))

    assert result["ok"] is True
    projection = result["device_session"]
    assert projection["authenticated"] is True
    assert projection["account_ref"] == RPC_ACCOUNT_REF
    assert projection["workspace_ref"] == RPC_WORKSPACE_REF
    assert projection["session_id"] == RPC_SESSION_ID
    assert projection["raw_device_credential"] is False


def test_runtime_rpc_refuses_every_deny_with_one_uniform_code() -> None:
    durable_object = _rpc_broker()
    now = datetime.now(timezone.utc)
    _provision_rpc_device(durable_object, now=now)

    # Well-formed requests that fail authentication all deny with the one
    # uniform code: wrong credential, unknown session, unknown binding.
    denials = [
        _rpc_payload(credential_b64=base64.b64encode(b"wrong-credential").decode("ascii")),
        _rpc_payload(session_id="sess.session-auth.unknown"),
        _rpc_payload(binding_ref="bind.session-auth.unknown"),
    ]
    for payload in denials:
        result = asyncio.run(durable_object.authenticate_device_session(payload))
        assert result["ok"] is False
        assert result["error"]["code"] == "device_session_auth_failed"
        assert RPC_ACCOUNT_REF not in str(result)


def test_runtime_rpc_refuses_malformed_requests_before_authentication() -> None:
    durable_object = _rpc_broker()
    _provision_rpc_device(durable_object, now=datetime.now(timezone.utc))

    # Malformed request shapes are refused as requests, before the verifier.
    malformed = [
        _rpc_payload(credential_b64="not-valid-base64!!!"),
        _rpc_payload(credential_b64=""),
        _rpc_payload(credential_b64=None),
        {},
        _rpc_payload(user_id="usr_attacker"),
        _rpc_payload(account_ref="usr_attacker"),
        _rpc_payload(workspace_ref="ws_attacker"),
        _rpc_payload(tenant="tenant_attacker"),
        _rpc_payload(product="product_attacker"),
    ]
    for payload in malformed:
        if payload.get("credential_b64") is None and "credential_b64" in payload:
            del payload["credential_b64"]
        result = asyncio.run(durable_object.authenticate_device_session(payload))
        assert result["ok"] is False, payload
        assert result["error"]["code"] == "invalid_device_session_auth_request"
        assert RPC_ACCOUNT_REF not in str(result)


def test_runtime_rpc_accepts_exactly_the_closed_key_set() -> None:
    durable_object = _rpc_broker()
    _provision_rpc_device(durable_object, now=datetime.now(timezone.utc))

    # No caller-supplied identity key exists: extra keys fail closed, and none
    # of them could alter the derived owner or scope even if present.
    for hostile in (
        _rpc_payload(user_id="usr_attacker"),
        _rpc_payload(account_ref="usr_attacker"),
        _rpc_payload(workspace_ref="ws_attacker"),
        _rpc_payload(tenant="tenant_attacker"),
        _rpc_payload(product="product_attacker"),
    ):
        result = asyncio.run(durable_object.authenticate_device_session(hostile))
        assert result["ok"] is False


def test_runtime_rpc_revocation_denies_immediately() -> None:
    durable_object = _rpc_broker()
    now = datetime.now(timezone.utc)
    _provision_rpc_device(durable_object, now=now)

    first = asyncio.run(durable_object.authenticate_device_session(_rpc_payload()))
    assert first["ok"] is True
    revoked = asyncio.run(
        durable_object.revoke_binding({"binding_ref": RPC_BINDING_REF, "now": (now + timedelta(seconds=2)).isoformat()})
    )
    assert revoked["ok"] is True
    second = asyncio.run(durable_object.authenticate_device_session(_rpc_payload()))
    assert second["ok"] is False
    assert second["error"]["code"] == "device_session_auth_failed"


def test_runtime_rpc_does_not_mutate_canonical_state() -> None:
    durable_object = _rpc_broker()
    _provision_rpc_device(durable_object, now=datetime.now(timezone.utc))
    before = durable_object._state_port.load(authority_ref=RPC_AUTHORITY_REF)

    asyncio.run(durable_object.authenticate_device_session(_rpc_payload()))
    asyncio.run(durable_object.authenticate_device_session(_rpc_payload(credential_b64="not-valid-base64!!!")))

    after = durable_object._state_port.load(authority_ref=RPC_AUTHORITY_REF)
    assert after.version == before.version
    assert after.snapshot == before.snapshot


def test_worker_entrypoints_expose_the_same_read_only_rpc() -> None:
    """The Default gateway forwards the RPC; the DO surface stays read-only."""

    assert callable(getattr(broker_worker.Default, "authenticate_device_session", None))
    assert callable(getattr(broker_worker.LocalAgentBrokerDurableObject, "authenticate_device_session", None))
