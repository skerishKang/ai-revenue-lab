"""BookAI v1 API authorization and persistence over the real SQLite facade."""
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


def record(record_id="note-1", *, updated_at=100, deleted=False, text="saved"):
    return {"record_id": record_id, "book_id": "bible-web", "locator": "ACT.9.3",
            "kind": "note", "payload": {"text": text}, "updated_at": updated_at, "deleted": deleted}


def wire(records):
    return json.dumps({"records": records}, ensure_ascii=False, separators=(",", ":")).encode()


def signed(method, path, body=b"", *, subject="sub_alice", timestamp=NOW, secret=SECRET):
    stamp = str(timestamp)
    message = "\n".join((method, path, stamp, subject, hashlib.sha256(body).hexdigest()))
    return {"content-type": "application/json", "x-bookai-subject": subject,
            "x-bookai-timestamp": stamp,
            "x-bookai-signature": hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()}


@pytest.fixture
def api(tmp_path):
    connection = sqlite3.connect(tmp_path / "chat.sqlite3", isolation_level=None, check_same_thread=False)
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
    return client.post(RECORDS_PATH, content=body, headers=signed("POST", RECORDS_PATH, body, **kwargs))


def get(client, path=RECORDS_PATH, **kwargs):
    return client.get(path, headers=signed("GET", path, **kwargs))


def test_roundtrip_is_private_and_subject_scoped_even_with_same_record_id(api):
    client, _ = api
    assert post(client, [record(text="Alice")]).json() == {"accepted": 1, "kept_newer": []}
    assert post(client, [record(text="Bob")], subject="sub_bob").json() == {"accepted": 1, "kept_newer": []}
    for subject, text in [("sub_alice", "Alice"), ("sub_bob", "Bob")]:
        response = get(client, subject=subject)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "private, no-store"
        assert response.json() == {"records": [record(text=text)], "next_since": 100, "more": False}
        assert "subject" not in response.json()["records"][0]
    assert get(client, subject="sub_empty").json() == {"records": [], "next_since": 0, "more": False}
    assert get(client, RECORDS_PATH + "?subject=sub_bob").status_code == 400
    assert post(client, [{**record(), "subject": "sub_bob"}]).status_code == 400


@pytest.mark.parametrize("mode", ["unsigned", "signature", "body", "subject", "path", "method", "expired", "future"])
def test_invalid_signature_cannot_write(api, mode):
    client, connection = api
    body = wire([record()])
    headers = signed("POST", RECORDS_PATH, body)
    if mode == "unsigned": headers = {"content-type": "application/json"}
    elif mode == "signature": headers["x-bookai-signature"] = "0" * 64
    elif mode == "body": body = wire([record(text="tampered")])
    elif mode == "subject": headers["x-bookai-subject"] = "sub_bob"
    elif mode == "path": headers = signed("POST", RECORDS_PATH + "?since=1", body)
    elif mode == "method": headers = signed("GET", RECORDS_PATH, body)
    elif mode == "expired": headers = signed("POST", RECORDS_PATH, body, timestamp=NOW - 301)
    elif mode == "future": headers = signed("POST", RECORDS_PATH, body, timestamp=NOW + 301)
    response = client.post(RECORDS_PATH, content=body, headers=headers)
    assert response.status_code == 401
    assert connection.execute("SELECT count(*) FROM bookai_records").fetchone()[0] == 0


@pytest.mark.parametrize("delta", [-300, 300])
def test_exact_five_minute_boundary_is_accepted(api, delta):
    client, _ = api
    assert post(client, [record()], timestamp=NOW + delta).status_code == 200


def test_exact_query_string_and_get_empty_body_are_signed(api):
    client, _ = api
    post(client, [record()])
    path = RECORDS_PATH + "?limit=2&since=%30"
    assert get(client, path).json()["next_since"] == 100
    assert client.get(RECORDS_PATH + "?since=1&limit=2",
                      headers=signed("GET", path)).status_code == 401
    assert client.request("GET", RECORDS_PATH, content=b"unexpected",
                          headers=signed("GET", RECORDS_PATH)).status_code == 401


