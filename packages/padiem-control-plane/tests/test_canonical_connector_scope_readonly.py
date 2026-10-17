"""#4139: never mint PC scope; reuse existing canonical context and membership."""
from datetime import datetime, timezone
import sqlite3

import pytest

from canonical_connector_scope_readonly import (
    PRODUCT_LOCAL_SCOPE_MINTED,
    SCOPE_BRIDGE_WIRED,
    SHARED_SCOPE_AUTHORITY_APPROVED,
    ReadOnlyExistingConnectorScope,
)
from padiem_control_plane.contracts import ControlPlaneContractError

NOW = datetime(2026, 10, 12, 10, tzinfo=timezone.utc)
SUBJECT = "usr_canonical_1"
TENANT = "tenant_canonical_1"


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def toArray(self):
        return self.rows


class Sql:
    def __init__(self, connection):
        self.connection = connection
        self.calls = []

    def exec(self, statement, *params):
        self.calls.append((statement, params))
        raw = self.connection.execute(statement, params)
        cols = [x[0] for x in raw.description] if raw.description else []
        return Cursor([dict(zip(cols, row, strict=True)) for row in raw.fetchall()])


class Storage:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.sql = Sql(self.db)
        self.db.execute(
            "CREATE TABLE canonical_connector_context ("
            "product_id TEXT NOT NULL, subject_id TEXT NOT NULL,"
            "account_ref TEXT NOT NULL, workspace_ref TEXT NOT NULL)"
        )

    def add(self, *, subject=SUBJECT, product="b62", account="account_canonical_1", workspace="workspace_canonical_1"):
        self.db.execute(
            "INSERT INTO canonical_connector_context VALUES (?,?,?,?)",
            (product, subject, account, workspace),
        )


class Members:
    def __init__(self):
        self.called = []
        self.allowed = True

    def resolve_active_tenant_membership(self, *, tenant_id, canonical_subject_id, now):
        self.called.append((tenant_id, canonical_subject_id, now))
        if not self.allowed or tenant_id != TENANT or canonical_subject_id != SUBJECT:
            raise ControlPlaneContractError("canonical_membership_denied", "not allowed")
        return object()


def resolver():
    storage, members = Storage(), Members()
    return ReadOnlyExistingConnectorScope(identity_do_storage=storage, membership_authority=members), storage, members


def test_exact_same_canonical_subject_and_tenant_uses_existing_scope_read_only():
    resolver_port, storage, members = resolver()
    storage.add()
    scope = resolver_port.resolve_scope(subject_id=SUBJECT, tenant_ref=TENANT, now=NOW)
    assert scope.owner_subject_id == SUBJECT
    assert scope.account_ref == "account_canonical_1"
    assert scope.workspace_ref == "workspace_canonical_1"
    assert scope.product_scoped is False
    assert members.called == [(TENANT, SUBJECT, NOW)]
    assert len(storage.sql.calls) == 1
    assert storage.sql.calls[0][0].startswith("SELECT ")
    assert SCOPE_BRIDGE_WIRED is False and SHARED_SCOPE_AUTHORITY_APPROVED is False
    assert PRODUCT_LOCAL_SCOPE_MINTED is False


@pytest.mark.parametrize("subject,tenant", [
    ("usr.other", TENANT), (SUBJECT, "tenant.other"), ("", TENANT), (SUBJECT, None)
])
def test_unreviewed_or_missing_subject_tenant_cannot_resolve_scope(subject, tenant):
    resolver_port, storage, members = resolver()
    storage.add()
    with pytest.raises(ControlPlaneContractError):
        resolver_port.resolve_scope(subject_id=subject, tenant_ref=tenant, now=NOW)
    assert not storage.sql.calls


def test_no_existing_context_fail_closed_never_create():
    resolver_port, storage, members = resolver()
    with pytest.raises(ControlPlaneContractError) as exc:
        resolver_port.resolve_scope(subject_id=SUBJECT, tenant_ref=TENANT, now=NOW)
    assert exc.value.code == "canonical_scope_not_established"
    assert len(storage.sql.calls) == 1
    assert storage.db.execute("SELECT count(*) FROM canonical_connector_context").fetchone()[0] == 0


def test_product_legacy_context_cannot_be_swapped_by_other_product():
    resolver_port, storage, members = resolver()
    storage.add(product="b54-padiem-claw")
    with pytest.raises(ControlPlaneContractError) as exc:
        resolver_port.resolve_scope(subject_id=SUBJECT, tenant_ref=TENANT, now=NOW)
    assert exc.value.code == "canonical_scope_not_established"


