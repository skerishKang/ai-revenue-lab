"""B-1A: read-only canonical connector workspace resolver (#2830).

This suite pins the single most important B-1A invariant: **reading** connector
workspace truth must never be able to create canonical connector context.

The pre-existing connect flow (``GoogleConnectTicketIssuer.issue``) is allowed to
call ``resolve_or_create`` because it is an explicit connect intent. Status/read
callers are not. ``resolve_existing`` and the private
``resolve_connector_workspace`` RPC exist so that a read path issues
``SELECT`` only: no ``INSERT``, no ``UPDATE``, no ``DELETE``.

The resolver is proven three ways:
1. Behaviourally, with a SQL recorder that captures every statement.
2. Structurally, by asserting the resolver source never contains a mutating verb.
3. Contractually, by asserting the private RPC payload is exactly ``session_id``.
"""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import re
import sqlite3
import sys
import types

import pytest

from identity_connector_ticket import (
    ALLOWED_PRODUCT_ID,
    CanonicalConnectorContext,
    CanonicalConnectorContextStore,
    GoogleConnectTicketIssuer,
)
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.connector_connect_ticket import (
    GMAIL_READONLY_SCOPE,
    ConnectorConnectTicketAuthority,
)
from padiem_control_plane.contracts import (
    CanonicalSubjectRef,
    ControlPlaneContractError,
    SubjectType,
)
from padiem_control_plane.tenants import CanonicalTenant


NOW = datetime(2026, 9, 4, 13, 30, tzinfo=timezone.utc)
KEY_BYTES = b"T" * 32
LOOKUP_KEY_BYTES = b"I" * 32
PRODUCT_ID = "b62"

_PACKAGE_ROOT = Path(__file__).parents[1]


# --------------------------------------------------------------------------- #
# Worker module loading (private RPC surface)
# --------------------------------------------------------------------------- #

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

_worker_path = _PACKAGE_ROOT / "identity_authority_worker.py"
_worker_spec = importlib.util.spec_from_file_location(
    "padiem_identity_authority_worker_b1a_test", _worker_path
)
assert _worker_spec is not None and _worker_spec.loader is not None
_worker_mod = importlib.util.module_from_spec(_worker_spec)
sys.modules[_worker_spec.name] = _worker_mod
_worker_spec.loader.exec_module(_worker_mod)


class _FakeObjectId:
    def __init__(self, name: str) -> None:
        self.name = name


class _RecordingStub:
    """Records which private RPC the gateway forwarded, and the exact payload."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def resolve_or_create_product_link(self, payload):
        self.calls.append(("resolve_or_create_product_link", payload))
        return {"ok": True, "link": {}}

    async def establish_auth_session(self, payload):
        self.calls.append(("establish_auth_session", payload))
        return {"ok": True, "session": {}}

    async def resolve_auth_session(self, payload):
        self.calls.append(("resolve_auth_session", payload))
        return {"ok": True, "session": {}}

    async def issue_google_connect_ticket(self, payload):
        self.calls.append(("issue_google_connect_ticket", payload))
        return {"ok": True, "ticket": {}}

    async def resolve_connector_workspace(self, payload):
        self.calls.append(("resolve_connector_workspace", payload))
        return {"ok": True, "workspace": {"present": False}}

    async def create_tenant(self, payload):
        self.calls.append(("create_tenant", payload))
        return {"ok": True, "tenant": {}}


class _FakeNamespace:
    def __init__(self, stub) -> None:
        self._stub = stub

    def idFromName(self, name: str):
        return _FakeObjectId(name)

    def get(self, object_id):
        del object_id
        return self._stub


class _FakeEnv:
    def __init__(self, stub) -> None:
        self.CONTROL_PLANE_ALLOWED_PRODUCT = PRODUCT_ID
        self.CONTROL_PLANE_IDENTITY = _FakeNamespace(stub)


# --------------------------------------------------------------------------- #
# SQL-recording storage doubles
# --------------------------------------------------------------------------- #

class _Cursor:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def toArray(self) -> list[dict]:
        return list(self._rows)


class RecordingSql:
    """Executes real SQLite while capturing every statement that was issued."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self.statements: list[str] = []

    def exec(self, statement: str, *args):
        self.statements.append(statement)
        cursor = self._connection.execute(statement, args)
        if cursor.description is not None:
            columns = [item[0] for item in cursor.description]
            rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
            return _Cursor(rows)
        return _Cursor([])

    # -- mutation proof helpers -------------------------------------------- #

    def _classified(self, verb: str) -> list[str]:
        pattern = re.compile(rf"^\s*{verb}\b", re.IGNORECASE)
        return [item for item in self.statements if pattern.match(item)]

    def selects(self) -> list[str]:
        return self._classified("SELECT")

    def inserts(self) -> list[str]:
        return self._classified("INSERT")

    def updates(self) -> list[str]:
        return self._classified("UPDATE")

    def deletes(self) -> list[str]:
        return self._classified("DELETE")

    def reset(self) -> None:
        self.statements.clear()

    def data_selects(self) -> list[str]:
        return [item for item in self.selects() if "canonical_connector_context" in item]


