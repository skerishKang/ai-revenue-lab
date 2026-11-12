"""#7542 P5-A — 권위의 읽기 커넥터 RPC 계정 열쇠 변형과 공통 판정.

세션 번호 대신 제품 + 계정 번호를 받는 읽기 변형 4개를 실제 Durable Object
생성자와 실제 저장소로 고정한다. 계정 열쇠에는 세션이 싣고 있던 사실(계정
존재, 제품 링크, 테넌트 하나, 검토된 제품)이 없으므로 권위가 호출마다 자기
저장소에서 다시 읽는다.

Covered:

- DEFAULT_OFF: 스위치가 없거나 true가 아니면 네 RPC 모두 닫힌 거부로 답한다
- SESSION_KEY_UNTOUCHED: 세션 열쇠 RPC의 답은 스위치와 무관하게 같다
- SAME_ANSWER_BOTH_KEYS: 같은 계정에 대해 두 열쇠의 답이 같다
- JUDGEMENT_REFUSALS: 링크 없음, 멤버십 0개, 멤버십 2개, 탈퇴 계정, 링크 전용
  제품, 검토되지 않은 제품, OWNER가 아닌 역할이 각각 거부된다
- CLOSED_INPUT: 테넌트·역할·시각·세션을 입력에 넣을 수 없다
- OWN_ACCOUNT_ONLY: 답에는 판정한 계정의 것만 나온다
- READ_ONLY: 통과하든 거부되든 저장소에 아무것도 쓰지 않는다
- PRIVATE_DOORS: 바인딩 진입점과 서명된 내부 진입으로만 닿는다
"""

from __future__ import annotations

import base64
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
    LOVETREE,
    _Storage,
    _worker_mod,
    run,
)

from canonical_connector_account_rpc import (  # noqa: E402
    CONNECTOR_ACCOUNT_KEY_READ_METHODS,
    CONNECTOR_ACCOUNT_KEY_RPC_DISABLED,
    CONNECTOR_ACCOUNT_KEY_RPC_SWITCH,
    judge_connector_account,
)
from padiem_control_plane.contracts import ControlPlaneContractError  # noqa: E402

BOOKAI = "b61"
DEPLOYED_PRODUCTS = "b62,b54-padiem-claw,lovetree-4-0,b61"
NOW = datetime.now(timezone.utc)
_KEY = base64.urlsafe_b64encode(b"K" * 32).decode("ascii").rstrip("=")
USER_A = "usr_" + "a" * 32
USER_B = "usr_" + "b" * 32
DEVICE = "device.windows.owner"
CONFIRMATION = "pc-enrollment-consent-v1"

OWNER_SCOPE = "resolve_connector_owner_scope_for_subject"
DEVICE_CONSENT = "resolve_connector_enrollment_consent_for_subject_device"
WORKSPACE = "resolve_connector_workspace_for_subject"
CONTEXT = "resolve_connector_context_for_subject"
ALL_READS = (OWNER_SCOPE, DEVICE_CONSENT, WORKSPACE, CONTEXT)
CONTEXT_READS = (WORKSPACE, CONTEXT)
ENROLLMENT_READS = (OWNER_SCOPE, DEVICE_CONSENT)


class _AlarmStorage(_Storage):
    """The shared fixture storage plus the alarm calls account deletion schedules."""

    async def deleteAlarm(self) -> None:
        return None

    async def setAlarm(self, _at) -> None:
        return None


def authority(*, switch: str | None = "true", enrollment: bool = True):
    """The real Durable Object, built by its own constructor from a deployed-style env."""
    ctx = types.SimpleNamespace(storage=_AlarmStorage())
    env = types.SimpleNamespace(
        CONTROL_PLANE_ALLOWED_PRODUCTS=DEPLOYED_PRODUCTS,
        CONTROL_PLANE_IDENTITY_LOOKUP_KEY=_KEY,
        GOOGLE_CONNECT_TICKET_KEY=_KEY,
        CONTROL_PLANE_CONNECTOR_ENROLLMENT_RPC_ENABLED="true" if enrollment else "false",
        CONTROL_PLANE_CONNECTOR_ENROLLMENT_SCOPE_APPROVED="true",
        CONTROL_PLANE_CONNECTOR_ENROLLMENT_SCHEMA_INSTALLED="true",
    )
    if switch is not None:
        setattr(env, CONNECTOR_ACCOUNT_KEY_RPC_SWITCH, switch)
    do = _worker_mod.CanonicalIdentityDurableObject(ctx, env)
    do._connector_enrollment_records.install_schema()
    return do


