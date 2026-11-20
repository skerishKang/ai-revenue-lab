"""#7644 — 코드 claim의 설치 토큰 확인은 활성 연결에서만 건너뛴다.

#6695 PR-4의 약속은 "토큰이 생기기 전에 연결된 PC는 예전처럼 연결된다"였다.
그런데 그 생략이 링크 행의 상태를 보지 않고 행 존재만 봤다. `pc_device_links`
의 상태 어휘는 CHECK 제약으로 세 값뿐이다 — `pending_verification`,
`active`, `revoked`. 확인 대기 행은 아직 아무것도 증명하지 못했고 해제된 행은
소유자가 철회한 연결이므로, 어느 쪽도 "연결이 서 있다"고 말할 수 없다.

이 계약은 네 결과를 실제 저장소 SQL(전체 마이그레이션)로 고정한다:

* 활성 행은 지금과 같이 토큰 확인을 전혀 돌리지 않는다(취소된 토큰을 내걸어도).
* 확인 대기 행 + 취소된 토큰 → 거절, 코드는 소비되지 않는다.
* 해제됨 행 + 만료된 토큰 → 거절.
* 확인 대기·해제됨 행 + 유효한 토큰 → 진행(각각 승격·재부여로).

typed claim(`redeem_code`)과 observed claim(`complete_claim_from_observation`)
두 길 모두 같은 판정을 거쳐야 하므로 양쪽을 모두 단언한다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import _support.pc_device_pairing as pairing            # noqa: E402

from app.pc_device_pairing_store import (                # noqa: E402
    PcPairingError,
    derive_install_tag,
)

OWNER = pairing.OWNER
NODE = pairing.NODE
RUN = pairing.run


def moment() -> datetime:
    """한 시험 안의 모든 시각이 이 순간에 고정된다(현재 시각 한 번만 읽는다)."""
    return datetime.now(timezone.utc)


def stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


def seed_link(store_value, state: str) -> None:
    """(OWNER, NODE) 링크 행을 저장소가 쓰는 것과 같은 모양으로 심는다."""
    stamped = stamp(moment())
    store_value.db.conn.execute(
        "INSERT INTO pc_device_links "
        "(link_id, user_id, mesh_node_id, label, state, roots_json, "
        " pairing_code_id, created_at, updated_at, revoked_at) "
        "VALUES (?, ?, ?, NULL, ?, '[]', NULL, ?, ?, ?)",
        ("pclink_" + "1" * 32, OWNER, NODE, state, stamped, stamped,
         stamped if state == "revoked" else None),
    )


def link_state(store_value) -> str:
    row = store_value.db.conn.execute(
        "SELECT state FROM pc_device_links WHERE user_id=? AND mesh_node_id=?",
        (OWNER, NODE),
    ).fetchone()
    return row[0]


def code_state(store_value, code_id: str) -> str:
    return store_value.db.conn.execute(
        "SELECT state FROM pc_pairing_codes WHERE code_id=?", (code_id,)
    ).fetchone()[0]


def revoke_token(store_value, code_id: str) -> None:
    store_value.db.conn.execute(
        "UPDATE pc_install_tokens SET revoked_at=? WHERE code_id=?",
        (stamp(moment()), code_id),
    )


def expire_token(store_value, code_id: str) -> None:
    # 만료 시점을 과거로 옮긴다. 표의 CHECK(expires_at > issued_at)를 지키려면
    # 발행 시각도 함께 과거로 밀어야 한다.
    store_value.db.conn.execute(
        "UPDATE pc_install_tokens SET issued_at=?, expires_at=? WHERE code_id=?",
        (stamp(moment() - timedelta(minutes=30)),
         stamp(moment() - timedelta(minutes=1)), code_id),
    )


def issue(store_value) -> dict:
    return RUN(store_value.issue_code(user_id=OWNER, issued_at=moment()))


def observed_name(tag: str, token: str | None = None) -> str:
    """설치 파일이 에이전트 이름에 쓰는 모양: `<태그> <토큰> <기계이름>`."""
    parts = ["PADIEM", tag]
    if token is not None:
        parts.append(token)
    parts.append("beta-notebook")
    return " ".join(parts)


# -- 1. 활성 행은 지금과 같이 토큰 확인을 건너뛴다 ------------------------------

def test_typed_claim_on_an_active_link_still_skips_the_token_check() -> None:
    shared = pairing.store()
    seed_link(shared, "active")
    issued = issue(shared)
    revoke_token(shared, issued["code_id"])

    # 취소된 토큰을 일부러 내건다: 생략은 "토큰 확인을 전혀 돌리지 않는다"는
    # 뜻이어야 하고, 그렇지 않으면 #6695 PR-4의 기존 약속이 깨진 것이다.
    claimed = RUN(shared.redeem_code(
        code=issued["code"], mesh_node_id=NODE, label=None, now=moment(),
        verified=True, install_token=issued["install_token"],
    ))
    assert claimed["state"] == "active"
    assert code_state(shared, issued["code_id"]) == "claimed"


def test_observed_claim_on_an_active_link_still_skips_the_token_check() -> None:
    shared = pairing.store()
    seed_link(shared, "active")
    issued = issue(shared)
    revoke_token(shared, issued["code_id"])
    tag = derive_install_tag(issued["code"])

    # 이름에 토큰이 없어도(결합 검사 길) 활성 행에서는 확인이 돌지 않는다.
    completed = RUN(shared.complete_claim_from_observation(
        agent_name=observed_name(tag), mesh_node_id=NODE, now=moment(),
    ))
    assert completed is not None
    assert completed["state"] == "active"
    assert code_state(shared, issued["code_id"]) == "claimed"


# -- 2. 확인 대기 행 + 취소된 토큰 → 거절 --------------------------------------

def test_typed_claim_on_a_pending_link_with_a_revoked_token_is_refused() -> None:
    shared = pairing.store()
    seed_link(shared, "pending_verification")
    issued = issue(shared)
    revoke_token(shared, issued["code_id"])

    with pytest.raises(PcPairingError) as refused:
        RUN(shared.redeem_code(
            code=issued["code"], mesh_node_id=NODE, label=None, now=moment(),
            verified=True,
        ))
    assert str(refused.value) == "install token revoked"
    # 거절은 코드를 소비하기 전에 일어난다.
    assert code_state(shared, issued["code_id"]) == "pending"
    assert link_state(shared) == "pending_verification"


def test_typed_claim_on_a_pending_link_with_a_presented_revoked_token_is_refused() -> None:
    shared = pairing.store()
    seed_link(shared, "pending_verification")
    issued = issue(shared)
    revoke_token(shared, issued["code_id"])

    with pytest.raises(PcPairingError) as refused:
        RUN(shared.redeem_code(
            code=issued["code"], mesh_node_id=NODE, label=None, now=moment(),
            verified=True, install_token=issued["install_token"],
        ))
    assert str(refused.value) == "install token revoked"
    assert code_state(shared, issued["code_id"]) == "pending"


def test_observed_claim_on_a_pending_link_with_a_revoked_token_is_refused() -> None:
    shared = pairing.store()
    seed_link(shared, "pending_verification")
    issued = issue(shared)
    revoke_token(shared, issued["code_id"])
    tag = derive_install_tag(issued["code"])

    with pytest.raises(PcPairingError) as refused:
        RUN(shared.complete_claim_from_observation(
            agent_name=observed_name(tag), mesh_node_id=NODE, now=moment(),
        ))
    assert str(refused.value) == "install token revoked"
    assert code_state(shared, issued["code_id"]) == "pending"
    assert link_state(shared) == "pending_verification"


# -- 3. 해제됨 행 + 만료된 토큰 → 거절 ----------------------------------------

def test_typed_claim_on_a_revoked_link_with_an_expired_token_is_refused() -> None:
    shared = pairing.store()
    seed_link(shared, "revoked")
    issued = issue(shared)
    expire_token(shared, issued["code_id"])

    with pytest.raises(PcPairingError) as refused:
        RUN(shared.redeem_code(
            code=issued["code"], mesh_node_id=NODE, label=None, now=moment(),
            verified=True,
        ))
    assert str(refused.value) == "install token expired"
    assert code_state(shared, issued["code_id"]) == "pending"
    assert link_state(shared) == "revoked"


def test_observed_claim_on_a_revoked_link_with_an_expired_token_is_refused() -> None:
    shared = pairing.store()
    seed_link(shared, "revoked")
    issued = issue(shared)
    expire_token(shared, issued["code_id"])
    tag = derive_install_tag(issued["code"])

    with pytest.raises(PcPairingError) as refused:
        RUN(shared.complete_claim_from_observation(
            agent_name=observed_name(tag), mesh_node_id=NODE, now=moment(),
        ))
    assert str(refused.value) == "install token expired"
    assert code_state(shared, issued["code_id"]) == "pending"
    assert link_state(shared) == "revoked"


# -- 4. 확인 대기·해제됨 행 + 유효한 토큰 → 진행 -------------------------------

def test_typed_claim_on_a_pending_link_with_a_valid_token_proceeds() -> None:
    shared = pairing.store()
    seed_link(shared, "pending_verification")
    issued = issue(shared)

    claimed = RUN(shared.redeem_code(
        code=issued["code"], mesh_node_id=NODE, label=None, now=moment(),
        verified=True, install_token=issued["install_token"],
    ))
    # 같은 쌍의 확인 대기 행은 유효 토큰과 함께 승격된다.
    assert claimed["state"] == "active"
    assert code_state(shared, issued["code_id"]) == "claimed"


def test_typed_claim_on_a_revoked_link_with_a_valid_token_proceeds() -> None:
    shared = pairing.store()
    seed_link(shared, "revoked")
    issued = issue(shared)

    claimed = RUN(shared.redeem_code(
        code=issued["code"], mesh_node_id=NODE, label=None, now=moment(),
        verified=True, install_token=issued["install_token"],
    ))
    # 해제 후 재연결은 새 부여다: 폴더·드라이브는 돌아오지 않는다.
    assert claimed["state"] == "active"
    assert claimed["roots"] == []
    assert code_state(shared, issued["code_id"]) == "claimed"


def test_observed_claim_on_a_pending_link_with_a_valid_token_proceeds() -> None:
    shared = pairing.store()
    seed_link(shared, "pending_verification")
    issued = issue(shared)
    tag = derive_install_tag(issued["code"])

    completed = RUN(shared.complete_claim_from_observation(
        agent_name=observed_name(tag, issued["install_token"]),
        mesh_node_id=NODE, now=moment(),
    ))
    assert completed is not None
    assert completed["state"] == "active"
    assert code_state(shared, issued["code_id"]) == "claimed"


def test_observed_claim_on_a_revoked_link_with_a_valid_token_proceeds() -> None:
    shared = pairing.store()
    seed_link(shared, "revoked")
    issued = issue(shared)
    tag = derive_install_tag(issued["code"])

    completed = RUN(shared.complete_claim_from_observation(
        agent_name=observed_name(tag, issued["install_token"]),
        mesh_node_id=NODE, now=moment(),
    ))
    assert completed is not None
    assert completed["state"] == "active"
    assert completed["roots"] == []
    assert code_state(shared, issued["code_id"]) == "claimed"
