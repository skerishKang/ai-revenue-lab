"""#7604 PR 1 — 계정 권위가 "이 계정 번호는 정상 탈퇴로 지워졌다"를 답하는 읽기 전용 판정.

탈퇴의 마지막 단계가 실패하면 공통 로그인에는 옛 계정 번호를 가리키는 기록이
남는다. 공통 로그인이 그 번호를 들고 물었을 때 권위가 답하는 한 값을 고정한다:
그 번호가 지금 없고, 계정 삭제 감사 기록에 있다.

저장소 시험은 저장소가 내보내는 SQL 문장을 그대로 sqlite3에서 실행하고, RPC
시험은 실제 Durable Object 생성자로 만든 객체를 부른다.

Covered:

- TRUE_AFTER_LAST_LINK: remove_product_link 로 마지막 연결이 제거된 번호만 참
- FALSE_OTHERWISE: 살아 있는 번호, 발급된 적 없는 번호, 삭제 기록 없이 사라진
  번호는 거짓이고, 다른 번호의 삭제 기록으로는 참이 되지 않는다
- SAME_JUDGEMENT: remove_product_link 가 "이미 삭제됨"이라고 답하는 것과 정확히
  같은 순간에 참과 거짓이 갈린다 (같은 해시, 같은 보존 기간)
- UNCHANGED_REBIND: 재로그인 판정(identity_rebind_forbidden)은 그대로다
- CLOSED_INPUT: 입력은 계정 번호 하나, 답은 한 값
- READ_ONLY: 답하든 거부하든 어느 표도 바뀌지 않는다
- ONE_CALLER_DOOR: 이름 붙은 전용 진입점으로만 닿고, 기본 바인딩과 서명된 내부
  진입(HTTPS)으로는 닿지 않는다
"""

from __future__ import annotations

import ast
import base64
import hashlib
import json
import pathlib
import sys
import time
import types
import uuid
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from test_internal_rpc_ingress import (  # noqa: E402
    ADAPTER_ROOT,
    SECRET,
    _env,
    _load_worker,
    _Namespace,
    _Request,
    _run,
    _signed_request,
    _Stub,
)
from test_lovetree_identity_registration import (  # noqa: E402
    B54,
    B62,
    _Storage,
    _Tokens,
    _worker_mod,
    run,
)

from identity_authority_durable import CloudflareCanonicalIdentityAuthorityStore  # noqa: E402
from identity_authority_rpc_closure import CLOSED_IDENTITY_RPC_METHODS  # noqa: E402
from padiem_control_plane.contracts import ControlPlaneContractError  # noqa: E402

RPC = "resolve_subject_removed_by_account_deletion"
ENTRYPOINT = "CommonLoginDeletionRecord"
ANSWER = "removed_by_account_deletion"
DEPLOYED_PRODUCTS = "b62,b54-padiem-claw,lovetree-4-0,b61"
_KEY = base64.urlsafe_b64encode(b"K" * 32).decode("ascii").rstrip("=")
T0 = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)
RETENTION = timedelta(days=365)
USER_A = "usr_" + "a" * 32
USER_B = "usr_" + "b" * 32
USER_C = "usr_" + "c" * 32
NEVER_ISSUED = "sub_" + "f" * 32


def subject_hash(subject: str) -> str:
    return hashlib.sha256(subject.encode("utf-8")).hexdigest()


def tables(storage) -> dict[str, list[tuple]]:
    """Every table of the store, every row, in storage order."""
    names = [
        row[0]
        for row in storage.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
    ]
    return {
        name: storage.connection.execute(
            f"SELECT rowid, * FROM {name} ORDER BY rowid"
        ).fetchall()
        for name in names
    }


# --- the store, on its own SQL ----------------------------------------------


def real_store():
    storage = _Storage()
    store = CloudflareCanonicalIdentityAuthorityStore(
        storage,
        lookup_key=b"K" * 32,
        allowed_product_ids=frozenset({B62, B54}),
        random_hex=_Tokens(),
    )
    return store, storage