def link(do, *, product, user, person):
    result = run(do.resolve_or_create_product_link({
        "product_id": product,
        "product_user_id": user,
        "auth_provider": "google",
        "provider_subject": person,
    }))
    assert result["ok"] is True, result
    return result["link"]["canonical_subject_id"]


def personal_tenant(do, subject):
    result = run(do.ensure_personal_tenant_membership(
        {"canonical_subject_id": subject, "role": "owner"}))
    assert result["ok"] is True, result
    return result["tenant"]["tenant_id"]


def session(do, *, product, subject):
    result = run(do.establish_auth_session({
        "product_id": product,
        "subject": {"subject_type": "user", "subject_id": subject},
        "authenticated_at": NOW.isoformat(),
        "not_after": (NOW + timedelta(hours=1)).isoformat(),
    }))
    assert result["ok"] is True, result
    return result["session"]["session_id"]


def owner(do, *, user=USER_A, person="person-a", context=True):
    """One ordinary signed-in owner: both login products linked, one personal tenant."""
    subject = link(do, product=B62, user=user, person=person)
    assert link(do, product=B54, user=user, person=person) == subject
    tenant = personal_tenant(do, subject)
    sid = session(do, product=B62, subject=subject)
    if context:
        ticket = run(do.issue_google_connect_ticket({"session_id": sid, "connector_id": "google-drive"}))
        assert ticket["ok"] is True, ticket
    return subject, tenant, sid


def account(subject, product=B62, **extra):
    return {"product_id": product, "canonical_subject_id": subject, **extra}


def payload_for(method, subject, product=B62):
    if method == DEVICE_CONSENT:
        return account(subject, product, device_id=DEVICE)
    return account(subject, product)


def read(do, method, subject, product=B62):
    return run(getattr(do, method)(payload_for(method, subject, product)))


def code(result):
    assert result["ok"] is False, result
    assert set(result) == {"ok", "error"}
    assert result["error"]["message"] == "Canonical identity request was rejected"
    return result["error"]["code"]


def grant(do, sid, device=DEVICE):
    result = run(do.grant_connector_enrollment_consent({
        "session_id": sid, "device_id": device,
        "confirmed": True, "confirmation_version": CONFIRMATION,
    }))
    assert result["ok"] is True, result
    return result["consent"]["consent_id"]


def changes(do):
    return do._storage.connection.total_changes


# --- DEFAULT_OFF -----------------------------------------------------------


@pytest.mark.parametrize("switch", [None, "", "false", "0", "1", "yes", "on", "enabled"])
def test_every_account_keyed_read_stays_closed_until_the_switch_is_exactly_true(switch) -> None:
    do = authority(switch=switch)
    subject, _tenant, sid = owner(do)
    grant(do, sid)
    for method in ALL_READS:
        assert code(read(do, method, subject)) == CONNECTOR_ACCOUNT_KEY_RPC_DISABLED, method
        # A closed deployment answers the same refusal whatever it is sent.
        for junk in (None, {}, {"session_id": sid}, [], "text"):
            assert code(run(getattr(do, method)(junk))) == CONNECTOR_ACCOUNT_KEY_RPC_DISABLED


def test_a_closed_deployment_reads_nothing_for_an_account_keyed_call() -> None:
    do = authority(switch=None)
    subject, _tenant, _sid = owner(do)
    statements: list[str] = []
    do._storage.connection.set_trace_callback(statements.append)
    for method in ALL_READS:
        read(do, method, subject)
    do._storage.connection.set_trace_callback(None)
    assert statements == []


