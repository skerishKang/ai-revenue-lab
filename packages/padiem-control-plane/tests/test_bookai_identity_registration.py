"""#7541 — BookAI(b61) 제품 등록: 계정 번호 발급·조회 전용.

공통 로그인은 처음 보는 사람의 계정 번호를 이 권위에 요청하고, 제품 ID로
클라이언트 ID를 보낸다. b61이 검토된 제품 집합에 없어서 다른 제품에 로그인한
적 없는 사람의 북AI 첫 로그인이 거부됐다.

b61은 러브트리처럼 전체 표면을 받지 않는다. 링크 전용 등급으로 등록되어
계정 링크가 만들어지고 다시 찾아지고 목록에 보이며, 세션·역조회는 닫혀 있다.
연결 제거는 별도 검토된 집합에 한해서만 열리고, 실제 생성자를 거쳐 경계를 고정한다.

Covered:

- LINK_ONLY_PINNED: b61 is reviewed, and only as a link-only product
- CODE_AND_DEPLOYED_LIST_MOVE_TOGETHER: the previous deployed list no longer boots
- FIRST_LOGIN_ACCEPTED: an unseen person gets an account number through b61
- ONE_ACCOUNT_ACROSS_PRODUCTS: BookAI-first then Chat (and the reverse) keep one number
- NO_SESSION_SURFACE: sessions and the reverse lookup stay closed
- LISTING_STAYS_WHOLE: a b61 link is listed and never fails the subject's listing
- TIER_STAYS_INSIDE_THE_BOUNDARY: a link-only product outside the reviewed set is refused
"""

from __future__ import annotations

import base64
import pathlib
import re
import sys
import types
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from test_lovetree_identity_registration import (  # noqa: E402
    B54,
    B62,
    LOVETREE,
    _Storage,
    _Tokens,
    _worker_mod,
    run,
)

from identity_authority_durable import CloudflareCanonicalIdentityAuthorityStore  # noqa: E402
from padiem_control_plane.contracts import SubjectType  # noqa: E402

BOOKAI = "b61"
DEPLOYED_PRODUCTS = "b62,b54-padiem-claw,lovetree-4-0,b61"
PREVIOUS_DEPLOYED_PRODUCTS = "b62,b54-padiem-claw,lovetree-4-0"
MISMATCH = "identity_authority_product_mismatch"
USER = "usr_" + "6" * 32
SUBJECT = "google-subject-7541"
NOW = datetime.now(timezone.utc)
_KEY = base64.urlsafe_b64encode(b"K" * 32).decode("ascii").rstrip("=")


class _AlarmStorage(_Storage):
    """The lovetree fixture's storage plus the alarm calls link removal schedules."""

    async def deleteAlarm(self) -> None:
        return None

    async def setAlarm(self, _at) -> None:
        return None


def authority(products: str = DEPLOYED_PRODUCTS):
    """The real Durable Object, built by its own constructor from a deployed-style env."""
    ctx = types.SimpleNamespace(storage=_AlarmStorage())
    env = types.SimpleNamespace(
        CONTROL_PLANE_ALLOWED_PRODUCTS=products,
        CONTROL_PLANE_LINK_REMOVAL_PRODUCTS=DEPLOYED_PRODUCTS,
        CONTROL_PLANE_IDENTITY_LOOKUP_KEY=_KEY,
        GOOGLE_CONNECT_TICKET_KEY=_KEY,
    )
    return _worker_mod.CanonicalIdentityDurableObject(ctx, env)


def link(do, *, product, user=USER, subject=SUBJECT, expected=None):
    payload = {
        "product_id": product,
        "product_user_id": user,
        "auth_provider": "google",
        "provider_subject": subject,
    }
    if expected is not None:
        payload["expected_canonical_subject_id"] = expected
    return run(do.resolve_or_create_product_link(payload))


def test_bookai_is_reviewed_only_as_a_link_only_product() -> None:
    assert _worker_mod._ALLOWED_PRODUCTS == frozenset({B62, B54, LOVETREE, BOOKAI})
    assert _worker_mod._LINK_ONLY_PRODUCTS == frozenset({BOOKAI})
    assert _worker_mod._LINK_ONLY_PRODUCTS <= _worker_mod._ALLOWED_PRODUCTS
    safe = authority()._store.safe_dict()
    assert safe["allowed_product_ids"] == sorted([B62, B54, LOVETREE, BOOKAI])
    assert safe["link_only_product_ids"] == [BOOKAI]


def test_the_deployed_product_list_must_move_together_with_the_code() -> None:
    with pytest.raises(RuntimeError, match="product boundary"):
        authority(PREVIOUS_DEPLOYED_PRODUCTS)
    assert authority(DEPLOYED_PRODUCTS) is not None


def test_bookai_first_login_is_given_an_account_number() -> None:
    result = link(authority(), product=BOOKAI)
    # Exactly what the common login checks before it accepts the account.
    assert result["ok"] is True
    assert result["link"]["state"] == "active"
    assert result["link"]["product_id"] == BOOKAI
    assert result["link"]["product_user_id"] == USER
    assert re.fullmatch(r"sub_[A-Za-z0-9_-]+", result["link"]["canonical_subject_id"])


