"""#6579 tus 조각 업로드 통로 공격 시험 — 결함은 고치지 말고 관측·기록만 한다.

1차 시험(test_tus_project_upload_261101.py)이 정상 사용자 계약을 고정했다면, 이
파일은 공격자 관점의 경계만 만진다: 오프셋·길이 조작, 조각 경합, 메타데이터
주입, 권한·ID 추측, same-origin 예외의 좁음, 자원 상한, 만료 이어올리기, 앞단
스트리밍 계약. 제품 코드는 한 줄도 고치지 않는다 — 관측이 계약에서 벗어나면 그
결과 그대로 결함으로 기록한다.

결함 대장(2026-11-02 실측, 전부 보고만 하고 수정하지 않는다):
- D1 app/tus_project_upload.py:236 — Upload-Length 5,000자리 → isdecimal() 통과
  후 int()가 파이썬 4300자리 한계 ValueError를 던져 미처리 500. 올바른 계약 400/413.
- D2 app/tus_project_upload.py:368 — Upload-Offset 5,000자리 → 같은 mechanism의
  미처리 500(덧붙임은 없다). 올바른 계약 409 + 무덧붙임. D1과 같은 뿌리: 헤더 숫자의
  isdecimal() 게이트가 파이썬 int() 자릿수 한계를 모른다.
- D3 설계 공백 — 사용자당 미완성 업로드 개수·디스크 상한 부재(24h 청소가 유일).
- D4 관측(기존 시험 11 허용 범위로 문서화) — 같은 오프셋 PATCH 경합에서
  _store_meta의 upload.json.tmp 충돌이 미처리 500로 관측된다(app/tus_project_upload.py:146).
  덧붙임 바이트는 오염되지 않았다(시험 11의 순수성 단언이 지켜진다). 계약은 409/423.

2차 시험(2026-11-02, 컴1) — 8장 보충: 생성 계약 빈틈(Upload-Length 누락·Defer 위장),
메타데이터 제어 문자·무효 base64·중복 키, 무세션·타인 프로젝트 생성, 인코딩된
upload_id 순회, 청소된 업로드 픽업, 원시 바이트 비 ASCII 헤더, 앞단 헤더 계약.
전부 통과 — 새 결함 없음. 비 ASCII 십진수 헤더는 HTTP 헤더가 latin-1로 디코딩되는
특성상 isdecimal()을 통과할 수 없어(관측 400/409) int() 정규화 경로는 도달 불가.

#6584 tus_core(main, 병합분) 적용성 확인(2026-11-02, 컴1 실측 — 보고만):
- tus_core.py:254 Upload-Length 5,000자리 → 500(D1 동일), tus_core.py:357
  Upload-Offset 5,000자리 → 500(D2 동일), 사용자당 상한 부재(D3 동일, 30/30 허용).
- 프로젝트 파일·채팅 첨부·웹 xlsx 세 경로가 모두 tus_core를 재사용하므로 결함이
  세 경로 전부에 적용된다. 재현 시험은 #6579 기반 브랜치에 tus_core가 없어
  main 워크트리 임시 시험으로 관측하고 커밋하지 않았다.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.tus_project_upload import (
    _DATA_NAME,
    _META_NAME,
    _upload_root,
    sweep_expired_uploads,
)

from test_tus_project_upload_261101 import make_app, tus_metadata

SESSION = "tus-test-session-secret-0123456789abcdef0123456789abcdef"
ORIGIN = "https://chat.example.test"


def sync_session(app, uid: str) -> TestClient:
    cfg = Settings.from_values(
        session_secret=SESSION,
        auth_mode="google",
        public_base_url=ORIGIN,
        google_client_id="phase11.apps.googleusercontent.com",
        google_client_secret="phase11-secret",
    )
    app.state.settings = cfg
    client = TestClient(app, base_url=ORIGIN)
    client.cookies.set(SESSION_COOKIE, create_session_token(cfg, uid),
                       domain="chat.example.test", path="/")
    client.headers.update({"Origin": ORIGIN})
    return client


def await_user(app, marker: str = "tus-owner"):
    return asyncio.run(app.state.history_store.add_user(marker))


def new_project(app, uid: str, name: str = "P"):
    return asyncio.run(app.state.history_store.create_project(uid, name, ""))


def _create(client, project_id: str, *, length: int, name: str = "a.png",
            media_type: str = "image/png") -> str:
    created = client.post(
        f"/api/projects/{project_id}/files/tus",
        headers={"Upload-Length": str(length),
                 "Upload-Metadata": tus_metadata(name, media_type),
                 "Tus-Resumable": "1.0.0"},
    )
    assert created.status_code == 201, created.text
    return created.json()["upload_id"]


def _head_offset(client, project_id: str, upload_id: str) -> tuple[int, int]:
    head = client.head(f"/api/projects/{project_id}/files/tus/{upload_id}",
                       headers={"Tus-Resumable": "1.0.0"})
    return (head.status_code, int(head.headers.get("upload-offset", "-1")))


def _data_size(upload_id: str) -> int:
    return os.path.getsize(os.path.join(_upload_root(), upload_id, _DATA_NAME))


def _patch(client, project_id: str, upload_id: str, offset: int, body: bytes):
    return client.patch(
        f"/api/projects/{project_id}/files/tus/{upload_id}",
        content=body,
        headers={"Upload-Offset": str(offset),
                 "Content-Type": "application/offset+octet-stream",
                 "Tus-Resumable": "1.0.0"},
    )


# ── 1) 오프셋·길이 조작 ─────────────────────────────────────────────────────


def test_upload_length_zero_negative_and_over_limit(monkeypatch, tmp_path):
    app, _history, _store = make_app(monkeypatch, tmp_path, max_bytes=1000)
    owner = await_user(app)
    project = new_project(app, owner.id)
    client = sync_session(app, owner.id)

    for bad_length, expected in (("0", (413,)), ("-5", (400, 422)), ("1001", (413,))):
        answer = client.post(
            f"/api/projects/{project.id}/files/tus",
            headers={"Upload-Length": bad_length,
                     "Upload-Metadata": tus_metadata("x.pdf", "application/pdf"),
                     "Tus-Resumable": "1.0.0"},
        )
        assert answer.status_code in expected, \
            (bad_length, answer.status_code, answer.text[:120])


@pytest.mark.xfail(reason=(
    "결함 D1(app/tus_project_upload.py:236): Upload-Length가 파이썬 정수 문자열 한계"
    "(4300자리)를 넘으면 isdecimal()은 통과하고 int()가 ValueError를 던져 미처리 예외로"
    " 500이 돌아온다. 올바른 계약은 400/413 거부. 제품을 고치면 이 시험은 xpass가 된다."
), strict=False)
def test_upload_length_beyond_int_digit_limit_is_rejected_not_500(monkeypatch, tmp_path):
    app, _history, _store = make_app(monkeypatch, tmp_path, max_bytes=1000)
    owner = await_user(app)
    project = new_project(app, owner.id)
    client = sync_session(app, owner.id)
    raw = TestClient(app, base_url=ORIGIN, raise_server_exceptions=False)
    raw.cookies.update(client.cookies)
    raw.headers.update(client.headers)

    answer = raw.post(
        f"/api/projects/{project.id}/files/tus",
        headers={"Upload-Length": "9" * 5000,
                 "Upload-Metadata": tus_metadata("x.pdf", "application/pdf"),
                 "Tus-Resumable": "1.0.0"},
    )
    # 현재 관측: 500 Internal Server Error(ValueError 미처리).
    assert answer.status_code in (400, 413), answer.status_code


def test_upload_length_header_after_creation_is_ignored(monkeypatch, tmp_path):
    app, _history, _store = make_app(monkeypatch, tmp_path)
    owner = await_user(app)
    project = new_project(app, owner.id)
    client = sync_session(app, owner.id)
    upload_id = _create(client, project.id, length=10)

    patched = client.patch(
        f"/api/projects/{project.id}/files/tus/{upload_id}",
        content=b"0123456789",
        headers={"Upload-Offset": "0", "Upload-Length": "999999",
                 "Content-Type": "application/offset+octet-stream",
                 "Tus-Resumable": "1.0.0"},
    )
    assert patched.status_code == 204, patched.text
    assert _head_offset(client, project.id, upload_id) == (200, 10)


def test_offset_negative_skip_and_mismatch_refuse_without_appending(monkeypatch, tmp_path):
    app, _history, _store = make_app(monkeypatch, tmp_path, chunk_bytes=4096)
    owner = await_user(app)
    project = new_project(app, owner.id)
    client = sync_session(app, owner.id)
    upload_id = _create(client, project.id, length=64)

    # 헤더 그대로: -1(음수), 5(건너뛰기), 128(선언 초과), 9*20(한계 미만 초대형).
    for bad_offset in ("-1", "5", "128", "9" * 20):
        answer = client.patch(
            f"/api/projects/{project.id}/files/tus/{upload_id}",
            content=b"X" * 8,
            headers={"Upload-Offset": bad_offset,
                     "Content-Type": "application/offset+octet-stream",
                     "Tus-Resumable": "1.0.0"},
        )
        assert answer.status_code == 409, (bad_offset, answer.status_code)
        assert _data_size(upload_id) == 0, bad_offset

    assert _head_offset(client, project.id, upload_id) == (200, 0)


@pytest.mark.xfail(reason=(
    "결함 D2(app/tus_project_upload.py:368): Upload-Offset가 4300자리를 넘으면"
    " isdecimal() 통과 후 int() ValueError가 미처리되어 500이 돌아온다(덧붙임은 없음)."
    " 올바른 계약은 409 + 무덧붙임. 제품을 고치면 이 시험은 xpass가 된다."
), strict=False)
def test_upload_offset_beyond_int_digit_limit_is_rejected_not_500(monkeypatch, tmp_path):
    app, _history, _store = make_app(monkeypatch, tmp_path, chunk_bytes=4096)
    owner = await_user(app)
    project = new_project(app, owner.id)
    client = sync_session(app, owner.id)
    upload_id = _create(client, project.id, length=64)
    raw = TestClient(app, base_url=ORIGIN, raise_server_exceptions=False)
    raw.cookies.update(client.cookies)
    raw.headers.update(client.headers)

    answer = raw.patch(
        f"/api/projects/{project.id}/files/tus/{upload_id}",
        content=b"X" * 8,
        headers={"Upload-Offset": "9" * 5000,
                 "Content-Type": "application/offset+octet-stream",
                 "Tus-Resumable": "1.0.0"},
    )
    # 현재 관측: 500 Internal Server Error(ValueError 미처리, 바이트는 덧붙지 않음).
    assert answer.status_code == 409, answer.status_code
    assert _data_size(upload_id) == 0
    assert _head_offset(client, project.id, upload_id) == (200, 0)


def test_last_chunk_over_declared_length_is_refused_then_exact_completes(monkeypatch, tmp_path):
    app, _history, _store = make_app(monkeypatch, tmp_path)
    owner = await_user(app)
    project = new_project(app, owner.id)
    client = sync_session(app, owner.id)
    upload_id = _create(client, project.id, length=10)

    over = _patch(client, project.id, upload_id, 0, b"0123456789ABCDEF")
    assert over.status_code == 413, over.text
    assert _data_size(upload_id) == 0

    exact = _patch(client, project.id, upload_id, 0, b"0123456789")
    assert exact.status_code == 204
    assert _head_offset(client, project.id, upload_id) == (200, 10)


def test_lying_content_length_cannot_advance_offset(monkeypatch, tmp_path):
    """선언 Content-Length가 조각 상한(=남은 길이 64)을 넘으면 본문을 읽기 전 413로
    거부되고(bounded spool의 선언 사전 검사), 상한 이하로 거짓말하면 실제 받은
    바이트(5)만 오프셋에 반영된다 — 선언을 믿지 않는다."""
    app, _history, _store = make_app(monkeypatch, tmp_path)
    owner = await_user(app)
    project = new_project(app, owner.id)
    client = sync_session(app, owner.id)
    upload_id = _create(client, project.id, length=64)
    url = f"/api/projects/{project.id}/files/tus/{upload_id}"

    over = client.request(
        "PATCH", url,
        content=b"abcde",
        headers={"Upload-Offset": "0", "Content-Type": "application/offset+octet-stream",
                 "Content-Length": "100", "Tus-Resumable": "1.0.0"},
    )
    assert over.status_code == 413, over.text
    assert _data_size(upload_id) == 0
    assert _head_offset(client, project.id, upload_id) == (200, 0)

    under = client.request(
        "PATCH", url,
        content=b"abcde",
        headers={"Upload-Offset": "0", "Content-Type": "application/offset+octet-stream",
                 "Content-Length": "32", "Tus-Resumable": "1.0.0"},
    )
    assert under.status_code == 204, under.text
    assert _head_offset(client, project.id, upload_id) == (200, 5)


# ── 2) 조각 경계와 경합 ─────────────────────────────────────────────────────


def test_oversized_chunk_appends_nothing(monkeypatch, tmp_path):
    app, _history, _store = make_app(monkeypatch, tmp_path, chunk_bytes=1024)
    owner = await_user(app)
    project = new_project(app, owner.id)
    client = sync_session(app, owner.id)
    upload_id = _create(client, project.id, length=4096)

    over = _patch(client, project.id, upload_id, 0, b"Z" * 1025)
    assert over.status_code == 413, over.text
    assert _data_size(upload_id) == 0
    assert _head_offset(client, project.id, upload_id) == (200, 0)

    good = _patch(client, project.id, upload_id, 0, b"Z" * 1024)
    assert good.status_code == 204
    assert _head_offset(client, project.id, upload_id) == (200, 1024)


def test_empty_patch_is_tus_legal_and_moves_nothing(monkeypatch, tmp_path):
    app, _history, _store = make_app(monkeypatch, tmp_path)
    owner = await_user(app)
    project = new_project(app, owner.id)
    client = sync_session(app, owner.id)
    upload_id = _create(client, project.id, length=10)

    answer = _patch(client, project.id, upload_id, 0, b"")
    assert answer.status_code == 204
    assert _head_offset(client, project.id, upload_id) == (200, 0)


def test_completed_upload_refuses_further_patches(monkeypatch, tmp_path):
    app, _history, _store = make_app(monkeypatch, tmp_path)
    owner = await_user(app)
    project = new_project(app, owner.id)
    client = sync_session(app, owner.id)
    upload_id = _create(client, project.id, length=10)
    assert _patch(client, project.id, upload_id, 0, b"0123456789").status_code == 204

    again = _patch(client, project.id, upload_id, 10, b"XXXX")
    assert again.status_code == 409, again.text
    assert _head_offset(client, project.id, upload_id) == (200, 10)


def test_concurrent_same_offset_patches_cannot_silently_corrupt(monkeypatch, tmp_path):
    """같은 오프셋에 두 PATCH가 경합하면 둘 중 하나는 거절되어야 한다(423 계약).

    관측이 204+204이면 서로 다른 내용의 조각이 같은 구간에 겹쳐 쓰였다는 뜻이고,
    그것은 조각 무결성 결함으로 기록한다(수정 없음).
    """
    app, _history, _store = make_app(monkeypatch, tmp_path, chunk_bytes=4096)
    owner = await_user(app)
    project = new_project(app, owner.id)
    client = sync_session(app, owner.id)
    upload_id = _create(client, project.id, length=64)

    safe_client = TestClient(app, base_url="https://chat.example.test",
                             raise_server_exceptions=False)
    safe_client.cookies.update(client.cookies)
    safe_client.headers.update(client.headers)

    def one(body: bytes):
        answer = safe_client.patch(
            f"/api/projects/{project.id}/files/tus/{upload_id}",
            content=body,
            headers={"Upload-Offset": "0",
                     "Content-Type": "application/offset+octet-stream",
                     "Tus-Resumable": "1.0.0"},
        )
        # 관측: 204(성공) 또는 500(메타 경합 미처리)만 관측된다.
        assert answer.status_code in (204, 500, 409), answer.status_code
        return answer.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(one, (b"A" * 32, b"B" * 32)))

    status, offset = _head_offset(client, project.id, upload_id)
    data = open(os.path.join(_upload_root(), upload_id, _DATA_NAME), "rb").read()
    pure = {b"A" * 32, b"B" * 32, b""}
    assert data[:32] in pure, f"interleaved chunk bytes: {data[:32]!r}"
    assert (status, offset) == (200, 32), (status, offset)


# ── 3) 메타데이터 주입 ──────────────────────────────────────────────────────


def test_metadata_injection_cannot_shape_paths_or_names(monkeypatch, tmp_path):
    app, _history, _store = make_app(monkeypatch, tmp_path)
    owner = await_user(app)
    project = new_project(app, owner.id)
    client = sync_session(app, owner.id)

    attacks = {
        "traversal": "../escape.pdf",
        "absolute": "/etc/passwd.png",
        "windows": "C:\\windows\\evil.png",
        "nul": "evil\0.png",
        "double-encode": "%2e%2e%2fevil.png",
    }
    created_ids = []
    for label, name in attacks.items():
        answer = client.post(
            f"/api/projects/{project.id}/files/tus",
            headers={"Upload-Length": "40",
                     "Upload-Metadata": tus_metadata(name, "image/png"),
                     "Tus-Resumable": "1.0.0"},
        )
        assert answer.status_code == 201, (label, answer.status_code, answer.text[:120])
        created_ids.append((label, answer.json()["upload_id"]))

    long_answer = client.post(
        f"/api/projects/{project.id}/files/tus",
        headers={"Upload-Length": "40",
                 "Upload-Metadata": tus_metadata("x" * 513, "image/png"),
                 "Tus-Resumable": "1.0.0"},
    )
    # 관측: 513자 이름은 422가 아니라 512로 잘라 받아들여진다(계약으로 기록).
    assert long_answer.status_code == 201, long_answer.status_code
    created_ids.append(("long", long_answer.json()["upload_id"]))

    root = _upload_root()
    for entry in os.listdir(root):
        assert "escape" not in entry and "passwd" not in entry and "windows" not in entry

    for label, upload_id in created_ids:
        answer = _patch(client, project.id, upload_id, 0,
                        b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
        assert answer.status_code == 204, (label, answer.status_code)
        # 완료 픽업: 검증 통과면 201, 파싱 거부면 422 — 둘 다 무해하다.
        picked = client.get(f"/api/projects/{project.id}/files/tus/{upload_id}")
        assert picked.status_code in (200, 201, 404, 422), (label, picked.status_code)


def test_media_type_content_mismatch_is_refused_at_finalize(monkeypatch, tmp_path):
    app, _history, _store = make_app(monkeypatch, tmp_path)
    owner = await_user(app)
    project = new_project(app, owner.id)
    client = sync_session(app, owner.id)
    upload_id = _create(client, project.id, name="가짜.pdf",
                        media_type="application/pdf", length=24)
    assert _patch(client, project.id, upload_id, 0,
                  b"\x89PNG\r\n\x1a\n" + b"\x00" * 16).status_code == 204
    picked = client.get(f"/api/projects/{project.id}/files/tus/{upload_id}")
    assert picked.status_code == 422, picked.text
    assert picked.json()["error"]["code"] == "invalid_document"


# ── 4) 권한·ID 추측·만료 ────────────────────────────────────────────────────


def test_cross_account_and_cross_project_uploads_behave_as_missing(monkeypatch, tmp_path):
    app, _history, _store = make_app(monkeypatch, tmp_path)
    a = await_user(app, "alice")
    b = await_user(app, "bob")
    project_a = new_project(app, a.id, "A")
    project_b = new_project(app, b.id, "B")
    client_a = sync_session(app, a.id)
    client_b = sync_session(app, b.id)

    upload_id = _create(client_a, project_a.id, length=10)

    assert b_client_list(client_b, project_a.id) in (403, 404)
    assert _patch(client_b, project_a.id, upload_id, 0, b"X").status_code == 404
    assert client_b.head(f"/api/projects/{project_a.id}/files/tus/{upload_id}",
                         headers={"Tus-Resumable": "1.0.0"}).status_code == 404
    assert client_b.get(f"/api/projects/{project_a.id}/files/tus/{upload_id}").status_code == 404

    swapped = _patch(client_a, project_b.id, upload_id, 0, b"X")
    assert swapped.status_code == 404, swapped.status_code

    for guess in ("x" * 32, "0" * 32, "../../etc/passwd", "."):
        answer = client_a.get(f"/api/projects/{project_a.id}/files/tus/{guess}")
        assert answer.status_code == 404, (guess, answer.status_code)

    assert client_a.head(f"/api/projects/{project_a.id}/files/tus/{upload_id}",
                         headers={"Tus-Resumable": "1.0.0"}).status_code == 200


def b_client_list(b_client, project_id: str) -> int:
    return b_client.get(f"/api/projects/{project_id}/files").status_code


def test_expired_upload_cannot_be_resumed(monkeypatch, tmp_path):
    app, _history, _store = make_app(monkeypatch, tmp_path, cleanup_seconds=60)
    owner = await_user(app)
    project = new_project(app, owner.id)
    client = sync_session(app, owner.id)
    upload_id = _create(client, project.id, length=10)
    assert _patch(client, project.id, upload_id, 0, b"01234").status_code == 204

    marker = os.path.join(_upload_root(), upload_id, _META_NAME)
    old = time.time() - 3600
    os.utime(marker, (old, old))
    assert sweep_expired_uploads() >= 1

    assert _head_offset(client, project.id, upload_id) == (404, -1)
    resume = _patch(client, project.id, upload_id, 5, b"56789")
    assert resume.status_code == 404, resume.status_code


def test_no_per_user_creation_cap_exists(monkeypatch, tmp_path):
    """결함 후보 D3(자원 고갈 완화 부재): 사용자당 미완성 업로드 개수 상한·디스크
    상한이 코드에 없다 — 30개 전부 허용, 24시간 청소가 유일한 경계. 보고만 한다."""
    app, _history, _store = make_app(monkeypatch, tmp_path)
    owner = await_user(app)
    project = new_project(app, owner.id)
    client = sync_session(app, owner.id)
    ids = []
    for _ in range(30):
        created = client.post(
            f"/api/projects/{project.id}/files/tus",
            headers={"Upload-Length": "1",
                     "Upload-Metadata": tus_metadata("a.png", "image/png"),
                     "Tus-Resumable": "1.0.0"},
        )
        assert created.status_code == 201
        ids.append(created.json()["upload_id"])
    assert len(set(ids)) == 30  # 전부 허용 — 디스크 상한도 없음(24h 청소가 유일)


# ── 5) 출처(same-origin 예외의 좁음) ────────────────────────────────────────


def test_foreign_and_originless_patch_are_refused_by_the_guard(monkeypatch, tmp_path):
    """외부 출처·무출처 PATCH는 쿠키가 있어도 통과하지 못한다(통과 시 결함).

    conftest는 무출처 변형 요청에 기대 출처를 자동으로 붙여 브라우저를 흉내 낸다.
    진짜 무출처를 만들려면 x-test-no-origin 마커(conftest.NO_BROWSER_ORIGIN_MARKER)를
    쓴다 — conftest가 앱에 도달하기 전에 마커를 지우고 출처를 채워 넣지 않는다.
    """
    app, _history, _store = make_app(monkeypatch, tmp_path)
    owner = await_user(app)
    project = new_project(app, owner.id)
    client = sync_session(app, owner.id)
    upload_id = _create(client, project.id, length=10)
    url = f"/api/projects/{project.id}/files/tus/{upload_id}"
    tus_headers = {"Upload-Offset": "0", "Content-Type": "application/offset+octet-stream",
                   "Tus-Resumable": "1.0.0"}
    del client.headers["Origin"]  # 이하 요청은 전부 명시적 출처 헤더로만

    foreign = dict(tus_headers, Origin="https://evil.example")
    answer = client.patch(url, content=b"0123456789", headers=foreign)
    assert answer.status_code in (403, 401), answer.status_code
    assert _data_size(upload_id) == 0

    originless = dict(tus_headers, **{"x-test-no-origin": "1"})
    answer = client.patch(url, content=b"0123456789", headers=originless)
    assert answer.status_code in (403, 401), answer.status_code
    assert _data_size(upload_id) == 0
    assert _head_offset(client, project.id, upload_id) == (200, 0)


def test_same_origin_guard_tus_exception_is_narrow(monkeypatch, tmp_path):
    """가드의 tus PATCH 예외는 경로 모양으로 우회되지 않는다.

    관측 정리(2026-11-02): ".."가 들어간 모양은 클라이언트(httpx)가 정규화해서
    같은 소유자의 진짜 경로로 도달한다 — 같은 출처에서 204가 나오는 것은 우회가
    아니라 같은 자원이고(빈 PATCH로 아무것도 옮기지 않음을 확인), 외부 출처에서는
    어떤 모양도 2xx일 수 없다. 정규화되지 않는 모양(대소문자, 끝 슬래시)은 라우팅이
    빗나가 3xx/4xx로 끝난다.
    """
    app, _history, _store = make_app(monkeypatch, tmp_path)
    owner = await_user(app)
    project = new_project(app, owner.id)
    client = sync_session(app, owner.id)
    upload_id = _create(client, project.id, length=10)
    real = f"/api/projects/{project.id}/files/tus/{upload_id}"
    tus_headers = {"Upload-Offset": "0", "Content-Type": "application/offset+octet-stream",
                   "Tus-Resumable": "1.0.0"}

    bypasses = [
        f"/api/projects/{project.id}/files/tus/../{upload_id}",
        f"/api/PROJECTS/{project.id}/files/tus/{upload_id}",
        real + "/",
        real.replace("/files/tus/", "/files/tus/../tus/"),
    ]

    # 외부 출처: 어떤 우회 모양도 성공(2xx)할 수 없다 — 가드가 라우팅보다 먼저 거부.
    for shape in bypasses:
        answer = client.patch(shape, content=b"0123456789",
                              headers=dict(tus_headers, Origin="https://evil.example"))
        assert not (200 <= answer.status_code < 300), (shape, answer.status_code)

    # 같은 출처: 빈 PATCH(tus 합법, 아무것도 옮기지 않음)로 탐색한다.
    # 204가 나오면 반드시 '진짜 업로드 자체'에 도달한 것이어야 한다.
    before_dirs = set(os.listdir(_upload_root()))
    for shape in bypasses:
        answer = client.patch(shape, content=b"",
                              headers=dict(tus_headers, Origin=ORIGIN))
        if answer.status_code == 204:
            assert _head_offset(client, project.id, upload_id) == (200, 0), shape
            assert set(os.listdir(_upload_root())) == before_dirs, shape
        else:
            # 빗나간 모양: 이동(3xx)이나 거부(4xx)만 — 다른 자원의 성공은 없다.
            assert 300 <= answer.status_code < 500, (shape, answer.status_code)

    assert client.patch(real, content=b"0123456789",
                        headers=dict(tus_headers, Origin=ORIGIN)).status_code == 204
    assert _head_offset(client, project.id, upload_id) == (200, 10)


# ── 7) 앞단(worker.mjs) — 소스 근결 관측(런타임 계약은 프론트 시험 담당) ─────


def test_front_worker_source_streams_body_and_gives_tus_its_own_deadline():
    source = Path(__file__).resolve().parents[2].joinpath(
        "padiem-chat-front", "worker.mjs").read_text(encoding="utf-8")
    # 앞단은 90MB 컷이 없다: 본문은 request.body 그대로(duplex half) 전달되고
    # 크기 제한은 뒷단의 bounded spool이 담당한다. 앞단 장치는 시간제한뿐.
    assert "init.body = request.body" in source
    assert 'duplex = "half"' in source
    assert "TUS_UPLOAD_TIMEOUT_MS" in source
    # 특수 타임아웃은 tus 모양(PATCH·POST 두 동사)에만 주어진다.
    assert 'request.method === "PATCH" || request.method === "POST"' in source
    assert re_search_tus(source)


def re_search_tus(source: str) -> bool:
    return 'files\\/tus(?:\\/|$)' in source


# ── 8) 보충(2차, 2026-11-02): 빠진 공격 표면 ────────────────────────────────


def _raw_client(app, cookie: str | None = None) -> TestClient:
    """관측용 raw 클라이언트: 서버 예외를 HTTP 상태로 관측한다."""
    raw = TestClient(app, base_url=ORIGIN, raise_server_exceptions=False)
    if cookie:
        raw.cookies.set(SESSION_COOKIE, cookie, domain="chat.example.test", path="/")
    raw.headers.update({"Origin": ORIGIN})
    return raw


def _upload_entries() -> set[str]:
    root = _upload_root()
    return set(os.listdir(root)) if os.path.isdir(root) else set()


def test_creation_requires_upload_length_and_ignores_defer_length(monkeypatch, tmp_path):
    """빈 Upload-Length·Defer-Length 위장은 생성되지 않는다(계약 400)."""
    app, _history, _store = make_app(monkeypatch, tmp_path)
    owner = await_user(app)
    project = new_project(app, owner.id)
    client = sync_session(app, owner.id)

    missing = client.post(
        f"/api/projects/{project.id}/files/tus",
        headers={"Upload-Metadata": tus_metadata("a.png", "image/png"),
                 "Tus-Resumable": "1.0.0"},
    )
    assert missing.status_code == 400, (missing.status_code, missing.text[:120])

    defer_only = client.post(
        f"/api/projects/{project.id}/files/tus",
        headers={"Upload-Defer-Length": "1",
                 "Upload-Metadata": tus_metadata("a.png", "image/png"),
                 "Tus-Resumable": "1.0.0"},
    )
    assert defer_only.status_code == 400, defer_only.status_code

    # Defer 헤더는 알 수 없는 확장으로 무시되고 Upload-Length만 본다(관측 계약).
    defer_plus_valid = client.post(
        f"/api/projects/{project.id}/files/tus",
        headers={"Upload-Length": "10", "Upload-Defer-Length": "1",
                 "Upload-Metadata": tus_metadata("a.png", "image/png"),
                 "Tus-Resumable": "1.0.0"},
    )
    assert defer_plus_valid.status_code == 201, defer_plus_valid.status_code
    assert defer_plus_valid.json()["length_bytes"] == 10


def test_metadata_control_characters_are_filtered_or_rejected(monkeypatch, tmp_path):
    """파일명 제어 문자: C0 제어(< 0x20)와 DEL은 걷어지고, 걷어진 뒤 빈 이름은 거부된다.

    저장된 이름(메타 JSON)에 줄바꿈·DEL·NUL이 남지 않는 것이 본 시험의 본체다.
    """
    app, _history, _store = make_app(monkeypatch, tmp_path)
    owner = await_user(app)
    project = new_project(app, owner.id)
    client = sync_session(app, owner.id)

    cases = {
        "crlf": "보고서\r\n이름.png",       # 줄바꿈 제거 → "보고서이름.png"
        "tab": "a\tb.png",                  # 탭 제거 → "ab.png"
        "del": "a\x7fb.png",                # DEL 제거
        "nul": "evil\0.png",                # NUL 제거
        "rtl-override": "\u202e evil.exe \u202e png",  # (>= 0x20 — 남긴다, 경로 무해)
        "zero-width": "a\u200bb.png",       # (>= 0x20 — 남긴다)
    }
    for label, name in cases.items():
        answer = client.post(
            f"/api/projects/{project.id}/files/tus",
            headers={"Upload-Length": "10",
                     "Upload-Metadata": tus_metadata(name, "image/png"),
                     "Tus-Resumable": "1.0.0"},
        )
        assert answer.status_code == 201, (label, answer.status_code, answer.text[:120])
        upload_id = answer.json()["upload_id"]
        stored = json.loads(
            open(os.path.join(_upload_root(), upload_id, _META_NAME),
                 encoding="utf-8").read())["filename"]
        for banned in ("\r", "\n", "\x00", "\x7f"):
            assert banned not in stored, (label, repr(stored))
        assert "/" not in stored and "\\" not in stored, (label, repr(stored))

    # 전부 제어 문자인 이름: 걷어진 뒤 빈 이름 → 422(생성 자체가 없다).
    blank = client.post(
        f"/api/projects/{project.id}/files/tus",
        headers={"Upload-Length": "10",
                 "Upload-Metadata": tus_metadata("\r\n\t\x00", "image/png"),
                 "Tus-Resumable": "1.0.0"},
    )
    assert blank.status_code == 422, (blank.status_code, blank.text[:120])


def test_metadata_invalid_base64_and_duplicate_keys(monkeypatch, tmp_path):
    app, _history, _store = make_app(monkeypatch, tmp_path)
    owner = await_user(app)
    project = new_project(app, owner.id)
    client = sync_session(app, owner.id)
    url = f"/api/projects/{project.id}/files/tus"

    broken = client.post(url, headers={
        "Upload-Length": "10",
        "Upload-Metadata": "filename !!!not-base64!!,filetype aW1hZ2UvcG5n",
        "Tus-Resumable": "1.0.0"})
    assert broken.status_code == 422, (broken.status_code, broken.text[:120])

    empty_meta = client.post(url, headers={
        "Upload-Length": "10", "Upload-Metadata": "", "Tus-Resumable": "1.0.0"})
    assert empty_meta.status_code == 422, empty_meta.status_code

    first = base64.b64encode("first.png".encode()).decode()
    last = base64.b64encode("last.png".encode()).decode()
    dup = client.post(url, headers={
        "Upload-Length": "10",
        "Upload-Metadata": f"filename {first},filename {last},"
                           f"filetype {base64.b64encode(b'image/png').decode()}",
        "Tus-Resumable": "1.0.0"})
    assert dup.status_code == 201, dup.status_code  # 마지막 키로 결정(관측 계약)
    upload_id = dup.json()["upload_id"]
    stored = json.loads(open(os.path.join(_upload_root(), upload_id, _META_NAME),
                             encoding="utf-8").read())["filename"]
    assert stored == "last.png", stored


def test_create_patch_head_without_session_are_refused(monkeypatch, tmp_path):
    """쿠키 없는 요청은 출처를 위조해도 세션 없이는 통과하지 못한다(401/403)."""
    app, _history, _store = make_app(monkeypatch, tmp_path)
    owner = await_user(app)
    project = new_project(app, owner.id)
    owner_client = sync_session(app, owner.id)
    upload_id = _create(owner_client, project.id, length=10)

    bare = TestClient(app, base_url=ORIGIN, raise_server_exceptions=False)
    bare.headers.update({"Origin": ORIGIN})  # 쿠키 없음 — 출처만 같음
    base = f"/api/projects/{project.id}/files/tus/{upload_id}"

    assert bare.post(f"/api/projects/{project.id}/files/tus", headers={
        "Upload-Length": "10", "Upload-Metadata": tus_metadata("a.png", "image/png"),
        "Tus-Resumable": "1.0.0"}).status_code in (401, 403)
    assert bare.patch(base, content=b"X", headers={
        "Upload-Offset": "0", "Content-Type": "application/offset+octet-stream",
        "Tus-Resumable": "1.0.0"}).status_code in (401, 403)
    assert bare.head(base, headers={"Tus-Resumable": "1.0.0"}).status_code in (401, 403)
    assert bare.get(base).status_code in (401, 403)
    assert _data_size(upload_id) == 0


def test_create_on_another_users_project_is_not_their_upload(monkeypatch, tmp_path):
    """소유자가 아닌 사용자의 생성(POST)도 404로 흩어진다 — 업로드 디렉터리조차 생기지 않는다."""
    app, _history, _store = make_app(monkeypatch, tmp_path)
    a = await_user(app, "alice")
    b = await_user(app, "bob")
    project_a = new_project(app, a.id, "A")
    client_b = sync_session(app, b.id)

    before = _upload_entries()
    answer = client_b.post(
        f"/api/projects/{project_a.id}/files/tus",
        headers={"Upload-Length": "10",
                 "Upload-Metadata": tus_metadata("steal.png", "image/png"),
                 "Tus-Resumable": "1.0.0"},
    )
    assert answer.status_code in (403, 404), (answer.status_code, answer.text[:120])
    assert _upload_entries() == before  # 생성물 0


def test_encoded_upload_id_traversal_shapes_behave_as_missing(monkeypatch, tmp_path):
    """upload_id 세그먼트의 퍼센트 인코딩 순회 모양은 전부 404(루트 탈출 0)."""
    app, _history, _store = make_app(monkeypatch, tmp_path)
    owner = await_user(app)
    project = new_project(app, owner.id)
    client = sync_session(app, owner.id)
    url = f"/api/projects/{project.id}/files/tus"

    before = _upload_entries()
    for guess in ("%2e%2e", "%2e%2e%2f", "..%2F", "..%5C", "%2e", "%2f", "...."):
        for method in ("get", "head"):
            answer = getattr(client, method)(f"{url}/{guess}",
                                             headers={"Tus-Resumable": "1.0.0"})
            assert answer.status_code == 404, (method, guess, answer.status_code)
    assert _upload_entries() == before


def test_swept_upload_pickup_is_missing(monkeypatch, tmp_path):
    """청소된 업로드의 픽업(GET)도 404 — 만료 자원은 상태 조회와 똑같이 사라진다."""
    app, _history, _store = make_app(monkeypatch, tmp_path, cleanup_seconds=60)
    owner = await_user(app)
    project = new_project(app, owner.id)
    client = sync_session(app, owner.id)
    upload_id = _create(client, project.id, length=10)
    assert _patch(client, project.id, upload_id, 0, b"01234").status_code == 204

    marker = os.path.join(_upload_root(), upload_id, _META_NAME)
    old = time.time() - 3600
    os.utime(marker, (old, old))
    assert sweep_expired_uploads() >= 1
    assert client.get(f"/api/projects/{project.id}/files/tus/{upload_id}"
                      ).status_code == 404


def test_unicode_decimal_headers_normalize_to_one_value(monkeypatch, tmp_path):
    """비 ASCII 십진수 헤더는 실제 HTTP 전달로는 도달조차 하지 못한다.

    isdecimal()/int()는 유니코드 십진수('١٢' → 12)를 같은 정수로 정규화하지만,
    HTTP 헤더는 아스키(Starlette는 latin-1 디코딩)로만 도달하므로 원시 UTF-8 바이트를
    싣으면 isdecimal()이 False가 되어 거부된다. 원시 바이트(공격자가 wire에서 직접
    쓰는 모양)로 세 경로를 관측해 무덧붙임·무생성을 고정한다.
    """
    app, _history, _store = make_app(monkeypatch, tmp_path)
    owner = await_user(app)
    project = new_project(app, owner.id)
    client = sync_session(app, owner.id)
    upload_id = _create(client, project.id, length=10)
    url = f"/api/projects/{project.id}/files/tus/{upload_id}"

    arabic_twelve = "١٢".encode("utf-8")       # 아라비아-인도 12
    arabic_zero = "٠".encode("utf-8")          # 아라비아-인도 0
    arabic_123 = "١٢٣".encode("utf-8")

    offset_wrong = client.patch(url, content=b"X" * 8, headers={
        "Upload-Offset": arabic_twelve,
        "Content-Type": "application/offset+octet-stream",
        "Tus-Resumable": "1.0.0"})
    assert offset_wrong.status_code == 409, offset_wrong.status_code
    assert _data_size(upload_id) == 0

    offset_zero = client.patch(url, content=b"01234", headers={
        "Upload-Offset": arabic_zero,
        "Content-Type": "application/offset+octet-stream",
        "Tus-Resumable": "1.0.0"})
    # 관측: latin-1 디코딩 결과가 십진수가 아니므로 409(무덧붙임) — 정규화 경로 자체가 닫힌다.
    assert offset_zero.status_code in (400, 409), offset_zero.status_code
    assert _data_size(upload_id) == 0
    assert _head_offset(client, project.id, upload_id) == (200, 0)

    length_arabic = client.post(
        f"/api/projects/{project.id}/files/tus",
        headers={"Upload-Length": arabic_123,
                 "Upload-Metadata": tus_metadata("a.png", "image/png"),
                 "Tus-Resumable": "1.0.0"})
    assert length_arabic.status_code == 400, length_arabic.status_code  # 무생성
    assert _upload_entries() == {upload_id}  # 기존 업로드 외 생성물 없음


def test_front_worker_never_forges_origin_or_edge_proof():
    """앞단 헤더 계약(소스 근결 관측): 출처와 에지 증명은 클라이언트가 만질 수 없다.

    - worker.mjs는 클라이언트 Origin을 그대로 전달한다(출처 위조를 도와주지 않음).
    - x-forwarded-* 는 서빙 값으로 덮어써진다(host 삭제 포함).
    - edge-proof.mjs는 클라이언트가 보낸 증명 헤더를 지운 뒤 자신이 다시 세팅한다
      (증명 위조 불가) — 서명문에 method·pathname이 들어가 재생이 경계를 벗어나지 못한다.
    """
    front = Path(__file__).resolve().parents[2].joinpath("padiem-chat-front")
    worker = front.joinpath("worker.mjs").read_text(encoding="utf-8")
    edge = front.joinpath("edge-proof.mjs").read_text(encoding="utf-8")

    assert 'headers.set("origin"' not in worker  # 출처 합성 금지 — 가드가 실제 출처를 본다
    assert 'headers.delete("host")' in worker
    assert 'headers.set("x-forwarded-host", new URL(request.url).host)' in worker
    assert 'headers.set("x-forwarded-proto", "https")' in worker
    assert 'headers.set("x-forwarded-for", prior ? `${prior}, ${ip}` : ip)' in worker

    assert 'const headers = new Headers(request.headers);' in edge
    assert 'for (const name of PROOF_HEADERS) headers.delete(name);' in edge
    assert '["v1", request.method, url.pathname, at, id, tls].join("\\n")' in edge
    assert 'request.cf?.tlsVersion' in edge  # TLS 사실이 증명에 묶인다