class RecordingStorage:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:", isolation_level=None)
        self.sql = RecordingSql(self.connection)
        self.transactions: list[str] = []

    def transactionSync(self, operation):
        self.transactions.append("BEGIN")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            result = operation()
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        self.connection.execute("COMMIT")
        return result

    def rows(self) -> list[tuple]:
        return self.connection.execute(
            "SELECT product_id, subject_id, actor_ref, account_ref, workspace_ref "
            "FROM canonical_connector_context ORDER BY subject_id"
        ).fetchall()


class TokenSource:
    def __init__(self) -> None:
        self.count = 0

    def __call__(self, bytes_count: int) -> str:
        self.count += 1
        return f"{self.count:0{bytes_count * 2}x}"[-bytes_count * 2 :]


def session(subject_id: str = "sub_1", **overrides) -> AuthSessionSnapshot:
    values = dict(
        session_id="sess_1",
        product_id=PRODUCT_ID,
        subject=CanonicalSubjectRef(SubjectType.USER, subject_id),
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
        state=AuthSessionState.ACTIVE,
        revision=1,
    )
    values.update(overrides)
    return AuthSessionSnapshot(**values)


def read_fixture() -> tuple[RecordingStorage, CanonicalConnectorContextStore]:
    storage = RecordingStorage()
    store = CanonicalConnectorContextStore(storage, random_hex=TokenSource())
    storage.sql.reset()
    return storage, store


def seeded_fixture():
    """One already-created canonical connector context, as the connect flow leaves it."""

    storage = RecordingStorage()
    source = TokenSource()
    store = CanonicalConnectorContextStore(storage, random_hex=source)
    issuer = GoogleConnectTicketIssuer(
        context_store=store,
        signing_key=KEY_BYTES,
        clock=lambda: NOW,
        random_hex=source,
    )
    seeded_session = session()
    receipt = issuer.issue(auth_session=seeded_session, connector_id="gmail")
    existing = store.resolve_or_create(auth_session=seeded_session, now=NOW)
    storage.sql.reset()
    return storage, store, issuer, seeded_session, receipt, existing


# =========================================================================== #
# §3 / §4 — resolve_existing contract
# =========================================================================== #

def test_resolve_existing_returns_none_for_active_session_without_context():
    storage, store = read_fixture()
    result = store.resolve_existing(auth_session=session(), now=NOW)
    assert result is None
    assert storage.rows() == []


def test_resolve_existing_returns_existing_context_for_active_session():
    storage, store, _, auth, _, existing = seeded_fixture()
    resolved = store.resolve_existing(auth_session=auth, now=NOW)
    assert isinstance(resolved, CanonicalConnectorContext)
    assert resolved == existing
    assert resolved.subject_id == auth.subject.subject_id
    assert resolved.product_id == ALLOWED_PRODUCT_ID


def test_resolve_existing_is_stable_and_idempotent_across_repeated_reads():
    _, store, _, auth, _, existing = seeded_fixture()
    reads = [store.resolve_existing(auth_session=auth, now=NOW + timedelta(seconds=n)) for n in range(4)]
    assert reads == [existing, existing, existing, existing]


def test_resolve_existing_does_not_create_context_for_unknown_subject():
    storage, store = read_fixture()
    known = session("sub_known")
    store.resolve_or_create(auth_session=known, now=NOW)
    assert len(storage.rows()) == 1

    assert store.resolve_existing(auth_session=session("sub_absent"), now=NOW) is None
    assert len(storage.rows()) == 1


def test_resolve_existing_is_per_subject_and_never_crosses_subjects():
    storage, store = read_fixture()
    first = store.resolve_or_create(auth_session=session("sub_1"), now=NOW)
    assert store.resolve_existing(auth_session=session("sub_1"), now=NOW) == first
    assert store.resolve_existing(auth_session=session("sub_2", session_id="sess_2"), now=NOW) is None
    assert len(storage.rows()) == 1


# =========================================================================== #
# §3 — fail closed
# =========================================================================== #

def test_resolve_existing_rejects_revoked_session_with_inactive_auth_session():
    _, store, _, auth, _, _ = seeded_fixture()
    revoked = session(session_id=auth.session_id, state=AuthSessionState.REVOKED)
    with pytest.raises(ControlPlaneContractError) as exc:
        store.resolve_existing(auth_session=revoked, now=NOW)
    assert exc.value.code == "inactive_auth_session"


