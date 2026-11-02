"""#6446 2차 — 1차에서 미확인이던 세 표면의 계정 격리.

1차 스윕(test_6446_account_isolation_sweep.py)이 북AI 기록(082)·PC 연결·자동화
규칙을 미확인으로 남긴 이유와 이번에 채우는 방법:

- **북AI 기록(082)**: 사용자 세션이 아니라 `x-bookai-*` HMAC 서명 헤더의 서비스
  간 레인이다. 시험 안에서만 가짜 동기화 비밀을 만들어 서명하고, subject A의
  기록을 subject B가 목록·병합으로 닿을 수 없는지, 무서명·위조·subject 바꿔치기·
  만료(재전송)가 401로 거부되는지 확인한다. 서비스 시계는 주입 가능하므로
  재전송 거부도 실제 시간 없이 재현한다.
- **PC 연결**: 1차에서는 페어링 포트 구성이 없어 fail-closed만 확인했다. 이번엔
  실제 `D1PcPairingStore`를 시험 DB에 얹고, A가 발급·클레임한 링크를 B가
  목록·해제·라벨·일시정지·재개로 닿을 수 없는지, 추측 link_id도 포함해 확인한다.
- **자동화 규칙 CRUD**: 생성·수정·삭제는 전부 B54 세션 브릿지 → 컨트롤플레인
  OWNER 멤버십 재검증(`resolve_automation_owner_mutation_context`)을 통과해야
  한다. 권한이 없으면 fail-closed(403)다 — 이번에도 가짜 권한을 구성하지 않고
  **fail-closed 증거**로 고정한다. 소유자-멤버 전체 행렬은 세 층 가짜(B54 세션
  스냅샷·TenantMembership·실행 대상 개정 권한)가 필요해 여전히 미확인이다.

규칙: 제품 코드 변경 없음(시험 파일만), 자격증명·운영 서버 미사용.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.bookai_records import install_bookai_records_routes
from app.pc_device_pairing_routes import (
    PC_PAIRING_LABEL_PATH, PC_PAIRING_LINK_PATH, PC_PAIRING_PAUSE_PATH,
    PC_PAIRING_PATH, PC_PAIRING_RESUME_PATH,
)
from app.pc_device_pairing_store import D1PcPairingStore

from test_6446_account_isolation_sweep import clients

BOOKAI_PATH = "/api/bookai/records"
BOOKAI_SECRET = "synthetic-bookai-sync-secret-6446-not-real"
SUBJECT_A = "sub_isolation_alpha_6446"
SUBJECT_B = "sub_isolation_beta_6446"


# ── 북AI 기록(082): 서명된 서비스 간 레인 ────────────────────────────────────


class _Clock:
    """주입 가능한 시계 — 만료·재전송을 실제 대기 없이 재현한다."""

    def __init__(self, now: float):
        self.now = now

    def __call__(self) -> float:
        return self.now


def _sign(secret: str, method: str, path: str, timestamp: str, subject: str,
          body: bytes) -> str:
    # app/com2_hmac.py::signature_matches의 canonical 그대로.
    canonical = "\n".join((
        method, path, timestamp, subject, hashlib.sha256(body).hexdigest(),
    ))
    return hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def _bookai_request(client, method, *, subject, secret, path=BOOKAI_PATH,
                    body=b"", now, query=""):
    timestamp = str(int(now))
    full_path = path + ("?" + query if query else "")
    headers = {
        "x-bookai-subject": subject,
        "x-bookai-timestamp": timestamp,
        "x-bookai-signature": _sign(secret, method, full_path, timestamp, subject, body),
    }
    if method == "GET":
        return client.get(full_path, headers=headers)
    return client.post(full_path, content=body, headers={
        **headers, "content-type": "application/json",
    })


def _record(record_id: str, updated_at: int, *, payload=None, deleted=False) -> dict:
    return {"record_id": record_id, "book_id": "book_6446",
            "locator": "loc-1", "kind": "note",
            "payload": payload or {"page": 1}, "updated_at": updated_at,
            "deleted": deleted}


@pytest.fixture
def bookai():
    app, a_client, b_client, _a, _b = clients()
    clock = _Clock(1_793_534_400.0)
    install_bookai_records_routes(
        app, env={"BOOKAI_COM2_SYNC_SECRET": BOOKAI_SECRET},
        db_binding=app.state.history_store.db, clock=clock,
    )
    return a_client, b_client, clock


def test_bookai_records_are_subject_scoped(bookai):
    a_client, b_client, clock = bookai
    import json as _json
    merge_body = _json.dumps({"records": [
        _record("r-a-1", 1000), _record("r-a-2", 2000, payload={"page": 2}),
    ]}).encode("utf-8")
    saved = _bookai_request(a_client, "POST", subject=SUBJECT_A, secret=BOOKAI_SECRET,
                            body=merge_body, now=clock.now)
    assert saved.status_code == 200, saved.text
    assert saved.json()["accepted"] == 2

    listed_b = _bookai_request(b_client, "GET", subject=SUBJECT_B, secret=BOOKAI_SECRET,
                               now=clock.now, query="since=0&limit=500")
    assert listed_b.status_code == 200, listed_b.text
    assert all(row["record_id"] != "r-a-1" and row["record_id"] != "r-a-2"
               for row in listed_b.json()["records"])

    # B가 같은 record_id로 병합해도 B의 행일 뿐 — A의 내용은 그대로다.
    borrowed = _json.dumps({"records": [_record("r-a-1", 3000, payload={"page": 99})]})
    merged_b = _bookai_request(b_client, "POST", subject=SUBJECT_B, secret=BOOKAI_SECRET,
                               body=borrowed.encode("utf-8"), now=clock.now)
    assert merged_b.status_code == 200, merged_b.text
    listed_a = _bookai_request(a_client, "GET", subject=SUBJECT_A, secret=BOOKAI_SECRET,
                               now=clock.now, query="since=0&limit=500")
    rows_a = {row["record_id"]: row for row in listed_a.json()["records"]}
    assert rows_a["r-a-1"]["payload"] == {"page": 1}


def test_bookai_tombstone_stays_subject_scoped(bookai):
    a_client, b_client, clock = bookai
    import json as _json
    tombstone = _json.dumps({"records": [_record("r-a-3", 5000, deleted=True)]})
    assert _bookai_request(a_client, "POST", subject=SUBJECT_A, secret=BOOKAI_SECRET,
                           body=tombstone.encode("utf-8"), now=clock.now,
                           ).status_code == 200
    listed_b = _bookai_request(b_client, "GET", subject=SUBJECT_B, secret=BOOKAI_SECRET,
                               now=clock.now, query="since=0&limit=500")
    assert listed_b.status_code == 200
    assert all(row["record_id"] != "r-a-3" for row in listed_b.json()["records"])


def test_bookai_rejects_missing_forged_swapped_and_expired_signatures(bookai):
    a_client, b_client, clock = bookai
    import json as _json
    body = _json.dumps({"records": [_record("r-x-1", 1000)]}).encode("utf-8")

    # 1) 서명 없음
    missing = a_client.post(BOOKAI_PATH, content=body, headers={
        "content-type": "application/json", "x-bookai-subject": SUBJECT_A,
        "x-bookai-timestamp": str(int(clock.now)),
    })
    assert missing.status_code == 401, missing.text

    # 2) 위조(엉뚱한 비밀로 서명)
    forged = _bookai_request(a_client, "POST", subject=SUBJECT_A,
                             secret="attacker-secret-6446", body=body, now=clock.now)
    assert forged.status_code == 401, forged.text

    # 3) subject 바꿔치기(A 서명을 그대로 B 헤더에)
    timestamp = str(int(clock.now))
    signature = _sign(BOOKAI_SECRET, "POST", BOOKAI_PATH, timestamp, SUBJECT_A, body)
    swapped = a_client.post(BOOKAI_PATH, content=body, headers={
        "content-type": "application/json",
        "x-bookai-subject": SUBJECT_B,
        "x-bookai-timestamp": timestamp,
        "x-bookai-signature": signature,
    })
    assert swapped.status_code == 401, swapped.text

    # 4) 만료(300초 창 밖) = 재전송 거부
    stale = _bookai_request(a_client, "POST", subject=SUBJECT_A, secret=BOOKAI_SECRET,
                            body=body, now=clock.now - 400)
    assert stale.status_code == 401, stale.text
    assert "expired" in stale.json()["error"], stale.text

    # 5) 정상 서명 요청을 창이 지나간 뒤 재전송 → 만료로 거부
    replay_body = b""
    replay = _bookai_request(a_client, "GET", subject=SUBJECT_A, secret=BOOKAI_SECRET,
                             body=replay_body, now=clock.now, query="since=0&limit=500")
    assert replay.status_code == 200
    clock.now += 400
    replayed = a_client.get(BOOKAI_PATH + "?since=0&limit=500", headers={
        "x-bookai-subject": SUBJECT_A,
        "x-bookai-timestamp": str(int(replay.request.headers["x-bookai-timestamp"])),
        "x-bookai-signature": replay.request.headers["x-bookai-signature"],
    })
    assert replayed.status_code == 401, replayed.text
    assert "expired" in replayed.json()["error"], replayed.text


# ── PC 연결: 페어링 링크는 계정별이다 ────────────────────────────────────────


def _pair_a_pc(db, a, now: datetime) -> str:
    store = D1PcPairingStore(db)
    code = asyncio.run(store.issue_code(user_id=a, issued_at=now))
    redeemed = asyncio.run(store.redeem_code(
        code=code["code"], mesh_node_id="node//a-pc-6446", label="A의 PC",
        now=now + timedelta(seconds=5), verified=True,
    ))
    link_id = redeemed.get("link_id")
    assert link_id, redeemed
    return link_id


def test_pc_pairing_links_stay_in_their_account():
    app, a_client, b_client, a, _b = clients()
    db = app.state.history_store.db
    app.state.pc_device_pairing_store = D1PcPairingStore(db)
    now = datetime.now(timezone.utc)
    link_id = _pair_a_pc(db, a, now)

    def link_path(suffix: str = "") -> str:
        # PC_PAIRING_LINK_PATH에는 {link_id} 자리표시가 이미 있으므로 치환한다.
        return PC_PAIRING_LINK_PATH.replace("{link_id}", link_id) + suffix

    listed_b = b_client.get(PC_PAIRING_PATH)
    assert listed_b.status_code == 200, listed_b.text
    assert all(row["link_id"] != link_id for row in listed_b.json().get("links") or [])

    # B가 A의 링크를 읽거나, 해제·라벨·일시정지·재개할 수 없다(추측 포함).
    assert b_client.get(link_path()).status_code == 404
    assert b_client.delete(link_path()).status_code == 404
    label_denied = b_client.post(link_path("/label"), json={"label": "B가 수정"})
    # 거부 형태는 404(존재 부정) 또는 403(권한 거부) 둘 다 닫힘이다.
    assert label_denied.status_code in (403, 404), label_denied.status_code
    assert b_client.post(link_path("/pause")).status_code in (403, 404)
    assert b_client.post(link_path("/resume")).status_code in (403, 404)
    guessed = b_client.delete(PC_PAIRING_LINK_PATH.replace("{link_id}", "plink_" + "f" * 32))
    assert guessed.status_code == 404, guessed.status_code

    # A의 링크는 A에게 그대로 있고, A의 해제는 동작한다(내 자원에는 유효).
    listed_a = a_client.get(PC_PAIRING_PATH)
    assert any(row["link_id"] == link_id for row in listed_a.json().get("links") or [])
    assert a_client.delete(link_path()).status_code == 200
    assert all(row["link_id"] != link_id
               for row in a_client.get(PC_PAIRING_PATH).json().get("links") or [])


def test_pc_pairing_delete_of_a_guessed_link_never_touches_anyone():
    app, a_client, b_client, a, _b = clients()
    db = app.state.history_store.db
    app.state.pc_device_pairing_store = D1PcPairingStore(db)
    link_id = _pair_a_pc(db, a, datetime.now(timezone.utc))
    # B가 존재하지 않는 link_id로 해제를 시도해도 아무 링크도 남지 않는다.
    guessed = b_client.delete(
        PC_PAIRING_LINK_PATH.replace("{link_id}", "plink_" + "e" * 32),
    )
    assert guessed.status_code == 404, guessed.status_code
    listed_a = a_client.get(PC_PAIRING_PATH).json().get("links") or []
    assert [row["link_id"] for row in listed_a] == [link_id]


# ── 자동화 규칙: 권한 없으면 fail-closed(전체 행렬은 미확인) ─────────────────


def test_automation_rule_lanes_fail_closed_without_authority():
    app, a_client, b_client, _a, _b = clients()
    # B(그리고 A조차)의 생성은 B54 세션 브릿지가 없으면 403으로 닫힌다.
    for client in (a_client, b_client):
        created = client.post("/api/claw/automation/rules", json={"title": "x"})
        assert created.status_code == 403, created.status_code
        assert created.json()["error"]["code"] == "current_b54_session_unavailable"
    # 목록은 canonical 테넌트가 없으면 403으로 닫힌다 — 아무도 남의 규칙을 못 본다.
    for client in (a_client, b_client):
        listed = client.get("/api/claw/automation/rules")
        assert listed.status_code == 403, listed.status_code
        assert listed.json()["error"]["code"] == "canonical_tenant_unavailable"
    # 소유자-멤버 전체 행렬(생성 후 B의 읽기·수정·삭제·실행)은 세 층 가짜(B54 세션
    # 스냅샷·TenantMembership·실행 대상 개정 권한)가 필요해 미확인으로 남긴다.