def test_bookai_first_login_is_found_again_with_the_same_number() -> None:
    do = authority()
    first = link(do, product=BOOKAI)
    again = link(do, product=BOOKAI)
    assert again["ok"] is True
    assert again["link"]["canonical_subject_id"] == first["link"]["canonical_subject_id"]


def test_a_bookai_first_account_keeps_its_number_when_it_later_signs_in_to_chat() -> None:
    do = authority()
    account = link(do, product=BOOKAI)["link"]["canonical_subject_id"]
    chat = link(do, product=B62, expected=account)
    assert chat["ok"] is True
    assert chat["link"]["canonical_subject_id"] == account


def test_a_chat_first_account_keeps_its_number_when_it_later_signs_in_to_bookai() -> None:
    do = authority()
    account = link(do, product=B62)["link"]["canonical_subject_id"]
    bookai = link(do, product=BOOKAI, expected=account)
    assert bookai["ok"] is True
    assert bookai["link"]["canonical_subject_id"] == account


def test_bookai_opens_no_session_or_reverse_lookup_surface() -> None:
    do = authority()
    account = link(do, product=BOOKAI)["link"]["canonical_subject_id"]
    refused = {
        "establish_auth_session": run(do.establish_auth_session({
            "product_id": BOOKAI,
            "subject": {"subject_type": SubjectType.USER.value, "subject_id": account},
            "authenticated_at": NOW.isoformat(),
            "not_after": (NOW + timedelta(hours=2)).isoformat(),
        })),
        "resolve_current_auth_session": run(do.resolve_current_auth_session({
            "product_id": BOOKAI, "product_user_id": USER,
        })),
        "revoke_auth_session": run(do.revoke_auth_session({
            "product_id": BOOKAI, "session_id": "sess_" + "0" * 32,
        })),
        "revoke_all_auth_sessions": run(do.revoke_all_auth_sessions({
            "product_id": BOOKAI, "product_user_id": USER,
        })),
        "resolve_product_user_for_subject": run(do.resolve_product_user_for_subject({
            "product_id": BOOKAI, "canonical_subject_id": account,
        })),
    }
    for method, answer in refused.items():
        assert answer["ok"] is False, method
        assert answer["error"]["code"] == MISMATCH, method
        assert set(answer) == {"ok", "error"}, method


def test_the_same_calls_stay_open_for_a_full_product() -> None:
    # The refusals above come from the link-only tier, not from a broken fixture.
    do = authority()
    account = link(do, product=B62)["link"]["canonical_subject_id"]
    established = run(do.establish_auth_session({
        "product_id": B62,
        "subject": {"subject_type": SubjectType.USER.value, "subject_id": account},
        "authenticated_at": NOW.isoformat(),
        "not_after": (NOW + timedelta(hours=2)).isoformat(),
    }))
    assert established["ok"] is True
    reverse = run(do.resolve_product_user_for_subject({
        "product_id": B62, "canonical_subject_id": account,
    }))
    assert reverse["ok"] is True and reverse["product_user_id"] == USER


def test_a_bookai_link_is_listed_and_does_not_fail_the_listing() -> None:
    do = authority()
    account = link(do, product=BOOKAI)["link"]["canonical_subject_id"]
    link(do, product=B62, expected=account)
    listed = run(do.list_active_product_links_for_subject({"canonical_subject_id": account}))
    assert listed["ok"] is True
    assert [item["product_id"] for item in listed["links"]] == [BOOKAI, B62]


def test_removing_the_chat_link_leaves_the_bookai_account_in_place() -> None:
    do = authority()
    account = link(do, product=BOOKAI)["link"]["canonical_subject_id"]
    link(do, product=B62, expected=account)
    removed = run(do.remove_product_link({
        "product_id": B62,
        "product_user_id": USER,
        "canonical_subject_id": account,
        "account_deletion_operation_id": None,
    }))
    assert removed["ok"] is True
    assert removed["removed"] is True
    assert removed["remaining_links"] == 1
    assert removed["common_account_deleted"] is False
    listed = run(do.list_active_product_links_for_subject({"canonical_subject_id": account}))
    assert [item["product_id"] for item in listed["links"]] == [BOOKAI]
    # The person is still the same account at the next BookAI sign-in.
    assert link(do, product=BOOKAI)["link"]["canonical_subject_id"] == account


def test_a_link_only_product_must_stay_inside_the_reviewed_set() -> None:
    def build(**kwargs):
        return CloudflareCanonicalIdentityAuthorityStore(
            _Storage(), lookup_key=b"K" * 32, random_hex=_Tokens(), **kwargs
        )

    with pytest.raises(ValueError, match="subset"):
        build(allowed_product_ids=frozenset({B62}), link_only_product_ids=frozenset({BOOKAI}))
    with pytest.raises(ValueError, match="frozenset"):
        build(allowed_product_ids=frozenset({B62, BOOKAI}), link_only_product_ids={BOOKAI})
    # Left out, the tier is empty: every reviewed product keeps the full surface.
    plain = build(allowed_product_ids=frozenset({B62, BOOKAI}))
    assert plain.safe_dict()["link_only_product_ids"] == []