def test_the_switch_name_and_the_added_surface_are_pinned() -> None:
    assert CONNECTOR_ACCOUNT_KEY_RPC_SWITCH == "CONTROL_PLANE_CONNECTOR_ACCOUNT_KEY_RPC_ENABLED"
    assert CONNECTOR_ACCOUNT_KEY_READ_METHODS == frozenset(ALL_READS)


# --- SESSION_KEY_UNTOUCHED / SAME_ANSWER_BOTH_KEYS --------------------------


def _session_answers(do, sid):
    return {
        "scope": run(do.resolve_connector_owner_scope({"session_id": sid})),
        "consent": run(do.resolve_connector_enrollment_consent_for_device(
            {"session_id": sid, "device_id": DEVICE})),
        "workspace": run(do.resolve_connector_workspace({"session_id": sid})),
        "context": run(do.resolve_connector_context({"session_id": sid})),
    }


def _stable(answers):
    """Drop the per-store random references so two stores can be compared by shape."""
    return {name: (result["ok"], sorted(result)) for name, result in answers.items()}


def test_session_keyed_reads_answer_the_same_with_the_switch_on_or_off() -> None:
    seen = []
    for switch in (None, "true"):
        do = authority(switch=switch)
        _subject, _tenant, sid = owner(do)
        grant(do, sid)
        answers = _session_answers(do, sid)
        assert all(result["ok"] is True for result in answers.values()), answers
        seen.append(_stable(answers))
    assert seen[0] == seen[1]


def test_both_keys_give_the_same_answer_for_the_same_account() -> None:
    do = authority()
    subject, _tenant, sid = owner(do)
    grant(do, sid)
    by_session = _session_answers(do, sid)
    assert read(do, OWNER_SCOPE, subject) == by_session["scope"]
    assert read(do, DEVICE_CONSENT, subject) == by_session["consent"]
    assert read(do, WORKSPACE, subject) == by_session["workspace"]
    assert read(do, CONTEXT, subject) == by_session["context"]
    assert by_session["scope"]["scope"]["owner_subject_id"] == subject
    assert by_session["workspace"]["workspace"]["present"] is True


def test_pc_registration_reads_accept_either_login_product_like_the_session_key() -> None:
    do = authority()
    subject, _tenant, sid = owner(do)
    grant(do, sid)
    claw_sid = session(do, product=B54, subject=subject)
    by_claw_session = run(do.resolve_connector_owner_scope({"session_id": claw_sid}))
    assert by_claw_session["ok"] is True
    assert read(do, OWNER_SCOPE, subject, B54) == by_claw_session
    assert read(do, OWNER_SCOPE, subject, B54) == read(do, OWNER_SCOPE, subject, B62)
    assert read(do, DEVICE_CONSENT, subject, B54) == read(do, DEVICE_CONSENT, subject, B62)


def test_an_account_without_connector_context_reads_the_same_by_both_keys() -> None:
    do = authority()
    subject, _tenant, sid = owner(do, context=False)
    by_session = _session_answers(do, sid)
    assert read(do, WORKSPACE, subject) == by_session["workspace"] == {
        "ok": True, "workspace": {"present": False}}
    assert read(do, CONTEXT, subject) == by_session["context"] == {
        "ok": True, "context": {"present": False}}
    assert code(read(do, OWNER_SCOPE, subject)) == code(by_session["scope"])
    assert code(read(do, DEVICE_CONSENT, subject)) == code(by_session["consent"])


# --- JUDGEMENT_REFUSALS ----------------------------------------------------


@pytest.mark.parametrize("method", ALL_READS)
def test_an_account_with_no_link_to_the_product_is_refused(method) -> None:
    do = authority()
    # A real account with a tenant, linked to another product only.
    subject = link(do, product=LOVETREE, user=USER_A, person="person-a")
    personal_tenant(do, subject)
    assert code(read(do, method, subject)) == "canonical_product_identity_link_not_found"


@pytest.mark.parametrize("method", ALL_READS)
def test_an_account_that_never_existed_is_refused(method) -> None:
    do = authority()
    owner(do)
    assert code(read(do, method, "sub_" + "0" * 32)) == "canonical_product_identity_link_not_found"