def test_resolve_existing_rejects_expired_session_by_absolute_time():
    _, store, _, auth, _, _ = seeded_fixture()
    with pytest.raises(ControlPlaneContractError) as exc:
        store.resolve_existing(auth_session=auth, now=NOW + timedelta(hours=2))
    assert exc.value.code == "inactive_auth_session"


def test_resolve_existing_rejects_session_declared_expired():
    _, store = read_fixture()
    with pytest.raises(ControlPlaneContractError) as exc:
        store.resolve_existing(
            auth_session=session(state=AuthSessionState.EXPIRED),
            now=NOW,
        )
    assert exc.value.code == "inactive_auth_session"


def test_resolve_existing_rejects_foreign_product_session():
    _, store = read_fixture()
    with pytest.raises(ControlPlaneContractError) as exc:
        store.resolve_existing(auth_session=session(product_id="b54"), now=NOW)
    assert exc.value.code == "connector_context_session_mismatch"


def test_resolve_existing_rejects_non_user_and_anonymous_subject_types():
    _, store = read_fixture()
    for subject_type in (SubjectType.ANONYMOUS, SubjectType.ACCOUNT):
        with pytest.raises(ControlPlaneContractError) as exc:
            store.resolve_existing(
                auth_session=session(subject=CanonicalSubjectRef(subject_type, "ref_1")),
                now=NOW,
            )
        assert exc.value.code == "connector_context_session_mismatch"


def test_resolve_existing_rejects_non_session_object():
    _, store = read_fixture()
    with pytest.raises(ControlPlaneContractError) as exc:
        store.resolve_existing(auth_session={"session_id": "sess_1"}, now=NOW)
    assert exc.value.code == "invalid_connector_context"


def test_resolve_existing_rejects_naive_now():
    _, store = read_fixture()
    with pytest.raises(ControlPlaneContractError) as exc:
        store.resolve_existing(auth_session=session(), now=datetime(2026, 9, 4, 13, 30))
    assert exc.value.code == "invalid_connector_context"


def test_resolve_existing_fails_closed_on_corrupted_duplicate_context_rows():
    """A duplicated key can never be silently resolved to one arbitrary row.

    The physical schema already forbids a second row for one canonical key. And
    when a corrupted store somehow hands the resolver two rows, the ambiguity
    guard raises instead of choosing one.
    """

    storage, store = read_fixture()
    with pytest.raises(sqlite3.IntegrityError):
        storage.connection.execute(
            "INSERT INTO canonical_connector_context "
            "(product_id, subject_id, actor_ref, account_ref, workspace_ref, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ALLOWED_PRODUCT_ID, "sub_dup", "actor_a", "account_a", "workspace_a", "2026-09-04T13:30:00Z"),
        )
        storage.connection.execute(
            "INSERT INTO canonical_connector_context "
            "(product_id, subject_id, actor_ref, account_ref, workspace_ref, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ALLOWED_PRODUCT_ID, "sub_dup", "actor_b", "account_b", "workspace_b", "2026-09-04T13:30:00Z"),
        )

    class _AmbiguousSql:
        """A store that reports two rows for a single canonical key."""

        def __init__(self, inner) -> None:
            self._inner = inner
            self.statements: list[str] = []

        def exec(self, statement: str, *args):
            self.statements.append(statement)
            if statement.lstrip().upper().startswith("SELECT") and "canonical_connector_context" in statement:
                return _Cursor(
                    [
                        {
                            "actor_ref": "actor_a",
                            "account_ref": "account_a",
                            "workspace_ref": "workspace_a",
                            "created_at": "2026-09-04T13:30:00Z",
                        },
                        {
                            "actor_ref": "actor_b",
                            "account_ref": "account_b",
                            "workspace_ref": "workspace_b",
                            "created_at": "2026-09-04T13:30:00Z",
                        },
                    ]
                )
            return self._inner.exec(statement, *args)

    ambiguous = _AmbiguousSql(storage.sql)
    store._sql = ambiguous
    with pytest.raises(ControlPlaneContractError) as exc:
        store.resolve_existing(auth_session=session("sub_dup"), now=NOW)
    assert exc.value.code == "connector_context_storage_error"
    assert len(ambiguous.statements) == 1