def test_latest_wins_equal_is_idempotent_and_tombstone_survives_stale_writer(api):
    client, _ = api
    assert post(client, [record(updated_at=200)]).status_code == 200
    assert post(client, [record(updated_at=100, text="stale")]).json() == {"accepted": 0, "kept_newer": ["note-1"]}
    assert post(client, [record(updated_at=200, text="tie")]).json() == {"accepted": 1, "kept_newer": []}
    assert get(client).json()["records"][0]["payload"]["text"] == "saved"
    tombstone = record(updated_at=300, deleted=True)
    assert post(client, [tombstone]).json() == {"accepted": 1, "kept_newer": []}
    assert post(client, [record(updated_at=250)]).json() == {"accepted": 0, "kept_newer": ["note-1"]}
    assert get(client, RECORDS_PATH + "?since=200").json() == {"records": [tombstone], "next_since": 300, "more": False}
    assert get(client, RECORDS_PATH + "?since=300").json() == {"records": [], "next_since": 300, "more": False}


@pytest.mark.parametrize("timestamp", [0, 200])
def test_stable_order_and_limit_above_500_preserve_equal_timestamp_records(api, timestamp):
    client, _ = api
    rows = [record(f"record-{n:04d}", updated_at=timestamp) for n in range(620)]
    assert post(client, list(reversed(rows))).json() == {"accepted": 620, "kept_newer": []}
    first = get(client).json()
    assert first == {"records": rows[:500], "next_since": timestamp, "more": True}
    assert get(client, RECORDS_PATH + f"?since={max(0, timestamp - 1)}&limit=1000").json() == {
        "records": rows, "next_since": timestamp, "more": False}


@pytest.mark.parametrize("bad", [
    {**record(), "updated_at": True}, {**record(), "updated_at": -1},
    {**record(), "updated_at": 9007199254740992}, {**record(), "deleted": 1},
    {**record(), "payload": []}, {**record(), "kind": "other"},
    {**record(), "locator": ""}, {**record(), "record_id": ""},
])
def test_invalid_batch_is_rejected_without_partial_writes(api, bad):
    client, connection = api
    assert post(client, [record("valid"), bad]).status_code == 400
    assert connection.execute("SELECT count(*) FROM bookai_records").fetchone()[0] == 0


def test_duplicate_ids_and_nonfinite_json_rejected(api):
    client, _ = api
    assert post(client, [record(), record()]).status_code == 400
    body = b'{"records":[{"payload":{"value":NaN}}]}'
    assert client.post(RECORDS_PATH, content=body, headers=signed("POST", RECORDS_PATH, body)).status_code == 400
    assert post(client, []).json() == {"accepted": 0, "kept_newer": []}


@pytest.mark.parametrize("query", ["since=-1", "limit=0", "limit=9007199254740992", "since=1&since=2"])
def test_invalid_query_is_rejected(api, query):
    client, _ = api
    assert get(client, RECORDS_PATH + "?" + query).status_code == 400


def test_post_five_mib_limit_is_bytes_and_atomic(api):
    client, connection = api
    small = wire([record(text="")])
    exact = wire([record(text="a" * (MAX_BODY_BYTES - len(small)))])
    assert len(exact) == MAX_BODY_BYTES
    assert client.post(RECORDS_PATH, content=exact, headers=signed("POST", RECORDS_PATH, exact)).status_code == 200
    oversized = wire([record("too-large", text="가" * (MAX_BODY_BYTES // 3))])
    assert len(oversized) > MAX_BODY_BYTES
    assert client.post(RECORDS_PATH, content=oversized, headers=signed("POST", RECORDS_PATH, oversized)).status_code == 413
    assert connection.execute("SELECT count(*) FROM bookai_records").fetchone()[0] == 1


def test_database_failure_rolls_back_entire_batch_and_keeps_retryable_response(api):
    client, connection = api
    connection.executescript("""
        CREATE TRIGGER simulate_disk_failure BEFORE INSERT ON bookai_records
        WHEN NEW.record_id='failure' BEGIN SELECT RAISE(ABORT, 'fixture failure'); END;
    """)
    response = post(client, [record("first"), record("failure")])
    assert response.status_code == 503
    assert response.json() == {"error": "sync_unavailable"}
    assert connection.execute("SELECT count(*) FROM bookai_records").fetchone()[0] == 0


def test_missing_secret_does_not_use_browser_session(api):
    client, _ = api
    client.app.state.bookai_records_service._secret = ""
    response = client.get(RECORDS_PATH, headers={"cookie": "session=fixture"})
    assert response.status_code == 503
    assert response.json() == {"error": "sync_unavailable"}