@pytest.mark.parametrize("method", ALL_READS)
def test_an_account_with_no_membership_is_refused(method) -> None:
    do = authority()
    subject = link(do, product=B62, user=USER_A, person="person-a")
    assert code(read(do, method, subject)) == "canonical_tenant_membership_not_found"


@pytest.mark.parametrize("method", ALL_READS)
def test_an_account_with_two_memberships_is_refused(method) -> None:
    do = authority()
    subject, _tenant, sid = owner(do)
    grant(do, sid)
    assert read(do, method, subject)["ok"] is True
    second = run(do.create_tenant({}))["tenant"]["tenant_id"]
    assigned = run(do.assign_tenant_membership({
        "tenant_id": second, "canonical_subject_id": subject, "role": "owner"}))
    assert assigned["ok"] is True, assigned
    assert code(read(do, method, subject)) == "canonical_tenant_membership_ambiguous"


@pytest.mark.parametrize("method", ALL_READS)
def test_a_deleted_account_is_refused(method) -> None:
    do = authority()
    subject, _tenant, sid = owner(do)
    grant(do, sid)
    assert read(do, method, subject)["ok"] is True
    for product in (B54, B62):
        removed = run(do.remove_product_link({
            "product_id": product, "product_user_id": USER_A,
            "canonical_subject_id": subject,
            "account_deletion_operation_id": str(uuid.uuid4()),
        }))
        assert removed["ok"] is True, removed
    assert removed["common_account_deleted"] is True
    assert do._store.account_deletion_recorded(canonical_subject_id=subject) is True
    assert code(read(do, method, subject)) == "canonical_subject_deleted"


@pytest.mark.parametrize("method", ALL_READS)
def test_leaving_one_product_closes_that_product_and_only_that_product(method) -> None:
    do = authority()
    subject, _tenant, sid = owner(do)
    grant(do, sid)
    removed = run(do.remove_product_link({
        "product_id": B62, "product_user_id": USER_A,
        "canonical_subject_id": subject,
        "account_deletion_operation_id": str(uuid.uuid4()),
    }))
    assert removed["ok"] is True and removed["common_account_deleted"] is False
    # The account, its tenant and its connector rows are all still stored.
    assert do._store.account_deletion_recorded(canonical_subject_id=subject) is False
    assert code(read(do, method, subject, B62)) == "canonical_product_identity_link_not_found"
    if method in ENROLLMENT_READS:
        assert read(do, method, subject, B54)["ok"] is True


@pytest.mark.parametrize("method", ALL_READS)
def test_a_link_only_product_is_refused(method) -> None:
    do = authority()
    # Linked to the link-only product and nothing else, with a tenant.
    subject = link(do, product=BOOKAI, user=USER_A, person="person-a")
    personal_tenant(do, subject)
    assert code(read(do, method, subject, BOOKAI)) == "connector_account_product_denied"


@pytest.mark.parametrize("method", ALL_READS)
def test_a_link_only_link_neither_opens_nor_closes_the_full_products(method) -> None:
    do = authority()
    subject, _tenant, sid = owner(do)
    grant(do, sid)
    assert link(do, product=BOOKAI, user=USER_A, person="person-a") == subject
    assert code(read(do, method, subject, BOOKAI)) == "connector_account_product_denied"
    assert read(do, method, subject, B62)["ok"] is True


def test_the_store_refuses_a_link_only_product_even_if_a_caller_lists_it_as_reviewed() -> None:
    do = authority()
    subject = link(do, product=BOOKAI, user=USER_A, person="person-a")
    personal_tenant(do, subject)
    with pytest.raises(ControlPlaneContractError) as refused:
        judge_connector_account(
            do._store, product_id=BOOKAI, canonical_subject_id=subject,
            reviewed_products=frozenset({BOOKAI}), require_owner=False,
            now=datetime.now(timezone.utc),
        )
    assert refused.value.code == "identity_authority_product_mismatch"


@pytest.mark.parametrize("method", ALL_READS)
def test_a_product_outside_the_reviewed_set_is_refused(method) -> None:
    do = authority()
    subject, _tenant, sid = owner(do)
    grant(do, sid)
    assert link(do, product=LOVETREE, user=USER_A, person="person-a") == subject
    for product in (LOVETREE, "unregistered-product", "B62", " b62"):
        assert code(read(do, method, subject, product)) == "connector_account_product_denied"