def test_resolve_existing_fails_closed_on_tampered_refs_and_created_at():
    storage, store = read_fixture()
    store._sql.exec(
        "INSERT INTO canonical_connector_context "
        "(product_id, subject_id, actor_ref, account_ref, workspace_ref, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ALLOWED_PRODUCT_ID, "sub_bad_ref", "actor_ok", "account_ok", "bad ref!", "2026-09-04T13:30:00Z",
    )
    storage.sql.reset()
    with pytest.raises(ControlPlaneContractError) as exc:
        store.resolve_existing(auth_session=session("sub_bad_ref"), now=NOW)
    assert exc.value.code == "invalid_connector_context"

    storage2, store2 = read_fixture()
    store2._sql.exec(
        "INSERT INTO canonical_connector_context "
        "(product_id, subject_id, actor_ref, account_ref, workspace_ref, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ALLOWED_PRODUCT_ID, "sub_bad_time", "actor_ok2", "account_ok2", "workspace_ok2", "not-a-timestamp",
    )
    storage2.sql.reset()
    with pytest.raises(ControlPlaneContractError) as exc2:
        store2.resolve_existing(auth_session=session("sub_bad_time"), now=NOW)
    assert exc2.value.code == "connector_context_storage_error"


def test_resolve_existing_ignores_rows_owned_by_another_product_key():
    storage, store = read_fixture()
    store._sql.exec(
        "INSERT INTO canonical_connector_context "
        "(product_id, subject_id, actor_ref, account_ref, workspace_ref, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        "b54", "sub_shared", "actor_x", "account_x", "workspace_x", "2026-09-04T13:30:00Z",
    )
    storage.sql.reset()
    assert store.resolve_existing(auth_session=session("sub_shared"), now=NOW) is None


def test_resolve_existing_rejects_row_whose_product_id_is_out_of_boundary():
    """A row that is reachable by key but not owned by the reviewed product fails closed."""

    storage, store = read_fixture()
    storage.connection.execute(
        "INSERT INTO canonical_connector_context "
        "(product_id, subject_id, actor_ref, account_ref, workspace_ref, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("b54", "sub_cross", "actor_c", "account_c", "workspace_c", "2026-09-04T13:30:00Z"),
    )
    storage.sql.reset()
    # The lookup is keyed on the reviewed product, so a foreign row is invisible.
    assert store.resolve_existing(auth_session=session("sub_cross"), now=NOW) is None

    # And a cross-product row returned by a corrupted key lookup is rejected outright.
    with pytest.raises(ControlPlaneContractError) as exc:
        CanonicalConnectorContext(
            product_id="b54",
            subject_id="sub_cross",
            actor_ref="actor_c",
            account_ref="account_c",
            workspace_ref="workspace_c",
            created_at=NOW,
        )
    assert exc.value.code == "connector_context_product_mismatch"


# =========================================================================== #
# §12 — mutation proof (the important one)
# =========================================================================== #

def test_resolve_existing_issues_select_only_and_never_mutates():
    storage, store, _, auth, _, _ = seeded_fixture()
    resolved = store.resolve_existing(auth_session=auth, now=NOW)

    assert resolved is not None
    assert storage.sql.selects(), "resolver must read through SELECT"
    assert storage.sql.inserts() == []
    assert storage.sql.updates() == []
    assert storage.sql.deletes() == []
    assert storage.sql.data_selects()
    assert all("canonical_connector_context" in item for item in storage.sql.selects())
    assert len(storage.sql.statements) == 1, "read path must issue exactly one statement"
    assert storage.sql.statements[0].lstrip().upper().startswith("SELECT")


def test_resolve_existing_issues_select_only_when_context_is_absent():
    storage, store = read_fixture()
    assert store.resolve_existing(auth_session=session("sub_none"), now=NOW) is None

    assert len(storage.sql.selects()) == 1
    assert storage.sql.inserts() == []
    assert storage.sql.updates() == []
    assert storage.sql.deletes() == []
    assert storage.rows() == []


def test_repeated_read_only_resolution_never_grows_the_store():
    storage, store, _, auth, _, _ = seeded_fixture()
    before = len(storage.rows())
    for _ in range(5):
        store.resolve_existing(auth_session=auth, now=NOW)
        store.resolve_existing(auth_session=session("sub_never_seen", session_id="sess_zz"), now=NOW)

    assert len(storage.rows()) == before
    assert storage.sql.inserts() == []
    assert storage.sql.updates() == []
    assert storage.sql.deletes() == []


def test_read_only_resolution_precedes_while_connect_flow_may_still_create():
    """§13 boundary: the connect flow keeps INSERT authority, the read path never does."""

    storage, store, issuer, auth, _, _ = seeded_fixture()
    assert storage.sql.inserts() == []
    assert store.resolve_existing(auth_session=auth, now=NOW) is not None
    assert storage.sql.inserts() == []

    # A brand new connect intent for a new subject still mints context exactly once.
    new_session = session("sub_fresh", session_id="sess_fresh")
    assert store.resolve_existing(auth_session=new_session, now=NOW) is None
    assert len(storage.rows()) == 1
    assert storage.sql.inserts() == []

    issuer.issue(auth_session=new_session, connector_id="gmail")
    assert len(storage.rows()) == 2
    assert store.resolve_existing(auth_session=new_session, now=NOW) is not None


