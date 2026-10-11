"""#3247 — read-only reverse product-user resolution.

`resolve_product_user_for_subject` answers exactly one question for the
server-owned background owner lane: which product user is linked to this
canonical subject for this product. Forward link creation stays exclusively
with `resolve_or_create_product_link`; this suite proves the reverse path is
read-only and fails closed on every non-canonical outcome.

Covered:

- RESOLVES_ACTIVE_LINK: the ACTIVE link's product user is returned
- ONE_ACTIVE_AMONG_REVOKED: a revoked sibling does not block the one ACTIVE link
- MISSING_LINK_FAILS_CLOSED
- INACTIVE_LINK_FAILS_CLOSED
- AMBIGUOUS_ACTIVE_LINKS_FAIL: two ACTIVE links -> storage error
- CORRUPT_STATE_FAILS / CORRUPT_USER_FAILS: malformed rows are corruption
- UNKNOWN_PRODUCT rejected by the allowlist
- MALFORMED_SUBJECT rejected; a well-shaped unknown subject fails closed
- CROSS_PRODUCT: the B62 lookup returns the B62 link, never the B54 one
- READ_ONLY: no new table, no row change, no second store
- RPC closed payload: exactly product_id + canonical_subject_id, nothing else
- RPC gateway exposes the new method
"""

from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import sys
import types
from datetime import datetime, timezone

import pytest

from identity_authority_durable import (
    CloudflareCanonicalIdentityAuthorityStore,
)
from padiem_control_plane.contracts import (
    ControlPlaneContractError,
    IdentityLinkState,
)

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
LOOKUP_KEY_BYTES = b"R" * 32
B54 = "b54-padiem-claw"
B62 = "b62"
USER = "usr_" + "1" * 32
OTHER_USER = "usr_" + "9" * 32
UNKNOWN_SUBJECT = "sub_" + "d" * 32
PACKAGE_ROOT = pathlib.Path(__file__).resolve().parents[1]


class FakeCursor:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def toArray(self) -> list[dict]:
        return list(self._rows)


class FakeSql:
    def __init__(self, connection) -> None:
        self._connection = connection

    def exec(self, statement: str, *args):
        cursor = self._connection.execute(statement, args)
        if cursor.description is not None:
            columns = [item[0] for item in cursor.description]
            return FakeCursor([dict(zip(columns, row, strict=True)) for row in cursor.fetchall()])
        return FakeCursor([])