def link(store, *, user, person, product=B62, now=T0) -> str:
    return store.resolve_or_create_product_link(
        product_id=product,
        product_user_id=user,
        auth_provider="google",
        provider_subject=person,
        now=now,
    ).canonical_subject_id


def leave(store, *, subject, user, product=B62, now=T0) -> dict:
    return store.remove_product_link(
        product_id=product,
        product_user_id=user,
        canonical_subject_id=subject,
        account_deletion_operation_id=str(uuid.uuid4()),
        now=now,
    )


def removed(store, subject, *, now=T0) -> bool:
    answer = store.subject_removed_by_account_deletion(canonical_subject_id=subject, now=now)
    assert isinstance(answer, bool)
    return answer


# --- TRUE_AFTER_LAST_LINK ---------------------------------------------------


def test_a_number_removed_with_its_last_link_reads_true() -> None:
    store, storage = real_store()
    subject = link(store, user=USER_A, person="person-a")
    assert removed(store, subject) is False

    result = leave(store, subject=subject, user=USER_A)
    assert result["common_account_deleted"] is True and result["already_deleted"] is False

    assert removed(store, subject) is True
    assert removed(store, subject, now=T0 + timedelta(days=30)) is True
    # The audit holds the hash the removal wrote; the number itself is nowhere.
    assert storage.connection.execute(
        "SELECT user_id_hash FROM canonical_account_deletion_audit"
    ).fetchall() == [(subject_hash(subject),)]
    assert subject not in repr(tables(storage))


def test_a_number_reads_false_while_any_product_link_is_left() -> None:
    store, _storage = real_store()
    subject = link(store, user=USER_A, person="person-a")
    assert link(store, user=USER_A, person="person-a", product=B54) == subject
    assert removed(store, subject) is False

    first = leave(store, subject=subject, user=USER_A, product=B62)
    assert first["common_account_deleted"] is False and first["remaining_links"] == 1
    assert removed(store, subject) is False

    last = leave(store, subject=subject, user=USER_A, product=B54)
    assert last["common_account_deleted"] is True
    assert removed(store, subject) is True


# --- FALSE_OTHERWISE --------------------------------------------------------


def test_a_number_that_was_never_issued_reads_false() -> None:
    store, _storage = real_store()
    assert removed(store, NEVER_ISSUED) is False

    subject = link(store, user=USER_A, person="person-a")
    leave(store, subject=subject, user=USER_A)
    assert removed(store, subject) is True
    # A store that does hold a deletion still has none for this number.
    assert removed(store, NEVER_ISSUED) is False


def test_another_numbers_deletion_record_never_answers_for_this_one() -> None:
    store, storage = real_store()
    gone = link(store, user=USER_A, person="person-a")
    alive = link(store, user=USER_B, person="person-b")
    assert gone != alive
    leave(store, subject=gone, user=USER_A)

    assert removed(store, gone) is True
    assert removed(store, alive) is False
    for near_miss in (gone + "0", gone[:-1], gone.upper(), "sub_" + gone):
        assert removed(store, near_miss) is False, near_miss

    leave(store, subject=alive, user=USER_B)
    assert removed(store, alive) is True
    assert removed(store, gone) is True
    assert sorted(
        row[0]
        for row in storage.connection.execute(
            "SELECT user_id_hash FROM canonical_account_deletion_audit"
        )
    ) == sorted([subject_hash(gone), subject_hash(alive)])


def test_a_number_missing_without_a_deletion_record_reads_false() -> None:
    store, storage = real_store()
    subject = link(store, user=USER_A, person="person-a")
    # Gone for some other reason: the rows are absent, account deletion never ran.
    storage.connection.execute(
        "DELETE FROM canonical_product_identity_link WHERE canonical_subject_id=?", (subject,)
    )
    storage.connection.execute(
        "DELETE FROM canonical_identity_subject WHERE canonical_subject_id=?", (subject,)
    )
    assert removed(store, subject) is False