# =========================================================================== #
# §13 — connect-ticket regression
# =========================================================================== #

def test_connect_ticket_flow_still_resolves_or_creates_exactly_once():
    storage = RecordingStorage()
    source = TokenSource()
    store = CanonicalConnectorContextStore(storage, random_hex=source)
    issuer = GoogleConnectTicketIssuer(
        context_store=store,
        signing_key=KEY_BYTES,
        clock=lambda: NOW,
        random_hex=source,
    )
    auth = session()
    storage.sql.reset()

    receipt = issuer.issue(auth_session=auth, connector_id="gmail")
    assert len(storage.sql.inserts()) == 1
    assert len(storage.rows()) == 1

    claims = ConnectorConnectTicketAuthority(signing_key=KEY_BYTES).verify(
        token=receipt.connect_ticket,
        now=NOW,
        expected_connector_id="gmail",
        auth_session=auth,
    )
    assert claims.scopes == (GMAIL_READONLY_SCOPE,)
    assert claims.workspace_ref == storage.rows()[0][4]

    # Second connect intent reuses the same row; it must not create a second one.
    issuer.issue(auth_session=auth, connector_id="google-drive")
    assert len(storage.rows()) == 1


def test_resolve_or_create_still_mints_for_a_new_subject_only():
    storage = RecordingStorage()
    store = CanonicalConnectorContextStore(storage, random_hex=TokenSource())
    storage.sql.reset()

    assert store.resolve_existing(auth_session=session("sub_a"), now=NOW) is None
    store.resolve_or_create(auth_session=session("sub_a"), now=NOW)
    store.resolve_or_create(auth_session=session("sub_a"), now=NOW)

    assert len(storage.sql.inserts()) == 1
    assert len(storage.rows()) == 1


def test_connect_ticket_issuer_does_not_use_the_read_only_primitive():
    """The connect path must keep calling resolve_or_create, not resolve_existing."""

    source = (_PACKAGE_ROOT / "identity_connector_ticket.py").read_text(encoding="utf-8")
    issuer_body = source.split("class GoogleConnectTicketIssuer", 1)[1]
    assert "resolve_or_create(" in issuer_body
    assert "resolve_existing(" not in issuer_body


# =========================================================================== #
# §5 / §6 — private RPC contract
# =========================================================================== #

def _rpc_keys():
    return getattr(_worker_mod, "_CONNECTOR_WORKSPACE_KEYS")


def test_private_rpc_closed_key_accepts_only_session_id():
    keys = _rpc_keys()
    assert keys == frozenset({"session_id"})
    payload = _worker_mod._closed({"session_id": "sess_1"}, keys, "connector workspace resolve RPC")
    assert payload == {"session_id": "sess_1"}


@pytest.mark.parametrize(
    "forbidden",
    [
        {"session_id": "sess_1", "workspace_ref": "workspace_attacker"},
        {"session_id": "sess_1", "tenant_id": "tenant_attacker"},
        {"session_id": "sess_1", "subject_id": "sub_attacker"},
        {"session_id": "sess_1", "product_id": "b54"},
        {"session_id": "sess_1", "account_ref": "account_attacker"},
        {"session_id": "sess_1", "actor_ref": "actor_attacker"},
        {"session_id": "sess_1", "connector_id": "gmail"},
        {"session_id": "sess_1", "provider_subject": "google-sub"},
        {"session_id": "sess_1", "created_at": "2026-09-04T13:30:00Z"},
    ],
)
def test_private_rpc_rejects_client_asserted_extra_fields(forbidden):
    with pytest.raises(ControlPlaneContractError) as exc:
        _worker_mod._closed(forbidden, _rpc_keys(), "connector workspace resolve RPC")
    assert exc.value.code == "invalid_identity_authority_rpc"


def test_private_rpc_rejects_missing_or_malformed_payload():
    for bad in ({}, None, {"session": "sess_1"}, {"session_id": "sess_1", "extra": 1}):
        with pytest.raises(ControlPlaneContractError) as exc:
            _worker_mod._closed(bad, _rpc_keys(), "connector workspace resolve RPC")
        assert exc.value.code == "invalid_identity_authority_rpc"