class FakeStorage:
    def __init__(self) -> None:
        import sqlite3

        self.connection = sqlite3.connect(":memory:", isolation_level=None)
        self.sql = FakeSql(self.connection)

    def transactionSync(self, operation):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            result = operation()
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        self.connection.execute("COMMIT")
        return result

    def count(self, table: str) -> int:
        return int(self.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])

    def tables(self) -> set[str]:
        return {
            str(row[0])
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

    def exec_direct(self, statement: str, *args) -> None:
        self.connection.execute(statement, args)


class TokenSource:
    def __init__(self) -> None:
        self.count = 0

    def __call__(self, bytes_count: int) -> str:
        self.count += 1
        return f"{self.count:0{bytes_count * 2}x}"[-bytes_count * 2 :]


def fixture(*, products=frozenset({B62, B54})):
    storage = FakeStorage()
    store = CloudflareCanonicalIdentityAuthorityStore(
        storage,
        lookup_key=LOOKUP_KEY_BYTES,
        allowed_product_ids=products,
        random_hex=TokenSource(),
    )
    return store, storage


def link(store, *, product=B62, user=USER, provider_subject="ps-1"):
    """Create one forward link through the only reviewed writer."""

    return store.resolve_or_create_product_link(
        product_id=product,
        product_user_id=user,
        auth_provider="google",
        provider_subject=provider_subject,
        now=NOW,
    )


# ── durable store: the reverse read ─────────────────────────────────────────


def test_resolves_the_active_link_for_the_exact_product_and_subject() -> None:
    store, _ = fixture()
    created = link(store)
    assert created.state is IdentityLinkState.ACTIVE

    resolved = store.resolve_product_user_for_subject(
        product_id=B62, canonical_subject_id=created.canonical_subject_id
    )
    assert resolved == USER


def test_one_active_link_among_revoked_siblings_resolves() -> None:
    store, storage = fixture()
    created = link(store, provider_subject="ps-shared")
    link(store, user=OTHER_USER, provider_subject="ps-shared")
    storage.exec_direct(
        "UPDATE canonical_product_identity_link SET state='revoked' "
        "WHERE product_user_id=?",
        OTHER_USER,
    )

    resolved = store.resolve_product_user_for_subject(
        product_id=B62, canonical_subject_id=created.canonical_subject_id
    )
    assert resolved == USER


def test_missing_link_fails_closed() -> None:
    store, _ = fixture()
    with pytest.raises(ControlPlaneContractError) as err:
        store.resolve_product_user_for_subject(
            product_id=B62, canonical_subject_id=UNKNOWN_SUBJECT
        )
    assert err.value.code == "canonical_product_identity_link_not_found"


def test_inactive_link_fails_closed() -> None:
    store, storage = fixture()
    created = link(store)
    storage.exec_direct(
        "UPDATE canonical_product_identity_link SET state='revoked' "
        "WHERE product_user_id=?",
        USER,
    )
    with pytest.raises(ControlPlaneContractError) as err:
        store.resolve_product_user_for_subject(
            product_id=B62, canonical_subject_id=created.canonical_subject_id
        )
    assert err.value.code == "canonical_product_identity_link_not_active"


def test_ambiguous_active_links_fail_as_storage_error() -> None:
    store, _ = fixture()
    created = link(store, provider_subject="ps-shared")
    link(store, user=OTHER_USER, provider_subject="ps-shared")
    with pytest.raises(ControlPlaneContractError) as err:
        store.resolve_product_user_for_subject(
            product_id=B62, canonical_subject_id=created.canonical_subject_id
        )
    assert err.value.code == "identity_authority_storage_error"


def test_corrupt_link_state_fails_as_storage_error() -> None:
    store, storage = fixture()
    created = link(store)
    storage.exec_direct(
        "UPDATE canonical_product_identity_link SET state='not-a-state' "
        "WHERE product_user_id=?",
        USER,
    )
    with pytest.raises(ControlPlaneContractError) as err:
        store.resolve_product_user_for_subject(
            product_id=B62, canonical_subject_id=created.canonical_subject_id
        )
    assert err.value.code == "identity_authority_storage_error"


def test_corrupt_link_user_fails_as_storage_error() -> None:
    store, storage = fixture()
    created = link(store)
    storage.exec_direct(
        "UPDATE canonical_product_identity_link SET product_user_id='' "
        "WHERE canonical_subject_id=?",
        created.canonical_subject_id,
    )
    with pytest.raises(ControlPlaneContractError) as err:
        store.resolve_product_user_for_subject(
            product_id=B62, canonical_subject_id=created.canonical_subject_id
        )
    assert err.value.code == "identity_authority_storage_error"


def test_unknown_product_is_rejected_by_the_allowlist() -> None:
    store, _ = fixture()
    with pytest.raises(ControlPlaneContractError) as err:
        store.resolve_product_user_for_subject(
            product_id="b99", canonical_subject_id=UNKNOWN_SUBJECT
        )
    assert err.value.code == "identity_authority_product_mismatch"


def test_malformed_subject_is_rejected_by_the_exact_subject_check() -> None:
    store, _ = fixture()
    with pytest.raises(ControlPlaneContractError) as err:
        store.resolve_product_user_for_subject(product_id=B62, canonical_subject_id="")
    assert err.value.code == "invalid_identity_authority"


def test_well_shaped_unknown_subject_fails_closed_without_disclosure() -> None:
    store, _ = fixture()
    # The store's subject check is the bounded safe-id check; a subject that
    # passes it but has no link fails closed exactly like a missing link.
    with pytest.raises(ControlPlaneContractError) as err:
        store.resolve_product_user_for_subject(
            product_id=B62, canonical_subject_id="sub_" + "z" * 32
        )
    assert err.value.code == "canonical_product_identity_link_not_found"


def test_b62_lookup_never_returns_the_b54_link() -> None:
    store, _ = fixture()
    # One canonical subject, linked in BOTH products: the product argument is
    # the only thing separating the two answers.
    created = link(store, product=B62, user=USER, provider_subject="ps-shared")
    link(store, product=B54, user=OTHER_USER, provider_subject="ps-shared")

    resolved = store.resolve_product_user_for_subject(
        product_id=B62, canonical_subject_id=created.canonical_subject_id
    )
    assert resolved == USER
    cross = store.resolve_product_user_for_subject(
        product_id=B54, canonical_subject_id=created.canonical_subject_id
    )
    assert cross == OTHER_USER


def test_reverse_read_is_strictly_read_only() -> None:
    store, storage = fixture()
    created = link(store)
    tables_before = storage.tables()
    rows_before = storage.count("canonical_product_identity_link")

    store.resolve_product_user_for_subject(
        product_id=B62, canonical_subject_id=created.canonical_subject_id
    )

    assert storage.tables() == tables_before
    assert storage.count("canonical_product_identity_link") == rows_before
    assert storage.tables() == {
        "canonical_identity_subject",
        "canonical_product_identity_link",
        "canonical_auth_session",
        "canonical_tenant",
        "canonical_tenant_membership",
        "identity_authority_schema",
    }


# ── worker RPC shape ────────────────────────────────────────────────────────


class _RecordingStore:
    def __init__(self, product_user_id: str | None, *, error: str | None = None):
        self.product_user_id = product_user_id
        self.error = error
        self.calls: list[dict] = []

    def resolve_product_user_for_subject(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None or self.product_user_id is None:
            from padiem_control_plane.contracts import ControlPlaneContractError

            raise ControlPlaneContractError(
                self.error or "canonical_product_identity_link_not_found",
                "no such link",
            )
        return self.product_user_id


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

_worker_spec = importlib.util.spec_from_file_location(
    "padiem_identity_authority_worker_3247_test",
    PACKAGE_ROOT / "identity_authority_worker.py",
)
assert _worker_spec is not None and _worker_spec.loader is not None
_worker_mod = importlib.util.module_from_spec(_worker_spec)
sys.modules[_worker_spec.name] = _worker_mod
_worker_spec.loader.exec_module(_worker_mod)


def _do_rpc(store):
    do = _worker_mod.CanonicalIdentityDurableObject.__new__(
        _worker_mod.CanonicalIdentityDurableObject
    )
    do._store = store
    return do


def _run(coro):
    """This package has no pytest-asyncio, so coroutines run explicitly."""

    return asyncio.run(coro)


def test_rpc_returns_the_linked_product_user() -> None:
    store = _RecordingStore(USER)
    result = _run(
        _do_rpc(store).resolve_product_user_for_subject(
            {"product_id": B62, "canonical_subject_id": UNKNOWN_SUBJECT}
        )
    )
    assert result == {"ok": True, "product_user_id": USER}
    assert store.calls == [
        {"product_id": B62, "canonical_subject_id": UNKNOWN_SUBJECT}
    ]


@pytest.mark.parametrize(
    "extra",
    [
        {"product_user_id": USER},
        {"auth_provider": "google"},
        {"provider_subject": "ps-1"},
        {"owner_ref": "owner:opaque:1"},
        {"now": NOW.isoformat()},
        {"state": "active"},
    ],
)
def test_rpc_refuses_any_caller_supplied_identity_field(extra) -> None:
    store = _RecordingStore(USER)
    result = _run(
        _do_rpc(store).resolve_product_user_for_subject(
            {"product_id": B62, "canonical_subject_id": UNKNOWN_SUBJECT, **extra}
        )
    )
    assert result["ok"] is False
    assert "product_user_id" not in result
    assert store.calls == [], "a rejected payload must not reach the store"


def test_rpc_missing_required_field_fails_closed() -> None:
    store = _RecordingStore(USER)
    for payload in ({"product_id": B62}, {"canonical_subject_id": UNKNOWN_SUBJECT}, {}):
        result = _run(_do_rpc(store).resolve_product_user_for_subject(payload))
        assert result["ok"] is False
    assert store.calls == []


def test_rpc_reports_missing_link_without_disclosure() -> None:
    store = _RecordingStore(None)
    result = _run(
        _do_rpc(store).resolve_product_user_for_subject(
            {"product_id": B62, "canonical_subject_id": UNKNOWN_SUBJECT}
        )
    )
    assert result["ok"] is False
    assert "product_user_id" not in result


def test_gateway_exposes_the_reverse_resolver() -> None:
    assert hasattr(_worker_mod.Default, "resolve_product_user_for_subject")
    assert _worker_mod.READ_ONLY_REVERSE_PRODUCT_LINK_RESOLVER is True
    assert _worker_mod.REVERSE_PRODUCT_LINK_CREATES_LINK is False
    assert _worker_mod.REVERSE_PRODUCT_LINK_ACCEPTS_PROVIDER_SUBJECT is False
    assert _worker_mod.REVERSE_PRODUCT_LINK_ACCEPTS_OWNER_REF is False
