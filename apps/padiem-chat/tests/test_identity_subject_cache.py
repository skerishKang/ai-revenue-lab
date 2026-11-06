"""261106 · subject→product_user 역방향 조회 프로세스 캐시 회귀 시험.

측정 근거: 11-03 이후 ``identity_rpc_slow method=resolve_product_user_for_subject``
133건이 전부 서버 소유 내부 경로(요청당 1회)에서 나왔다(p50 441ms, 최대 5,480ms).
같은 canonical subject 를 요청마다 다시 조회하지 않도록 짧은 TTL 프로세스 캐시를
두고, 링크 쓰기(생성·재바인딩·제거)에서 같은 키를 무효화한다.

- 같은 (product, subject) 재조회는 RPC 를 한 번만 친다(수정 전 코드에서는 두 번
  치므로 이 시험은 수정 전 코드에서 실패한다).
- resolve_or_create_product_link / remove_product_link 성공은 같은 키를 무효화해
  다음 조회가 RPC 로 새 값을 받는다.
- TTL 이 지나면 만료된 항목은 다시 RPC 로 조회한다.
- 키에 product_id 와 canonical_subject_id 가 모두 들어가 다른 사용자·다른 제품
  결과가 섞이지 않는다(계정 격리).
"""

from __future__ import annotations

import asyncio

from app.control_plane_identity_worker import (
    CloudflareControlPlaneIdentityAuthority,
    _product_user_cache,
)

PRODUCT = "b62"
SUBJECT_A = "usr_aaaaaaaaaaaaaaaaaaaaaaaa"
SUBJECT_B = "usr_bbbbbbbbbbbbbbbbbbbbbbbb"
USER_1 = "puser_1111"
USER_2 = "puser_2222"


class Binding:
    def __init__(self, product_user_id=USER_1):
        self.calls = []
        self.product_user_id = product_user_id

    async def resolve_product_user_for_subject(self, payload):
        self.calls.append(("resolve", dict(payload)))
        return {"ok": True, "product_user_id": self.product_user_id}

    async def resolve_or_create_product_link(self, payload):
        self.calls.append(("create", dict(payload)))
        # The rebind this test models targets the same canonical subject the
        # earlier reverse lookup cached; the authority echoes that subject.
        return {
            "ok": True,
            "link": {
                "product_id": payload["product_id"],
                "product_user_id": payload["product_user_id"],
                "canonical_subject_id": SUBJECT_A,
                "state": "active",
            },
        }

    async def remove_product_link(self, payload):
        self.calls.append(("remove", dict(payload)))
        return {
            "ok": True,
            "removed": True,
            "remaining_links": 0,
            "common_account_deleted": False,
            "revoked_sessions": 0,
            "already_deleted": False,
        }


def _authority(binding):
    return CloudflareControlPlaneIdentityAuthority(binding)


def _resolve(authority, *, product_id=PRODUCT, subject=SUBJECT_A):
    return asyncio.run(
        authority.resolve_product_user_for_subject(
            product_id=product_id, canonical_subject_id=subject
        )
    )


def setup_function(_function):
    _product_user_cache.clear()


def teardown_function(_function):
    _product_user_cache.clear()


def test_same_subject_second_lookup_answers_from_cache_without_rpc():
    binding = Binding()
    authority = _authority(binding)
    first = _resolve(authority)
    second = _resolve(authority)
    assert first == second == USER_1
    assert len(binding.calls) == 1, "같은 subject 재조회는 RPC 를 반복하지 않는다"


def test_create_link_invalidates_the_same_pair():
    binding = Binding()
    authority = _authority(binding)
    assert _resolve(authority) == USER_1
    asyncio.run(
        authority.resolve_or_create_product_link(
            product_id=PRODUCT,
            product_user_id=USER_2,
            auth_provider="synthetic",
            provider_subject="provider-subject-1",
        )
    )
    binding.product_user_id = USER_2
    assert _resolve(authority) == USER_2, "생성·재바인딩 뒤에는 캐시가 무효화된다"
    assert len(binding.calls) == 3


def test_remove_link_invalidates_the_same_pair():
    binding = Binding()
    authority = _authority(binding)
    assert _resolve(authority) == USER_1
    asyncio.run(
        authority.remove_product_link(
            product_id=PRODUCT,
            product_user_id=USER_1,
            canonical_subject_id=SUBJECT_A,
        )
    )
    binding.product_user_id = USER_2
    assert _resolve(authority) == USER_2, "제거 뒤에는 캐시가 무효화된다"
    assert len(binding.calls) == 3


def test_expired_entry_refetches(monkeypatch):
    binding = Binding()
    authority = _authority(binding)
    assert _resolve(authority) == USER_1
    import app.control_plane_identity_worker as worker_module
    monkeypatch.setattr(worker_module, "PRODUCT_USER_CACHE_TTL_SECONDS", 0.0)
    assert worker_module.PRODUCT_USER_CACHE_TTL_SECONDS == 0.0
    binding.product_user_id = USER_2
    assert _resolve(authority) == USER_2, "TTL 만료 항목은 다시 RPC 로 조회한다"


def test_different_subjects_never_share_an_entry():
    binding = Binding()
    authority = _authority(binding)
    assert _resolve(authority, subject=SUBJECT_A) == USER_1
    binding.product_user_id = USER_2
    assert _resolve(authority, subject=SUBJECT_B) == USER_2, "다른 사용자 결과가 섞이지 않는다"
    assert _resolve(authority, subject=SUBJECT_A) == USER_1, "A 의 캐시는 그대로 유지된다"


def test_same_subject_other_product_is_a_separate_key():
    binding = Binding()
    authority = _authority(binding)
    assert _resolve(authority, product_id="b62", subject=SUBJECT_A) == USER_1
    binding.product_user_id = USER_2
    assert _resolve(authority, product_id="other", subject=SUBJECT_A) == USER_2, "다른 제품은 별개 키다"
    assert _resolve(authority, product_id="b62", subject=SUBJECT_A) == USER_1