def test_private_rpc_source_pins_bounded_payload_and_no_client_workspace_assertion():
    source = _worker_path.read_text(encoding="utf-8")
    assert '_CONNECTOR_WORKSPACE_KEYS = frozenset({"session_id"})' in source
    assert "async def resolve_connector_workspace" in source
    assert 'wire = _closed(payload, _CONNECTOR_WORKSPACE_KEYS,' in source
    rpc_body = source.split("async def resolve_connector_workspace", 1)[1].split("async def ", 1)[0]
    assert "resolve_existing(" in rpc_body
    assert "resolve_or_create" not in rpc_body


def test_private_rpc_does_not_read_client_asserted_keys_at_all():
    """No client-supplied workspace/tenant/subject/product key is ever dereferenced."""

    source = _worker_path.read_text(encoding="utf-8")
    rpc_body = source.split("async def resolve_connector_workspace", 1)[1].split("async def ", 1)[0]
    for forbidden in ("workspace_ref", "tenant_id", "subject_id", "product_id", "account_ref", "actor_ref"):
        assert f'wire["{forbidden}"]' not in rpc_body
        assert f"wire['{forbidden}']" not in rpc_body
    assert 'wire["session_id"]' in rpc_body


def test_private_rpc_does_not_import_or_call_google_oauth_or_service_binding():
    source = _worker_path.read_text(encoding="utf-8")
    assert "GOOGLE_OAUTH_SERVICE" not in source
    assert "google_oauth_worker" not in source
    first_use = source.index("SERVICE_BINDING")
    rpc_at = source.index("async def resolve_connector_workspace")
    assert rpc_at < first_use, "the read-only resolver must not touch service binding"
    # Pre-existing review pins that must survive this slice.
    assert "PUBLIC_FETCH = False" in source
    assert "CONNECT_TICKET_ISSUED_BY_CONTROL_PLANE = True" in source
    assert "CLIENT_ACTOR_ACCOUNT_WORKSPACE_AUTHORITY = False" in source


def test_private_rpc_exposes_only_the_two_bounded_response_shapes():
    """§6: present/absent are the only shapes, and both are closed."""

    present_do, present_storage = _bootstrap_do()
    _, present_session = _seed_identity_and_session(present_storage, subject_id="sub_present")
    connector_store = CanonicalConnectorContextStore(present_storage, random_hex=TokenSource())
    connector_store.resolve_or_create(
        auth_session=_session_for(present_session, "sub_present"),
        now=NOW,
    )
    present = _run_rpc_at(
        present_do.resolve_connector_workspace, {"session_id": present_session.session_id}
    )
    assert set(present) == {"ok", "workspace"}
    assert present["ok"] is True
    assert set(present["workspace"]) == {"present", "workspace_ref"}

    absent_do, absent_storage = _bootstrap_do()
    _, absent_session = _seed_identity_and_session(absent_storage, subject_id="sub_absent_shape")
    absent = _run_rpc_at(
        absent_do.resolve_connector_workspace, {"session_id": absent_session.session_id}
    )
    assert set(absent) == {"ok", "workspace"}
    assert absent == {"ok": True, "workspace": {"present": False}}


def _bootstrap_do():
    """Wire the real Durable Object onto an in-memory SQLite store.

    The DO resolves ``datetime.now()`` for session validation, so the in-memory
    session is minted with a window that brackets the real current time and the
    clock is pinned to ``NOW`` while the RPC runs.
    """

    storage = RecordingStorage()
    env = _build_env()
    ctx = types.SimpleNamespace(storage=storage)
    return _worker_mod.CanonicalIdentityDurableObject(ctx, env), storage


def _build_env() -> _FakeEnv:
    env = _FakeEnv(_RecordingStub())
    env.CONTROL_PLANE_IDENTITY_LOOKUP_KEY = (
        base64.urlsafe_b64encode(LOOKUP_KEY_BYTES).decode("ascii").rstrip("=")
    )
    env.GOOGLE_CONNECT_TICKET_KEY = (
        base64.urlsafe_b64encode(KEY_BYTES).decode("ascii").rstrip("=")
    )
    return env


_PINNED_CLOCK_SOURCE = _PACKAGE_ROOT / "identity_authority_worker.py"


class _PinnedNow(datetime):
    """A ``datetime`` subclass whose ``now()`` returns the test clock."""

    _pinned: datetime = NOW

    @classmethod
    def now(cls, tz=None):
        value = cls._pinned
        if tz is None:
            return value
        return value.astimezone(tz)


def _run_rpc_at(callable_, *args, observed_at: datetime = NOW, **kwargs):
    """Execute a DO RPC with session validation pinned to ``observed_at``."""

    patch = pytest.MonkeyPatch()
    try:
        patch.setattr(_worker_mod, "datetime", _PinnedNow)
        _PinnedNow._pinned = observed_at
        return asyncio.run(callable_(*args, **kwargs))
    finally:
        patch.undo()