def test_a_live_number_reads_false_even_beside_a_deletion_record_with_its_hash() -> None:
    store, storage = real_store()
    subject = link(store, user=USER_A, person="person-a")
    storage.connection.execute(
        "INSERT INTO canonical_account_deletion_audit (user_id_hash, deleted_at) VALUES (?, ?)",
        (subject_hash(subject), "2026-11-01T09:00:00Z"),
    )
    # The audit-only read says "recorded"; this answer needs the number gone as well.
    assert store.account_deletion_recorded(canonical_subject_id=subject) is True
    assert removed(store, subject) is False


# --- SAME_JUDGEMENT ---------------------------------------------------------


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (timedelta(0), True),
        (RETENTION - timedelta(seconds=1), True),
        (RETENTION, True),
        (RETENTION + timedelta(seconds=1), False),
        (RETENTION + timedelta(days=30), False),
    ],
)
def test_the_answer_turns_false_exactly_when_removal_stops_calling_it_deleted(age, expected) -> None:
    store, storage = real_store()
    subject = link(store, user=USER_A, person="person-a")
    leave(store, subject=subject, user=USER_A, now=T0)
    at = T0 + age
    before = tables(storage)

    assert removed(store, subject, now=at) is expected
    # Expired or not, the read left the audit row where it was.
    assert tables(storage) == before

    # remove_product_link's own judgement at the same instant.
    try:
        again = leave(store, subject=subject, user=USER_A, now=at)
    except ControlPlaneContractError as exc:
        assert exc.code == "canonical_subject_not_found"
        already_deleted = False
    else:
        already_deleted = again["already_deleted"] is True
    assert already_deleted is expected


# --- CLOSED_INPUT (store) ---------------------------------------------------


@pytest.mark.parametrize("bad", [None, 7, b"sub_1", "", " ", "sub_1 ", "sub/1", "-sub", "s" * 129])
def test_a_malformed_number_is_refused_not_answered(bad) -> None:
    store, _storage = real_store()
    with pytest.raises(ControlPlaneContractError) as refused:
        store.subject_removed_by_account_deletion(canonical_subject_id=bad, now=T0)
    assert refused.value.code == "invalid_identity_authority"


def test_the_instant_judged_must_be_timezone_aware() -> None:
    store, _storage = real_store()
    with pytest.raises(ControlPlaneContractError) as refused:
        store.subject_removed_by_account_deletion(
            canonical_subject_id=NEVER_ISSUED, now=datetime(2026, 11, 1, 9, 0)
        )
    assert refused.value.code == "invalid_identity_authority"


# --- READ_ONLY (store) ------------------------------------------------------


def test_the_read_issues_selects_only_and_changes_no_table(monkeypatch) -> None:
    store, storage = real_store()
    live = link(store, user=USER_A, person="person-a")
    gone = link(store, user=USER_B, person="person-b")
    expired = link(store, user=USER_C, person="person-c")
    leave(store, subject=gone, user=USER_B, now=T0)
    leave(store, subject=expired, user=USER_C, now=T0 - RETENTION - timedelta(days=35))

    statements: list[str] = []
    real_exec = storage.sql.exec

    def recording_exec(statement, *args):
        statements.append(statement)
        return real_exec(statement, *args)

    def no_transaction(_operation):
        raise AssertionError("the read must not open a write transaction")

    monkeypatch.setattr(storage.sql, "exec", recording_exec)
    monkeypatch.setattr(storage, "transactionSync", no_transaction)
    before, changes = tables(storage), storage.connection.total_changes

    assert removed(store, live) is False
    assert removed(store, gone) is True
    assert removed(store, expired) is False
    assert removed(store, NEVER_ISSUED) is False
    for bad in (None, "", "sub/1"):
        with pytest.raises(ControlPlaneContractError):
            store.subject_removed_by_account_deletion(canonical_subject_id=bad, now=T0)

    assert statements
    assert all(statement.lstrip().upper().startswith("SELECT ") for statement in statements)
    assert tables(storage) == before
    assert storage.connection.total_changes == changes
    # The expired row is still stored: leaving it out of the answer pruned nothing.
    assert storage.connection.execute(
        "SELECT count(*) FROM canonical_account_deletion_audit"
    ).fetchone() == (2,)