@pytest.mark.parametrize("method", CONTEXT_READS)
def test_connector_context_reads_take_the_chat_product_only(method) -> None:
    do = authority()
    subject, _tenant, _sid = owner(do)
    assert read(do, method, subject, B62)["ok"] is True
    assert code(read(do, method, subject, B54)) == "connector_account_product_denied"


def _non_owner(do, role):
    subject = link(do, product=B62, user=USER_A, person="person-a")
    tenant = run(do.create_tenant({}))["tenant"]["tenant_id"]
    assigned = run(do.assign_tenant_membership({
        "tenant_id": tenant, "canonical_subject_id": subject, "role": role}))
    assert assigned["ok"] is True, assigned
    return subject


@pytest.mark.parametrize("role", ["viewer", "operator", "approver"])
def test_pc_registration_reads_require_the_owner_role(role) -> None:
    do = authority()
    subject = _non_owner(do, role)
    for method in ENROLLMENT_READS:
        assert code(read(do, method, subject)) == "connector_enrollment_owner_required"
    # Connector context is the account's own; any role-bearing membership reads it.
    for method in CONTEXT_READS:
        assert read(do, method, subject)["ok"] is True


def test_pc_registration_reads_stay_behind_the_existing_enrollment_gates() -> None:
    do = authority(enrollment=False)
    subject, _tenant, _sid = owner(do)
    for method in ENROLLMENT_READS:
        assert code(read(do, method, subject)) == "connector_enrollment_rpc_disabled"
    for method in CONTEXT_READS:
        assert read(do, method, subject)["ok"] is True


# --- CLOSED_INPUT ----------------------------------------------------------


@pytest.mark.parametrize("method", ALL_READS)
def test_nothing_but_the_product_and_the_account_can_be_supplied(method) -> None:
    do = authority()
    subject, tenant, sid = owner(do)
    grant(do, sid)
    good = payload_for(method, subject)
    assert run(getattr(do, method)(good))["ok"] is True
    extras = {
        "tenant_id": tenant, "role": "owner", "now": NOW.isoformat(),
        "session_id": sid, "expires_at": NOW.isoformat(), "product_user_id": USER_A,
        "workspace_ref": "workspace.other", "account_ref": "account.other",
    }
    for key, value in extras.items():
        assert code(run(getattr(do, method)({**good, key: value}))) == "invalid_identity_authority_rpc", key
    for key in good:
        missing = {name: value for name, value in good.items() if name != key}
        assert code(run(getattr(do, method)(missing))) == "invalid_identity_authority_rpc", key
        for bad in (None, 7, True, "", [subject], {"id": subject}):
            assert code(run(getattr(do, method)({**good, key: bad}))) == "invalid_identity_authority_rpc"
    for junk in (None, [], "text", 7):
        assert code(run(getattr(do, method)(junk))) == "invalid_identity_authority_rpc"


# --- OWN_ACCOUNT_ONLY ------------------------------------------------------


def test_each_account_reads_its_own_scope_and_consent_and_no_other() -> None:
    do = authority()
    subject_a, _tenant_a, sid_a = owner(do, user=USER_A, person="person-a")
    subject_b, _tenant_b, _sid_b = owner(do, user=USER_B, person="person-b")
    assert subject_a != subject_b
    consent_a = grant(do, sid_a)

    scope_a = read(do, OWNER_SCOPE, subject_a)["scope"]
    scope_b = read(do, OWNER_SCOPE, subject_b)["scope"]
    assert scope_a["owner_subject_id"] == subject_a
    assert scope_b["owner_subject_id"] == subject_b
    assert not set(scope_a.values()) & set(scope_b.values())

    assert read(do, DEVICE_CONSENT, subject_a)["consent"]["consent_id"] == consent_a
    # The same device name under the other account has no consent of its own.
    assert code(read(do, DEVICE_CONSENT, subject_b)) == "enrollment_consent_required"

    context_a = read(do, CONTEXT, subject_a)["context"]
    context_b = read(do, CONTEXT, subject_b)["context"]
    assert context_a["subject_id"] == subject_a and context_b["subject_id"] == subject_b
    assert context_a["workspace_ref"] != context_b["workspace_ref"]
    assert read(do, WORKSPACE, subject_a)["workspace"]["workspace_ref"] == context_a["workspace_ref"]


