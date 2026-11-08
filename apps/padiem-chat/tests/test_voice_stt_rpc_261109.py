"""호스트→Chat-Worker 음성 STT RPC 수신 계약 — #7228 복구 (voice (ii)).

COM2 호스트가 `app.state.voice_stt_transport`를 채우기 위해 부르는
`/internal/rpc/voice_stt`의 수신 계약. 증명·재생 방지는 password RPC와 같은
v2 서비스 서명 + history store의 service id 소비를 그대로 쓰고, 디스패치만
Service-Binding transport(``CloudflareVoiceSttServiceTransport``와 같은
모양)로 돌린다. STT Worker에는 새 HTTPS 입구가 없다.

Claims verified here:
(a) 유효한 증명 + live_token → 200, 응답은 {status, body}이고 upstream 상태가 그대로 온다;
(b) transcribe → audioDataUrl·language가 전달되고, 한도 초과 audio는 400;
(c) 서명·시각 창 위반 → 401, 같은 service id 재사용 → 409;
(d) 시크릿 미설정 → 404로 닫는다(호출 전용 호스트가 이 경로를 열지 않음);
(e) transport의 ServiceBindingResponseError → 503 voice_stt_unavailable;
(f) 응답 한도 초과 upstream 본문 → 502.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import sqlite3
import time
import uuid
from types import SimpleNamespace

import httpx

from app.config import Settings
from app.history import D1HistoryStore
from app.main import create_app
from app.service_binding_response import ServiceBindingResponseError

from test_6446_account_isolation_sweep import apply_all_migrations

BASE = "https://chat.example.test"
SECRET = "chat-test-voice-rpc-secret-value-0000000"
PATH = "/internal/rpc/voice_stt"
AUDIO_DATA_URL = "data:audio/pcm;base64," + "A" * 512


class Statement:
    def __init__(self, db, sql, params=()):
        self.db, self.sql, self.params = db, sql, params

    def bind(self, *params):
        return Statement(self.db, self.sql, params)

    async def first(self):
        row = self.db.conn.execute(self.sql, self.params).fetchone()
        return dict(row) if row else None

    async def run(self):
        cursor = self.db.conn.execute(self.sql, self.params)
        return SimpleNamespace(
            results=[dict(row) for row in cursor.fetchall()],
            meta={"changes": cursor.rowcount},
        )


class SqliteD1:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:", isolation_level=None)
        self.conn.row_factory = sqlite3.Row

    def prepare(self, sql):
        return Statement(self, sql)

    async def batch(self, statements):
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            results = []
            for statement in statements:
                cursor = self.conn.execute(statement.sql, statement.params)
                results.append(SimpleNamespace(
                    results=[dict(row) for row in cursor.fetchall()],
                    meta={"changes": cursor.rowcount},
                ))
            self.conn.execute("COMMIT")
            return results
        except Exception:
            self.conn.execute("ROLLBACK")
            raise


class FakeSttTransport:
    """The shape both the Worker's Service-Binding transport and the host's
    RPC transport expose; calls are recorded so tests assert the envelope."""

    def __init__(self, *, status=200, body=b'{"token":"t","session":{}}', error=None):
        self.calls = []
        self.status = status
        self.body = body
        self.error = error

    async def live_token(self, *, body, product_id, session_id):
        self.calls.append(("live_token", dict(body), product_id, session_id))
        if self.error is not None:
            raise self.error
        return self.status, self.body

    async def transcribe(self, *, body, product_id, session_id):
        self.calls.append(("transcribe", dict(body), product_id, session_id))
        if self.error is not None:
            raise self.error
        return self.status, self.body


def build(secret=SECRET, *, transport=None):
    db = SqliteD1()
    apply_all_migrations(db)
    store = D1HistoryStore(db)
    settings = Settings.from_values(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url=BASE,
        session_secret="voice-rpc-test-session-secret-000000",
        session_max_age_seconds=3600,
        voice_rpc_secret=secret,
    )
    app = create_app(settings=settings, d1_binding=db, history_store=store,
                     voice_stt_transport=transport)
    return app, db


def proof_headers(secret, path, body, *, at=None, service_id=None):
    at = int(time.time()) if at is None else at
    service_id = str(uuid.uuid4()) if service_id is None else service_id
    signed = b"\n".join((b"v2", b"POST", path.encode(), str(at).encode(), service_id.encode(), body))
    proof = "v2=" + hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return {
        "content-type": "application/json",
        "x-padiem-service-at": str(at),
        "x-padiem-service-id": service_id,
        "x-padiem-service-proof": proof,
    }


def rpc(app, payload, *, secret=SECRET, at=None, service_id=None, raw=None, path=PATH):
    body = raw if raw is not None else json.dumps(payload, separators=(",", ":")).encode()
    headers = proof_headers(secret, path, body, at=at, service_id=service_id)

    async def inner():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE
        ) as client:
            return await client.post(path, content=body, headers=headers)

    return asyncio.run(inner())


def test_valid_proof_live_token_returns_status_and_body():
    transport = FakeSttTransport()
    app, _ = build(transport=transport)
    response = rpc(app, {"op": "live_token", "productId": "p1", "sessionId": "s1"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == 200
    assert json.loads(data["body"])["token"] == "t"
    assert transport.calls == [("live_token", {"sessionId": "s1"}, "p1", "s1")]


def test_transcribe_forwards_language_and_audio_and_enforces_the_audio_bound():
    transport = FakeSttTransport(body=b'{"text":"ok"}')
    app, _ = build(transport=transport)
    response = rpc(app, {"op": "transcribe", "productId": "p1", "sessionId": "s1",
                         "language": "ko", "audioDataUrl": AUDIO_DATA_URL})
    assert response.status_code == 200
    assert transport.calls[0][1] == {"language": "ko", "audioDataUrl": AUDIO_DATA_URL}

    oversized = "data:audio/pcm;base64," + "A" * (5 * 1024 * 1024 + 1)
    response = rpc(app, {"op": "transcribe", "productId": "p1", "sessionId": "s1",
                         "language": "ko", "audioDataUrl": oversized})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert len(transport.calls) == 1


def test_bad_proof_and_replayed_service_id_are_refused():
    app, _ = build(transport=FakeSttTransport())
    payload = {"op": "live_token", "productId": "p1", "sessionId": "s1"}
    assert rpc(app, payload, secret="wrong-secret-value-000000000000000000").status_code == 401
    stale = int(time.time()) - 400
    assert rpc(app, payload, at=stale).status_code == 401
    fixed_id = str(uuid.uuid4())
    assert rpc(app, payload, service_id=fixed_id).status_code == 200
    assert rpc(app, payload, service_id=fixed_id).status_code == 409


def test_unconfigured_secret_keeps_the_route_closed():
    app, _ = build(secret=None, transport=FakeSttTransport())
    response = rpc(app, {"op": "live_token", "productId": "p1", "sessionId": "s1"})
    assert response.status_code == 404


def test_transport_failure_maps_to_the_fail_closed_503():
    app, _ = build(transport=FakeSttTransport(error=ServiceBindingResponseError("refused")))
    response = rpc(app, {"op": "live_token", "productId": "p1", "sessionId": "s1"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "voice_stt_unavailable"


def test_oversized_upstream_body_is_a_502_not_a_leak():
    big = b"x" * (1024 * 1024 + 1)
    app, _ = build(transport=FakeSttTransport(body=big))
    response = rpc(app, {"op": "live_token", "productId": "p1", "sessionId": "s1"})
    assert response.status_code == 502
    assert "x" * 16 not in response.text