def removal_says_deleted(store, subject: str, at: datetime) -> bool:
    """remove_product_link's own judgement at ``at``: already deleted, or not found."""
    try:
        again = leave(store, subject=subject, user=USER_A, now=at)
    except ControlPlaneContractError as exc:
        assert exc.code == "canonical_subject_not_found"
        return False
    return again["already_deleted"] is True


@pytest.mark.parametrize("deleted_us", [0, 1, 500_000, 999_999])
@pytest.mark.parametrize(
    "asked_after",
    [
        RETENTION - timedelta(microseconds=1),
        RETENTION,
        RETENTION + timedelta(microseconds=1),
        RETENTION + timedelta(seconds=1),
    ],
)
def test_the_answer_and_removal_agree_at_every_instant_around_the_window(deleted_us, asked_after) -> None:
    store, _storage = real_store()
    subject = link(store, user=USER_A, person="person-a")
    deleted = T0 + timedelta(microseconds=deleted_us)
    leave(store, subject=subject, user=USER_A, now=deleted)
    at = deleted + asked_after
    assert removed(store, subject, now=at) is removal_says_deleted(store, subject, at)


# --- the authority, through its Durable Object ------------------------------


class _AlarmStorage(_Storage):
    """The shared fixture storage plus the alarm calls account deletion schedules."""

    def __init__(self) -> None:
        super().__init__()
        self.alarm_calls: list[str] = []

    async def deleteAlarm(self) -> None:
        self.alarm_calls.append("delete")

    async def setAlarm(self, _at) -> None:
        self.alarm_calls.append("set")


def authority():
    """The real Durable Object, built by its own constructor from a deployed-style env."""
    ctx = types.SimpleNamespace(storage=_AlarmStorage())
    env = types.SimpleNamespace(
        CONTROL_PLANE_ALLOWED_PRODUCTS=DEPLOYED_PRODUCTS,
        CONTROL_PLANE_IDENTITY_LOOKUP_KEY=_KEY,
        GOOGLE_CONNECT_TICKET_KEY=_KEY,
    )
    return _worker_mod.CanonicalIdentityDurableObject(ctx, env)


def rpc_link(do, *, user, person, product=B62, expected=None) -> dict:
    payload = {
        "product_id": product,
        "product_user_id": user,
        "auth_provider": "google",
        "provider_subject": person,
    }
    if expected is not None:
        payload["expected_canonical_subject_id"] = expected
    return run(do.resolve_or_create_product_link(payload))


def rpc_subject(do, **kwargs) -> str:
    result = rpc_link(do, **kwargs)
    assert result["ok"] is True, result
    return result["link"]["canonical_subject_id"]


def rpc_leave(do, *, subject, user, product=B62) -> dict:
    result = run(do.remove_product_link({
        "product_id": product,
        "product_user_id": user,
        "canonical_subject_id": subject,
        "account_deletion_operation_id": str(uuid.uuid4()),
    }))
    assert result["ok"] is True, result
    return result


def ask(do, payload):
    return run(getattr(do, RPC)(payload))


def answer_for(do, subject):
    result = ask(do, {"canonical_subject_id": subject})
    assert set(result) == {"ok", ANSWER}, result
    assert result["ok"] is True and isinstance(result[ANSWER], bool)
    return result[ANSWER]


def test_the_authority_answers_one_value_for_one_number() -> None:
    do = authority()
    gone = rpc_subject(do, user=USER_A, person="person-a")
    alive = rpc_subject(do, user=USER_B, person="person-b")
    assert answer_for(do, gone) is False

    assert rpc_leave(do, subject=gone, user=USER_A)["common_account_deleted"] is True

    assert answer_for(do, gone) is True
    assert answer_for(do, alive) is False
    assert answer_for(do, NEVER_ISSUED) is False