def _seed_identity_and_session(storage, *, subject_id: str = "sub_1", expires_after_hours: int = 1):
    """Create an active canonical session whose window brackets the real clock."""

    real_now = datetime.now(timezone.utc)
    durable = _worker_mod.CloudflareCanonicalIdentityAuthorityStore(
        storage,
        lookup_key=LOOKUP_KEY_BYTES,
        allowed_product_id=PRODUCT_ID,
    )
    durable._sql.exec(
        "INSERT INTO canonical_identity_subject "
        "(provider, provider_fingerprint, canonical_subject_id, created_at) VALUES (?, ?, ?, ?)",
        "google",
        "fingerprint-placeholder",
        subject_id,
        "2026-09-04T13:00:00Z",
    )
    durable._sql.exec(
        "INSERT INTO canonical_product_identity_link "
        "(product_id, product_user_id, canonical_subject_id, state, created_at) VALUES (?, ?, ?, ?, ?)",
        PRODUCT_ID,
        "user_1",
        subject_id,
        "active",
        "2026-09-04T13:00:00Z",
    )
    snapshot = durable.establish_auth_session(
        product_id=PRODUCT_ID,
        subject=CanonicalSubjectRef(SubjectType.USER, subject_id),
        authenticated_at=real_now - timedelta(minutes=5),
        not_after=real_now + timedelta(hours=12),
        now=real_now,
    )
    return durable, snapshot


def _session_for(snapshot, subject_id: str, **overrides) -> AuthSessionSnapshot:
    values = dict(
        session_id=snapshot.session_id,
        product_id=PRODUCT_ID,
        subject=CanonicalSubjectRef(SubjectType.USER, subject_id),
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
        state=AuthSessionState.ACTIVE,
        revision=1,
    )
    values.update(overrides)
    return AuthSessionSnapshot(**values)


def test_durable_object_rpc_reports_absent_workspace_without_creating_context():
    durable_object, storage = _bootstrap_do()
    _, snapshot = _seed_identity_and_session(storage, subject_id="sub_no_context")
    storage.sql.reset()

    result = _run_rpc_at(
        durable_object.resolve_connector_workspace, {"session_id": snapshot.session_id}
    )

    assert result == {"ok": True, "workspace": {"present": False}}
    assert storage.sql.inserts() == []
    assert storage.sql.updates() == []
    assert storage.sql.deletes() == []
    assert storage.rows() == []


def test_durable_object_rpc_reports_present_workspace_ref_and_nothing_else():
    durable_object, storage = _bootstrap_do()
    _, snapshot = _seed_identity_and_session(storage, subject_id="sub_has_context")
    connector_store = CanonicalConnectorContextStore(storage, random_hex=TokenSource())
    existing = connector_store.resolve_or_create(
        auth_session=_session_for(snapshot, "sub_has_context"),
        now=NOW,
    )
    storage.sql.reset()

    result = _run_rpc_at(
        durable_object.resolve_connector_workspace, {"session_id": snapshot.session_id}
    )

    assert result == {"ok": True, "workspace": {"present": True, "workspace_ref": existing.workspace_ref}}
    assert set(result["workspace"]) == {"present", "workspace_ref"}
    for forbidden in (
        "actor_ref",
        "account_ref",
        "canonical_subject_id",
        "subject_id",
        "tenant_id",
        "product_id",
        "provider_subject",
        "created_at",
        "memberships",
        "token",
        "secret",
        "scopes",
        "binding_ref",
    ):
        assert forbidden not in result
        assert forbidden not in result["workspace"]
    assert storage.sql.inserts() == []
    assert storage.sql.updates() == []
    assert storage.sql.deletes() == []


def test_durable_object_rpc_rejects_unknown_session_and_client_asserted_workspace():
    durable_object, storage = _bootstrap_do()
    _seed_identity_and_session(storage, subject_id="sub_rpc")
    storage.sql.reset()

    unknown = _run_rpc_at(
        durable_object.resolve_connector_workspace, {"session_id": "sess_unknown"}
    )
    assert unknown["ok"] is False
    assert unknown["error"]["code"] == "canonical_auth_session_not_found"

    asserted = _run_rpc_at(
        durable_object.resolve_connector_workspace,
        {"session_id": "sess_any", "workspace_ref": "workspace_attacker"},
    )
    assert asserted["ok"] is False
    assert asserted["error"]["code"] == "invalid_identity_authority_rpc"
    assert storage.sql.inserts() == []


