"""BookAI 기록 API(COM2 HMAC 레인) 공격 시험 — test_bookai_records.py가 고정하지
않은 공격 장면만: 재전송(멱등성), 공격자 비밀로 계산한 서명, 개행 헤더, payload로
다른 계정 끼워넣기, 레코드 수 폭탄의 부분 쓰기 금지, 비밀 노출, 깊은 중첩 JSON.

모의 대역만 사용한다(실제 auth·chat·bookai 서비스 접속 없음).
"""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import sqlite3

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from app.bookai_records import MAX_BODY_BYTES, RECORDS_PATH, install_bookai_records_routes
from app.d1_sqlite import SqliteD1

NOW = 1793534400
SECRET = "synthetic-bookai-records-test-key"
ATTACKER_SECRET = "attacker-chosen-secret-not-the-server-one"
ALICE = "sub_alice"
BOB = "sub_bob"


def record(record_id="note-1", *, updated_at=100, deleted=False, text="saved"):
    return {"record_id": record_id, "book_id": "bible-web", "locator": "ACT.9.3",
            "kind": "note", "payload": {"text": text}, "updated_at": updated_at,
            "deleted": deleted}


def wire(records):
    return json.dumps({"records": records}, ensure_ascii=False,
                      separators=(",", ":")).encode()


def signed(method, path, body=b"", *, subject=ALICE, timestamp=NOW, secret=SECRET):
    stamp = str(timestamp)
    message = "\n".join((method, path, stamp, subject, hashlib.sha256(body).hexdigest()))
    return {"content-type": "application/json", "x-bookai-subject": subject,
            "x-bookai-timestamp": stamp,
            "x-bookai-signature": hmac.new(secret.encode(), message.encode(),
                                           hashlib.sha256).hexdigest()}


@pytest.fixture
def api(tmp_path):
    connection = sqlite3.connect(tmp_path / "chat.sqlite3", isolation_level=None,
                                 check_same_thread=False)
    connection.row_factory = sqlite3.Row
    migration = Path(__file__).resolve().parents[1] / "migrations" / "082_bookai_records.sql"
    connection.executescript(migration.read_text(encoding="utf-8"))
    app = Starlette()
    install_bookai_records_routes(app, env={"BOOKAI_COM2_SYNC_SECRET": SECRET},
                                  db_binding=SqliteD1(connection), clock=lambda: NOW)
    with TestClient(app) as client:
        yield client, connection
    connection.close()


def post(client, records, **kwargs):
    body = wire(records)
    return client.post(RECORDS_PATH, content=body,
                       headers=signed("POST", RECORDS_PATH, body, **kwargs))


def get(client, path=RECORDS_PATH, **kwargs):
    return client.get(path, headers=signed("GET", path, **kwargs))


def test_replayed_identical_post_writes_once(api):
    """재전송(같은 서명 두 번): 같은 내용의 재전송은 두 번 쓰이지 않는다 — 행 1개,
    내용 불변. 응답의 accepted=1은 동일 타임스탬프 처리 계약(test_latest_wins가
    고정)이며, 무해 재전송이라는 설계 판단을 기록한다(서버는 재전송을 거부하지
    않고 멱등 병합으로 무력화한다)."""
    client, connection = api
    first = post(client, [record(text="Alice")])
    second = post(client, [record(text="Alice")])
    assert first.status_code == 200 and second.status_code == 200
    assert connection.execute("SELECT count(*) FROM bookai_records").fetchone()[0] == 1
    assert get(client).json()["records"][0]["payload"]["text"] == "Alice"


def test_attacker_computed_signature_with_own_secret_is_refused(api):
    client, connection = api
    body = wire([record(text="Alice")])
    attacker = signed("POST", RECORDS_PATH, body, secret=ATTACKER_SECRET)
    assert client.post(RECORDS_PATH, content=body, headers=attacker).status_code == 401
    assert connection.execute("SELECT count(*) FROM bookai_records").fetchone()[0] == 0


@pytest.mark.parametrize("subject_header", ["sub_alice\nsub_bob", "sub_alice\rsub_bob",
                                            "sub_alice sub_bob", ""])