def test_the_rebind_refusal_is_unchanged_and_the_answer_names_its_cause() -> None:
    do = authority()
    old = rpc_subject(do, user=USER_A, person="person-a")
    rpc_leave(do, subject=old, user=USER_A)

    # Login with the old number as the expected one is refused exactly as before.
    for expected in (old, NEVER_ISSUED):
        refused = rpc_link(do, user=USER_A, person="person-a", expected=expected)
        assert refused == {
            "ok": False,
            "error": {
                "code": "identity_rebind_forbidden",
                "message": "Canonical identity request was rejected",
            },
        }
    # Only the authority's answer tells the two numbers apart.
    assert answer_for(do, old) is True
    assert answer_for(do, NEVER_ISSUED) is False

    # A first login without an expected number is given a new number, as before;
    # the old number keeps reading as removed, the new one does not.
    fresh = rpc_subject(do, user=USER_A, person="person-a")
    assert fresh != old
    assert answer_for(do, old) is True
    assert answer_for(do, fresh) is False


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        "sub_" + "f" * 32,
        {},
        {"subject_id": NEVER_ISSUED},
        {"canonical_subject_id": NEVER_ISSUED, "now": "2026-11-01T09:00:00Z"},
        {"canonical_subject_id": NEVER_ISSUED, "product_id": "b62"},
        {"canonical_subject_id": NEVER_ISSUED, "user_id_hash": subject_hash(NEVER_ISSUED)},
        {"canonical_subject_id": None},
        {"canonical_subject_id": 7},
        {"canonical_subject_id": ""},
        {"canonical_subject_id": "sub/1"},
    ],
)
def test_the_input_is_the_number_alone(payload) -> None:
    do = authority()
    result = ask(do, payload)
    assert result["ok"] is False
    assert set(result) == {"ok", "error"}
    assert result["error"]["code"] in {"invalid_identity_authority_rpc", "invalid_identity_authority"}
    assert result["error"]["message"] == "Canonical identity request was rejected"
    assert ANSWER not in repr(result)


def test_asking_changes_no_table_and_schedules_nothing() -> None:
    do = authority()
    storage = do._storage
    alive = rpc_subject(do, user=USER_A, person="person-a")
    gone = rpc_subject(do, user=USER_B, person="person-b")
    rpc_leave(do, subject=gone, user=USER_B)
    # An audit row past the retention window that no alarm has removed yet.
    expired = "sub_" + "e" * 32
    storage.connection.execute(
        "INSERT INTO canonical_account_deletion_audit (user_id_hash, deleted_at) VALUES (?, ?)",
        (subject_hash(expired), "2020-01-01T00:00:00Z"),
    )
    before, changes = tables(storage), storage.connection.total_changes
    alarms = list(storage.alarm_calls)

    assert answer_for(do, alive) is False
    assert answer_for(do, gone) is True
    assert answer_for(do, expired) is False
    assert answer_for(do, NEVER_ISSUED) is False
    for bad in (None, {}, {"canonical_subject_id": "sub/1"}):
        assert ask(do, bad)["ok"] is False

    assert tables(storage) == before
    assert storage.connection.total_changes == changes
    assert storage.alarm_calls == alarms
    assert storage.connection.execute(
        "SELECT count(*) FROM canonical_account_deletion_audit"
    ).fetchone() == (2,)


# --- ONE_CALLER_DOOR --------------------------------------------------------


def _com2_methods() -> frozenset[str]:
    """COM2_IDENTITY_RPC_METHODS, read from source (the module needs a web stack)."""
    source = (ADAPTER_ROOT / "com2_identity_rpc_ingress.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "COM2_IDENTITY_RPC_METHODS"
            for target in node.targets
        ):
            value = node.value
            while isinstance(value, ast.Call) and value.args:
                value = value.args[0]
            return frozenset(ast.literal_eval(value)) - CLOSED_IDENTITY_RPC_METHODS
    raise AssertionError("COM2_IDENTITY_RPC_METHODS not found")