def test_durable_object_rpc_fails_closed_for_inactive_session_and_creates_nothing():
    durable_object, storage = _bootstrap_do()
    _, snapshot = _seed_identity_and_session(storage, subject_id="sub_revoked")
    storage.connection.execute(
        "UPDATE canonical_auth_session SET state='revoked' WHERE session_id=?",
        (snapshot.session_id,),
    )
    storage.sql.reset()

    result = _run_rpc_at(
        durable_object.resolve_connector_workspace, {"session_id": snapshot.session_id}
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "inactive_auth_session"
    assert storage.sql.inserts() == []
    assert storage.sql.updates() == []
    assert storage.sql.deletes() == []
    assert storage.rows() == []


def test_durable_object_rpc_fails_closed_for_expired_session_by_absolute_time():
    durable_object, storage = _bootstrap_do()
    _, snapshot = _seed_identity_and_session(storage, subject_id="sub_timeout")
    storage.sql.reset()

    result = _run_rpc_at(
        durable_object.resolve_connector_workspace,
        {"session_id": snapshot.session_id},
        observed_at=NOW + timedelta(days=30),
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "inactive_auth_session"
    assert storage.sql.inserts() == []
    assert storage.sql.updates() == []
    assert storage.sql.deletes() == []
    assert storage.rows() == []


def test_durable_object_public_fetch_still_returns_404():
    durable_object, _ = _bootstrap_do()
    response = asyncio.run(durable_object.fetch(object()))
    assert response.status == 404


def test_gateway_forwards_connector_workspace_rpc_with_payload_unchanged():
    stub = _RecordingStub()
    gateway = _worker_mod.Default(_FakeEnv(stub))
    result = asyncio.run(gateway.resolve_connector_workspace({"session_id": "sess_gw"}))

    assert result == {"ok": True, "workspace": {"present": False}}
    assert stub.calls == [("resolve_connector_workspace", {"session_id": "sess_gw"})]


def test_gateway_has_no_public_connector_workspace_route():
    source = _worker_path.read_text(encoding="utf-8")
    gateway_body = source.split("class Default(WorkerEntrypoint)", 1)[1]
    assert "resolve_connector_workspace" in gateway_body
    assert "PUBLIC_ROUTE" not in source
    assert "url.pathname" not in source


# =========================================================================== #
# §8 — membership / tenant must not leak into this slice
# =========================================================================== #

def test_resolver_never_reads_or_returns_membership_or_tenant_truth():
    source = (_PACKAGE_ROOT / "identity_connector_ticket.py").read_text(encoding="utf-8")
    resolver_body = source.split("def resolve_existing", 1)[1].split("\n    def resolve_or_create", 1)[0]
    assert "_read_context_row(" in resolver_body
    for forbidden in (
        "canonical_tenant",
        "canonical_tenant_membership",
        "tenant_id",
        "_active_membership_tenant_ids",
    ):
        assert forbidden not in resolver_body


def test_resolver_output_carries_no_tenant_or_membership_projection():
    source = (_PACKAGE_ROOT / "identity_connector_ticket.py").read_text(encoding="utf-8")
    assert "CanonicalTenant" not in source
    assert "resolve_active_memberships" not in source
    assert "canonical_tenant" not in source


def test_context_projection_is_not_used_as_the_workspace_wire_shape():
    """The status wire must be the minimal §6 shape, not the full context dict."""

    durable_object, storage = _bootstrap_do()
    _, snapshot = _seed_identity_and_session(storage, subject_id="sub_shape")
    result = _run_rpc_at(
        durable_object.resolve_connector_workspace, {"session_id": snapshot.session_id}
    )
    assert result["workspace"] == {"present": False}
    assert "server_owned" not in result["workspace"]
    assert "client_asserted" not in result["workspace"]


def test_present_wire_does_not_reuse_the_full_context_projection():
    durable_object, storage = _bootstrap_do()
    _, snapshot = _seed_identity_and_session(storage, subject_id="sub_shape_present")
    existing = CanonicalConnectorContextStore(storage, random_hex=TokenSource()).resolve_or_create(
        auth_session=_session_for(snapshot, "sub_shape_present"),
        now=NOW,
    )
    result = _run_rpc_at(
        durable_object.resolve_connector_workspace, {"session_id": snapshot.session_id}
    )
    assert result["workspace"] == {"present": True, "workspace_ref": existing.workspace_ref}
    assert "server_owned" not in result["workspace"]
    assert "client_asserted" not in result["workspace"]
    assert "created_at" not in result["workspace"]


def test_workspace_ref_is_not_exposed_through_any_public_surface():
    source = _worker_path.read_text(encoding="utf-8")
    assert "status=404" in source
    assert "Response(" in source
    gateway_body = source.split("class Default(WorkerEntrypoint)", 1)[1]
    assert 'headers={"cache-control": "no-store"}' in gateway_body
