"""#13 (skerishKang/lovetree-4.0) — LoveTree 제품 등록과 세션 격리.

`lovetree-4-0`을 검토된 제품 경계에 추가한 결과를 고정한다. 경계는 이 저장소의
검토된 제품 집합을 소스에서 바꾸는 한 곳(`identity_authority_worker._ALLOWED_PRODUCTS`)이고,
`CONTROL_PLANE_ALLOWED_PRODUCTS` env는 이 집합과 다를 때 구조 자체를 거부한다.
Chat·Claw 제품 ID를 전용하지 않고 새 제품 항목만 더한다.

Covered:

- REVIEWED_SET_PINNED: the allowlist is exactly the three reviewed products
- REGISTERED_LINK_ACCEPTED: forward link creation works for lovetree-4-0
- REGISTERED_SESSION_ACCEPTED: a product-scoped session is minted and resolved
- CROSS_PRODUCT_ISOLATION: a b62 session never resolves to the LoveTree lane
  and the reverse link read stays product-scoped
- UNREGISTERED_PRODUCT_REJECTED: a product outside the set still fails closed
- RPC payload stays closed: no extra key is accepted on the link RPC
"""

from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import sqlite3
import sys
import types
from datetime import datetime, timedelta, timezone

PACKAGE_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

LOOKUP_KEY_BYTES = b"R" * 32
B62 = "b62"
B54 = "b54-padiem-claw"
LOVETREE = "lovetree-4-0"
LOVETREE_USER = "usr_" + "7" * 32
B62_USER = "usr_" + "1" * 32
NOW = datetime(2026, 10, 27, 6, 0, tzinfo=timezone.utc)


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
    "padiem_identity_authority_worker_lovetree_test", PACKAGE_ROOT / "identity_authority_worker.py"
)
assert _worker_spec is not None and _worker_spec.loader is not None
_worker_mod = importlib.util.module_from_spec(_worker_spec)
sys.modules[_worker_spec.name] = _worker_mod
_worker_spec.loader.exec_module(_worker_mod)

from identity_authority_durable import CloudflareCanonicalIdentityAuthorityStore  # noqa: E402
from padiem_control_plane.contracts import SubjectType  # noqa: E402


class _Cursor:
    def __init__(self, rows) -> None:
        self._rows = rows

    def toArray(self):
        return list(self._rows)


class _Sql:
    def __init__(self, connection) -> None:
        self._connection = connection

    def exec(self, statement, *args):
        cursor = self._connection.execute(statement, args)
        if cursor.description is not None:
            columns = [item[0] for item in cursor.description]
            return _Cursor([dict(zip(columns, row, strict=True)) for row in cursor.fetchall()])
        return _Cursor([])


class _Storage:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:", isolation_level=None)
        self.sql = _Sql(self.connection)

    def transactionSync(self, operation):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            result = operation()
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        self.connection.execute("COMMIT")
        return result


class _Tokens:
    def __init__(self) -> None:
        self.count = 0

    def __call__(self, bytes_count: int) -> str:
        self.count += 1
        return f"{self.count:0{bytes_count * 2}x}"[-bytes_count * 2:]


def authority():
    """Real store gated by the reviewed product set, reached through the RPC methods."""
    storage = _Storage()
    do = _worker_mod.CanonicalIdentityDurableObject.__new__(_worker_mod.CanonicalIdentityDurableObject)
    do._store = CloudflareCanonicalIdentityAuthorityStore(
        storage,
        lookup_key=LOOKUP_KEY_BYTES,
        allowed_product_ids=_worker_mod._ALLOWED_PRODUCTS,
        random_hex=_Tokens(),
    )
    return do


def run(coroutine):
    return asyncio.run(coroutine)


def link_rpc(do, *, product, user, provider_subject):
    return run(do.resolve_or_create_product_link({
        "product_id": product,
        "product_user_id": user,
        "auth_provider": "password",
        "provider_subject": provider_subject,
    }))


def test_reviewed_product_set_is_pinned() -> None:
    assert _worker_mod._ALLOWED_PRODUCTS == frozenset({B62, B54, LOVETREE})


def test_lovetree_forward_link_is_accepted_by_the_authority() -> None:
    do = authority()
    result = link_rpc(do, product=LOVETREE, user=LOVETREE_USER, provider_subject="google-subject-1")
    assert result["ok"] is True
    assert result["link"]["product_id"] == LOVETREE
    assert result["link"]["state"] == "active"


def test_lovetree_session_is_minted_and_resolved_for_its_own_product() -> None:
    do = authority()
    created = link_rpc(do, product=LOVETREE, user=LOVETREE_USER, provider_subject="google-subject-1")
    subject_id = created["link"]["canonical_subject_id"]

    established = run(do.establish_auth_session({
        "product_id": LOVETREE,
        "subject": {"subject_type": SubjectType.USER.value, "subject_id": subject_id},
        "authenticated_at": NOW.isoformat(),
        "not_after": (NOW + timedelta(hours=2)).isoformat(),
    }))
    assert established["ok"] is True
    session_id = established["session"]["session_id"]
    assert established["session"]["product_id"] == LOVETREE

    resolved = run(do.resolve_auth_session({"session_id": session_id}))
    assert resolved["ok"] is True
    assert resolved["session"]["product_id"] == LOVETREE
    assert resolved["session"]["subject"]["subject_id"] == subject_id
    assert resolved["session"]["state"] == "active"

    reverse = run(do.resolve_product_user_for_subject({
        "product_id": LOVETREE,
        "canonical_subject_id": subject_id,
    }))
    assert reverse["ok"] is True
    assert reverse["product_user_id"] == LOVETREE_USER


def test_a_b62_session_never_resolves_into_the_lovetree_lane() -> None:
    do = authority()
    b62_link = link_rpc(do, product=B62, user=B62_USER, provider_subject="google-subject-2")
    b62_session = run(do.establish_auth_session({
        "product_id": B62,
        "subject": {"subject_type": SubjectType.USER.value, "subject_id": b62_link["link"]["canonical_subject_id"]},
        "authenticated_at": NOW.isoformat(),
        "not_after": (NOW + timedelta(hours=2)).isoformat(),
    }))

    cross = run(do.resolve_product_user_for_subject({
        "product_id": LOVETREE,
        "canonical_subject_id": b62_link["link"]["canonical_subject_id"],
    }))
    assert cross["ok"] is False
    assert "product_user_id" not in cross
    assert isinstance(cross["error"]["code"], str) and cross["error"]["code"]

    resolved = run(do.resolve_auth_session({"session_id": b62_session["session"]["session_id"]}))
    assert resolved["session"]["product_id"] == B62


def test_products_outside_the_reviewed_set_stay_closed() -> None:
    do = authority()
    for rejected in ("lovetree-4-0-admin", "b63", ""):
        result = link_rpc(do, product=rejected, user="usr_" + "5" * 32, provider_subject="subject-x")
        assert result["ok"] is False, rejected


def test_link_rpc_payload_stays_closed() -> None:
    do = authority()
    result = run(do.resolve_or_create_product_link({
        "product_id": LOVETREE,
        "product_user_id": LOVETREE_USER,
        "auth_provider": "password",
        "provider_subject": "google-subject-1",
        "email": "someone@example.test",
    }))
    assert result["ok"] is False
    assert "link" not in result
    # 같은 페이로드에서 email만 뺀 요청은 성공한다: 닫힌 키셋이 실제 문지기다.
    assert link_rpc(do, product=LOVETREE, user=LOVETREE_USER, provider_subject="google-subject-1")["ok"] is True