def test_only_the_common_login_entrypoint_reaches_the_answer() -> None:
    module = _load_worker(
        ADAPTER_ROOT / "identity_authority_worker.py", "identity_worker_deletion_record_test"
    )
    door = getattr(module, ENTRYPOINT)
    assert issubclass(door, module.WorkerEntrypoint) and door is not module.Default
    assert [name for name in vars(door) if not name.startswith("_")] == [RPC]
    assert module.ACCOUNT_DELETION_RECORD_ENTRYPOINT == ENTRYPOINT
    assert module.ACCOUNT_DELETION_RECORD_CALLER == "padiem-auth"
    assert module.ACCOUNT_DELETION_RECORD_RETENTION_DAYS == RETENTION.days
    assert module.ACCOUNT_DELETION_RECORD_RPC_WRITES is False

    # The named entrypoint forwards to the one authority object, end to end.
    do = authority()
    old = rpc_subject(do, user=USER_A, person="person-a")
    rpc_leave(do, subject=old, user=USER_A)
    reached = door(env=_env(CONTROL_PLANE_IDENTITY=_Namespace(do)))
    assert _run(getattr(reached, RPC)({"canonical_subject_id": old})) == {"ok": True, ANSWER: True}

    # Every other bound Worker holds the default entrypoint (or the account-block
    # notifier); neither carries the method.
    stub = _Stub({"ok": True, ANSWER: True})
    for other in (module.Default, module.BlockNotifier):
        assert not hasattr(other, RPC), other
        with pytest.raises(AttributeError):
            getattr(other(env=_env(CONTROL_PLANE_IDENTITY=_Namespace(stub))), RPC)
    assert module.ACCOUNT_DELETION_RECORD_RPC_ON_DEFAULT_ENTRYPOINT is False

    # Neither signed HTTPS door lists it.
    assert RPC not in module.IDENTITY_RPC_INGRESS_METHODS
    assert RPC not in _com2_methods()
    assert module.ACCOUNT_DELETION_RECORD_RPC_ON_HTTPS_INGRESS is False


def test_an_unauthenticated_or_signed_https_call_is_refused_and_never_dispatched() -> None:
    module = _load_worker(
        ADAPTER_ROOT / "identity_authority_worker.py", "identity_worker_deletion_record_https_test"
    )
    # The answer exists behind the named entrypoint ...
    door = getattr(module, ENTRYPOINT)
    forwarded = _Stub({"ok": True, ANSWER: False})
    payload = {"canonical_subject_id": NEVER_ISSUED}
    assert _run(getattr(door(env=_env(CONTROL_PLANE_IDENTITY=_Namespace(forwarded))), RPC)(payload)) == {
        "ok": True, ANSWER: False,
    }
    assert forwarded.calls == [(RPC, payload)]

    # ... and no HTTPS request reaches it, signed or not.
    stub = _Stub({"ok": True, ANSWER: True})
    body = ('{"canonical_subject_id":"' + NEVER_ISSUED + '"}').encode("ascii")
    now = int(time.time())
    closed = module.Default(env=_env(CONTROL_PLANE_IDENTITY=_Namespace(stub)))
    response = _run(closed.fetch(_signed_request(method=RPC, body=body, at=now)))
    assert response.status == 404 and response.body == "Not Found"

    worker = module.Default(env=_env(
        CONTROL_PLANE_IDENTITY=_Namespace(stub), PADIEM_IDENTITY_RPC_INGRESS_SECRET=SECRET))
    path = "/internal/rpc/" + RPC
    for request in (
        _Request("https://identity.invalid" + path, headers={}, body=body),
        _signed_request(method=RPC, body=body, at=now, secret="wrong-secret-0123456789abcdef"),
        _signed_request(method=RPC, body=body, at=now),
    ):
        response = _run(worker.fetch(request))
        assert response.status == 404
        assert json.loads(response.body)["error"]["code"] == "rpc_unknown_method"
    assert stub.calls == []