def test_ambiguous_context_and_missing_membership_fail_closed():
    resolver_port, storage, members = resolver()
    storage.add()
    storage.add()
    with pytest.raises(ControlPlaneContractError) as exc:
        resolver_port.resolve_scope(subject_id=SUBJECT, tenant_ref=TENANT, now=NOW)
    assert exc.value.code == "canonical_scope_not_established"
    members.allowed = False
    with pytest.raises(ControlPlaneContractError) as exc:
        resolver_port.resolve_scope(subject_id=SUBJECT, tenant_ref=TENANT, now=NOW)
    assert exc.value.code == "canonical_membership_denied"


def test_invalid_clock_refuses_before_any_authority_read():
    resolver_port, storage, members = resolver()
    storage.add()
    with pytest.raises(ControlPlaneContractError):
        resolver_port.resolve_scope(subject_id=SUBJECT, tenant_ref=TENANT, now=datetime(2026,10,12))
    assert not storage.sql.calls and not members.called


class ProxyRow:
    """A deployed-Worker JS proxy row: only to_py() exposes the mapping."""

    def __init__(self, values):
        self._values = values

    def to_py(self):
        return dict(self._values)

    def __iter__(self):
        raise TypeError("proxy rows are not directly mapping-convertible")


class ProxyCursor:
    """A proxy container: toArray() returns a proxy list of proxy rows."""

    def __init__(self, rows):
        self._rows = [ProxyRow(row) for row in rows]

    def toArray(self):
        return ProxyList(self._rows)


class ProxyList:
    def __init__(self, items):
        self._items = items

    def __iter__(self):
        return iter(self._items)

    def __len__(self):
        return len(self._items)

    def __getitem__(self, index):
        return self._items[index]


class ProxySql(Sql):
    def exec(self, statement, *params):
        self.calls.append((statement, params))
        raw = self.connection.execute(statement, params)
        cols = [x[0] for x in raw.description] if raw.description else []
        rows = [dict(zip(cols, row, strict=True)) for row in raw.fetchall()]
        return ProxyCursor(rows)


def proxy_resolver():
    storage = Storage()
    storage.sql = ProxySql(storage.db)
    members = Members()
    return (
        ReadOnlyExistingConnectorScope(identity_do_storage=storage, membership_authority=members),
        storage,
        members,
    )


def test_proxy_container_row_resolves_the_same_established_scope():
    """The SAME healthy single row must resolve whether it is plain or proxied.

    Reproduced live: the deployed Identity Worker returns proxy rows, so the
    plain isinstance() check reported one established row as not established.
    """
    resolver_port, storage, members = proxy_resolver()
    storage.add()

    scope = resolver_port.resolve_scope(subject_id=SUBJECT, tenant_ref=TENANT, now=NOW)

    assert scope.account_ref == "account_canonical_1"
    assert scope.workspace_ref == "workspace_canonical_1"
    assert scope.owner_subject_id == SUBJECT
    assert members.called == [(TENANT, SUBJECT, NOW)]


def test_proxy_shape_never_widens_the_exactly_one_row_requirement():
    resolver_port, storage, _ = proxy_resolver()
    storage.add()
    storage.add()

    with pytest.raises(ControlPlaneContractError) as exc:
        resolver_port.resolve_scope(subject_id=SUBJECT, tenant_ref=TENANT, now=NOW)
    assert exc.value.code == "canonical_scope_not_established"


def test_proxy_shape_with_a_malformed_row_is_refused():
    storage = Storage()

    class _BrokenRow:
        def to_py(self):
            return "not a mapping"

        def __iter__(self):
            raise TypeError("unconvertible proxy row")

    class _BrokenCursor:
        def toArray(self):
            return ProxyList([_BrokenRow()])

    class _BrokenSql(Sql):
        def exec(self, statement, *params):
            del statement, params
            return _BrokenCursor()

    storage.sql = _BrokenSql(storage.db)
    # The port reads sql at construction time, so build it against the broken one.
    resolver_port = ReadOnlyExistingConnectorScope(
        identity_do_storage=storage, membership_authority=Members()
    )
    with pytest.raises(ControlPlaneContractError) as exc:
        resolver_port.resolve_scope(subject_id=SUBJECT, tenant_ref=TENANT, now=NOW)
    assert exc.value.code == "canonical_scope_unavailable"
