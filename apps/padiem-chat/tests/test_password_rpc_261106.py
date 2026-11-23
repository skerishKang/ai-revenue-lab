"""공통 로그인(옵트인) 이메일 가입·로그인 — Chat 수신 RPC.

padiem-auth가 이메일 자격 확인을 위해 부르는 /internal/password-verify와
/internal/password-register의 수신 계약. 증명 방식은 계정 삭제 수신기
(padiem-auth verifyAccountDeletionRpc)와 같은 v2 서비스 서명이고, 검사는
기존 password_auth와 잠금 규칙을 그대로 재사용한다.

Claims verified here:
(a) 유효한 증명 + 올바른 자격 → 200, 응답은 product_user_id뿐이다;
(b) 틀린 비밀번호 → 401과 실패 기록, 5회 잠금 뒤에는 올바른 자격도 401;
(c) 서명·시각 창·service id·본문 한도 위반 → 401;
(d) 같은 service id의 재사용 → 409 rpc_replay_detected;
(e) 가입 경로: 신규 200, 중복 409 account_exists, 형식 위반 400;
(f) 시크릿 미설정 → 404로 닫는다.
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
from app.history import D1HistoryStore, _password_user_id
from app.main import create_app
from app.password_auth import hash_password
from app.queue_store_proxy import QueueForwardingHistoryStore

# #8061: 공용 준비(BASE·SECRET·build·proof_headers·rpc)는
# _support/password_rpc가 소유한다.
from _support.password_rpc import (
    BASE, EMAIL, PASSWORD, REGISTER_PATH, SECRET, VERIFY_PATH, build,
    failed_attempts, proof_headers, rpc)

def test_valid_proof_and_credentials_return_only_the_product_user_id():
    app, _ = build()
    response = rpc(app, VERIFY_PATH, {"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 200
    answer = response.json()
    # #7551: beside the product user id, only the credential's creation time.
    assert set(answer) == {"ok", "product_user_id", "credential_epoch"}
    assert answer["ok"] is True and answer["product_user_id"] == _password_user_id(EMAIL)
    assert isinstance(answer["credential_epoch"], str) and answer["credential_epoch"]


def test_wrong_password_is_a_generic_401_and_records_one_failure():
    app, db = build()
    response = rpc(app, VERIFY_PATH, {"email": EMAIL, "password": "not-the-password"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"
    assert failed_attempts(db) == (1, None)


def test_five_failures_lock_the_account_even_for_the_correct_password():
    app, db = build()
    for _ in range(5):
        response = rpc(app, VERIFY_PATH, {"email": EMAIL, "password": "not-the-password"})
        assert response.status_code == 401
    failures, locked_until = failed_attempts(db)
    assert failures >= 5
    assert locked_until is not None
    correct = rpc(app, VERIFY_PATH, {"email": EMAIL, "password": PASSWORD})
    assert correct.status_code == 401


def test_proof_failures_are_unauthorized():
    app, _ = build()
    good = {"email": EMAIL, "password": PASSWORD}
    assert rpc(app, VERIFY_PATH, good, secret="wrong-secret-but-still-long-enough-00").status_code == 401
    assert rpc(app, VERIFY_PATH, good, at=int(time.time()) - 400).status_code == 401
    assert rpc(app, VERIFY_PATH, good, service_id="not-a-uuid").status_code == 401
    assert rpc(app, VERIFY_PATH, good, raw=b"x" * 513).status_code == 401
    assert rpc(app, VERIFY_PATH, good, raw=b"not-json").status_code == 401


def test_a_repeated_service_id_is_a_replay():
    app, _ = build(queue_wrapped=True)
    service_id = str(uuid.uuid4())
    first = rpc(app, VERIFY_PATH, {"email": EMAIL, "password": PASSWORD}, service_id=service_id)
    assert first.status_code == 200
    replay = rpc(app, VERIFY_PATH, {"email": EMAIL, "password": PASSWORD}, service_id=service_id)
    assert replay.status_code == 409
    assert replay.json()["error"]["code"] == "rpc_replay_detected"


def test_queue_wrapped_store_verifies_password_using_local_replay_store():
    app, db = build(queue_wrapped=True)
    response = rpc(app, VERIFY_PATH, {"email": EMAIL, "password": PASSWORD})

    assert response.status_code == 200
    assert db.conn.execute("SELECT COUNT(*) FROM password_rpc_service_ids").fetchone()[0] == 1


def test_register_path_signs_up_and_stays_honest_on_conflicts():
    app, _ = build()
    created = rpc(app, REGISTER_PATH, {"email": "new@example.test", "password": "another-good-one", "name": "New"})
    assert created.status_code == 200
    created_answer = created.json()
    assert set(created_answer) == {"ok", "product_user_id", "credential_epoch"}
    assert created_answer["product_user_id"] == _password_user_id("new@example.test")
    # The login that follows the signup answers with the same credential.
    login = rpc(app, VERIFY_PATH, {"email": "new@example.test", "password": "another-good-one"})
    assert login.json()["credential_epoch"] == created_answer["credential_epoch"]
    duplicate = rpc(app, REGISTER_PATH, {"email": EMAIL, "password": "another-good-one", "name": ""})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "account_exists"
    weak = rpc(app, REGISTER_PATH, {"email": "third@example.test", "password": "third@example.test", "name": ""})
    assert weak.status_code == 400
    assert weak.json()["error"]["code"] == "invalid_password"


def test_without_the_secret_the_routes_stay_closed():
    app, _ = build(secret=None)
    assert rpc(app, VERIFY_PATH, {"email": EMAIL, "password": PASSWORD}).status_code == 404
    assert rpc(app, REGISTER_PATH, {"email": EMAIL, "password": PASSWORD, "name": ""}).status_code == 404