def test_a_withdrawn_consent_is_no_longer_read_by_account() -> None:
    do = authority()
    subject, _tenant, sid = owner(do)
    consent_id = grant(do, sid)
    assert read(do, DEVICE_CONSENT, subject)["ok"] is True
    withdrawn = run(do.revoke_connector_enrollment_consent({
        "session_id": sid, "consent_id": consent_id,
        "confirmed": True, "confirmation_version": CONFIRMATION,
    }))
    assert withdrawn["ok"] is True, withdrawn
    assert code(read(do, DEVICE_CONSENT, subject)) == "enrollment_consent_required"


# --- READ_ONLY -------------------------------------------------------------


def test_account_keyed_reads_never_write_whether_they_pass_or_refuse() -> None:
    do = authority()
    subject, _tenant, sid = owner(do)
    grant(do, sid)
    bare = link(do, product=B62, user=USER_B, person="person-b")  # no membership
    before = changes(do)
    for method in ALL_READS:
        assert read(do, method, subject)["ok"] is True
        assert read(do, method, bare)["ok"] is False
        assert read(do, method, subject, BOOKAI)["ok"] is False
        assert read(do, method, "sub_" + "0" * 32)["ok"] is False
    assert changes(do) == before


def test_reading_by_account_does_not_mint_connector_context() -> None:
    do = authority()
    subject, _tenant, _sid = owner(do, context=False)
    before = changes(do)
    for _ in range(3):
        assert read(do, WORKSPACE, subject) == {"ok": True, "workspace": {"present": False}}
        assert read(do, CONTEXT, subject) == {"ok": True, "context": {"present": False}}
    assert changes(do) == before


# --- PRIVATE_DOORS ---------------------------------------------------------


def test_the_added_reads_are_reachable_only_through_the_private_doors() -> None:
    module = _load_worker(
        ADAPTER_ROOT / "identity_authority_worker.py", "identity_worker_account_key_test"
    )
    assert CONNECTOR_ACCOUNT_KEY_READ_METHODS <= module.IDENTITY_RPC_INGRESS_METHODS
    stub = _Stub({"ok": True})
    payload = {"product_id": B62, "canonical_subject_id": "sub_" + "1" * 32}
    body = b'{"product_id":"b62","canonical_subject_id":"sub_' + b"1" * 32 + b'"}'

    # No ingress secret: the door is not registered, binding RPC still forwards.
    closed = module.Default(env=_env(CONTROL_PLANE_IDENTITY=_Namespace(stub)))
    for name in sorted(CONNECTOR_ACCOUNT_KEY_READ_METHODS):
        now = int(time.time())
        assert _run(closed.fetch(_signed_request(method=name, body=body, at=now))).status == 404
        assert _run(getattr(closed, name)(payload)) == {"ok": True}
        assert stub.calls[-1] == (name, payload)

    worker = module.Default(env=_env(
        CONTROL_PLANE_IDENTITY=_Namespace(stub), PADIEM_IDENTITY_RPC_INGRESS_SECRET=SECRET))
    for name in sorted(CONNECTOR_ACCOUNT_KEY_READ_METHODS):
        now = int(time.time())
        path = "/internal/rpc/" + name
        before = len(stub.calls)
        missing = _Request("https://identity.invalid" + path, headers={}, body=body)
        assert _run(worker.fetch(missing)).status == 403
        wrong = _signed_request(method=name, body=body, at=now, secret="wrong-secret")
        assert _run(worker.fetch(wrong)).status == 403
        assert len(stub.calls) == before
        valid = _signed_request(method=name, body=body, at=now)
        assert _run(worker.fetch(valid)).status == 200
        assert stub.calls[-1] == (name, payload)