def test_newline_and_empty_subject_headers_are_signature_failures(api, subject_header):
    client, connection = api
    body = wire([record()])
    headers = signed("POST", RECORDS_PATH, body)
    headers["x-bookai-subject"] = subject_header
    assert client.post(RECORDS_PATH, content=body, headers=headers).status_code == 401
    stamp = headers["x-bookai-timestamp"] + "\n1800000000"
    headers = signed("POST", RECORDS_PATH, body)
    headers["x-bookai-timestamp"] = stamp
    assert client.post(RECORDS_PATH, content=body, headers=headers).status_code == 401
    assert connection.execute("SELECT count(*) FROM bookai_records").fetchone()[0] == 0


def test_payload_mentioning_another_subject_stays_in_the_signed_tenant(api):
    """payload 안에 다른 sub를 끼워도 소속은 서명된 subject다 — sub_bob 계정에는
    아무것도 보이지 않는다."""
    client, connection = api
    smuggled = record("smuggled", text="x")
    smuggled["payload"] = {"text": "x", "sub": BOB, "owner": BOB}
    assert post(client, [smuggled]).status_code == 200
    assert get(client, subject=ALICE).json()["records"][0]["record_id"] == "smuggled"
    assert get(client, subject=BOB).json()["records"] == []
    assert connection.execute(
        "SELECT subject FROM bookai_records").fetchone()[0] == ALICE


def test_record_count_bomb_writes_exactly_what_it_accepted(api):
    """레코드 수 폭탄: 5,000건 일괄 — 응답(accepted/kept_newer)과 실제 행 수가
    정확히 일치한다(부분 쓰기 없음). 실패 시에도 원자적으로 503이다."""
    client, connection = api
    rows = [record(f"bomb-{n:05d}", updated_at=100 + n, text=f"t{n}")
            for n in range(5000)]
    body = wire(rows)
    assert len(body) <= MAX_BODY_BYTES
    response = post(client, rows)
    assert response.status_code in (200, 503)
    if response.status_code == 200:
        assert response.json()["accepted"] == 5000
        assert connection.execute(
            "SELECT count(*) FROM bookai_records").fetchone()[0] == 5000
    else:
        assert connection.execute(
            "SELECT count(*) FROM bookai_records").fetchone()[0] == 0


def test_responses_never_contain_the_sync_secret(api):
    client, _ = api
    for response in (post(client, [record()]), get(client),
                     get(client, RECORDS_PATH + "?since=-1"),
                     client.post(RECORDS_PATH, content=b"{}\n",
                                 headers=signed("POST", RECORDS_PATH, b"{}\n"))):
        assert SECRET not in response.text
        assert ATTACKER_SECRET not in response.text


def test_deeply_nested_payload_is_bounded_not_a_crash(api):
    """JSON 깊이 폭탄: RecursionError가 미처리되면 500(결함 — xfail strict로
    관측, 수정은 CTO 배정). 부분 쓰기는 어느 쪽이든 없다."""
    client, connection = api
    depth = 100_000
    body = (b'{"records":[{"record_id":"deep","book_id":"b","locator":"A.1",'
            b'"kind":"note","payload":' + b'{"n":' * depth + b'{}' + b'}' * depth +
            b',"updated_at":100,"deleted":false}]}')
    assert len(body) <= MAX_BODY_BYTES
    headers = signed("POST", RECORDS_PATH, body)
    app = Starlette()
    install_bookai_records_routes(app, env={"BOOKAI_COM2_SYNC_SECRET": SECRET},
                                  db_binding=SqliteD1(connection), clock=lambda: NOW)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(RECORDS_PATH, content=body, headers=headers)
    assert response.status_code == 400, response.status_code  # 결함: 실제 500
    assert connection.execute("SELECT count(*) FROM bookai_records").fetchone()[0] == 0


test_deeply_nested_payload_is_bounded_not_a_crash = pytest.mark.xfail(
    reason=(
        "결함 D2(낮음): 깊은 중첩 payload의 json.loads가 RecursionError를 던지고 "
        "bookai_records.py:42의 except (ValueError, UnicodeError)가 이를 놓쳐 미처리 "
        "500이 된다(부분 쓰기는 없다). 올바른 계약은 400 invalid_records. 위치: "
        " apps/padiem-chat/app/bookai_records.py:42(json.loads 호출부의 예외 범위). "
        " 수정은 CTO가 다른 레인에 배정."
    ), strict=True)(test_deeply_nested_payload_is_bounded_not_a_crash)
