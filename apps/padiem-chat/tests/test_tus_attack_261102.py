"""tus 공격 시험 — tus_core 기준 이관본(#6579 시험 브랜치 test/tus-hardening-261101
47322e584에서 이관, 2026-11-02).

원칙은 그대로: 결함은 고치지 말고 관측·기록만 한다(이 파일은 시험만 담는다). 다만
이 브랜치는 #6602가 D1·D2·D3를 고친 tus_core 위에 서 있으므로:

- D1·D2 xfail은 제거했다(이제 정상 계약이므로 정상 단언) — 해당 장면의 1차 관측은
  tests/test_tus_hardening_d1_d3_261102.py 가 소유한다.
- #6602와 겹치는 장면(길이 조작 8종, 오프셋 -1·건너뛰기·5,000자리, 선언 초과 조각,
  거짓 Content-Length, 계정별 상한)은 이 파일에서 뺐다 — 중복 금지.
- D4(같은 오프셋 동시 PATCH)는 이 파일의 정상 단언으로 승격했다: 204+409(upload_busy),
  500 없음, 조각 바이트 순수, 메타 .tmp 잔여물 없음.
- D3가 생겼으므로 한 계정이 미완성 업로드를 많이 만드는 장면은 개별적으로 상한을
  올려 둔다(상한 자체의 시험은 #6602 소유).

남는 건 모두 #6602가 다루지 않는 공격 표면이다: 생성 계약(Defer 위장), 메타데이터
제어 문자·무효 base64·중복 키·경로 주입, 무세션 요청, 타인 프로젝트 생성, 인코딩된
upload_id 순회, 만료 픽업, 원시 바이트 비 ASCII 헤더, same-origin 예외의 좁음,
앞단(worker.mjs·edge-proof.mjs) 헤더 계약.
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
from app.tus_core import (
    _DATA_NAME,
    _META_NAME,
    sweep_expired_uploads,
    upload_root as _upload_root,
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


# ── 1) 생성 계약: Defer-Length 위장 ─────────────────────────────────────────


def test_creation_ignores_defer_length_but_never_accepts_it_as_length(monkeypatch, tmp_path):
    """Upload-Defer-Length는 알 수 없는 확장으로 무시되고(관측 계약), 이것만으로는
    생성이 일어나지 않는다(400) — 길이를 나중에 정하는 통로는 없다."""
    app, _history, _store = make_app(monkeypatch, tmp_path)
    owner = await_user(app)
    project = new_project(app, owner.id)
    client = sync_session(app, owner.id)

    defer_only = client.post(
        f"/api/projects/{project.id}/files/tus",
        headers={"Upload-Defer-Length": "1",
                 "Upload-Metadata": tus_metadata("a.png", "image/png"),
                 "Tus-Resumable": "1.0.0"},
    )
    assert defer_only.status_code == 400, defer_only.status_code

    defer_plus_valid = client.post(
        f"/api/projects/{project.id}/files/tus",
        headers={"Upload-Length": "10", "Upload-Defer-Length": "1",
                 "Upload-Metadata": tus_metadata("a.png", "image/png"),
                 "Tus-Resumable": "1.0.0"},
    )
    assert defer_plus_valid.status_code == 201, defer_plus_valid.status_code
    assert defer_plus_valid.json()["length_bytes"] == 10


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


# ── 2) 메타데이터 주입: 제어 문자·경로·base64 ───────────────────────────────


def test_metadata_injection_cannot_shape_paths_or_names(monkeypatch, tmp_path):
    """경로 주입·제어 문자가 저장 이름이나 디스크 배치를 결정하지 못한다.

    D3로 계정별 상한이 생겼으므로 이 장면만 상한을 올린다(상한 시험은 #6602 소유).
    """
    monkeypatch.setenv("PADIEM_TUS_MAX_ACTIVE_UPLOADS_PER_USER", "50")
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
        "crlf": "보고서\r\n이름.png",
        "tab": "a\tb.png",
        "del": "a\x7fb.png",
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

    # 저장된 이름에는 제어 문자가 남지 않는다. 경로 모양의 이름은 관측 계약대로
    # 그대로 저장될 수 있지만(디스크 배치는 upload_id 디렉터리가 결정한다), 어느
    # 이름도 업로드 루트 밖으로 나가지 않는 것은 아래 listing 단언이 증명한다.
    for label, upload_id in created_ids:
        stored = json.loads(
            open(os.path.join(_upload_root(), upload_id, _META_NAME),
                 encoding="utf-8").read())["filename"]
        for banned in ("\r", "\n", "\x00", "\x7f"):
            assert banned not in stored, (label, repr(stored))

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


def test_metadata_of_only_control_characters_is_rejected(monkeypatch, tmp_path):
    """걷어진 뒤 빈 이름은 생성 자체가 없다(422) — 빈 파일명 업로드는 없다."""
    app, _history, _store = make_app(monkeypatch, tmp_path)
    owner = await_user(app)
    project = new_project(app, owner.id)
    client = sync_session(app, owner.id)

    blank = client.post(
        f"/api/projects/{project.id}/files/tus",
        headers={"Upload-Length": "10",
                 "Upload-Metadata": tus_metadata("\r\n\t\x00", "image/png"),
                 "Tus-Resumable": "1.0.0"},
    )
    assert blank.status_code == 422, (blank.status_code, blank.text[:120])
    assert _upload_entries() == set()


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


# ── 3) 조각 경계 ────────────────────────────────────────────────────────────


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
    """D4 정상 단언: 같은 오프셋에 두 PATCH가 경합하면 하나만 진행한다.

    이전 관측(47322e584)은 204+500(메타 tmp 충돌 미처리)이었다. 수정 후 계약:
    한쪽 204, 다른 쪽 409(upload_busy — 이미 끝난 뒤 도착이면 offset/completed 사유),
    500은 없고, 조각 바이트는 순수하며, 메타 .tmp 잔여물도 없다.
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
        code = ""
        try:
            code = (answer.json().get("error") or {}).get("code", "")
        except Exception:
            pass
        return answer.status_code, code

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(one, (b"A" * 32, b"B" * 32)))

    statuses = {first[0], second[0]}
    assert statuses == {204, 409}, (first, second)  # 500 금지, 이중 성공 금지
    for status, code in (first, second):
        if status == 409:
            assert code in ("upload_busy", "offset_mismatch", "upload_completed"), code

    status, offset = _head_offset(client, project.id, upload_id)
    data = open(os.path.join(_upload_root(), upload_id, _DATA_NAME), "rb").read()
    pure = {b"A" * 32, b"B" * 32, b""}
    assert data[:32] in pure, f"interleaved chunk bytes: {data[:32]!r}"
    assert (status, offset) == (200, 32), (status, offset)
    # 메타 쓰기 잔여물: 고유 tmp 이름은 항상 치환되거나 치워진다.
    assert not list(Path(_upload_root(), upload_id).glob("*.tmp"))


def test_a_within_limit_huge_offset_still_mismatches(monkeypatch, tmp_path):
    """20자리(파서 한계 이내, 파이썬 int()로도 안전한) 초대형 오프셋도 그대로 409다."""
    app, _history, _store = make_app(monkeypatch, tmp_path)
    owner = await_user(app)
    project = new_project(app, owner.id)
    client = sync_session(app, owner.id)
    upload_id = _create(client, project.id, length=64)

    answer = client.patch(
        f"/api/projects/{project.id}/files/tus/{upload_id}",
        content=b"X" * 8,
        headers={"Upload-Offset": "9" * 20,
                 "Content-Type": "application/offset+octet-stream",
                 "Tus-Resumable": "1.0.0"},
    )
    assert answer.status_code == 409, answer.status_code
    assert _data_size(upload_id) == 0
    assert _head_offset(client, project.id, upload_id) == (200, 0)


# ── 4) 권한·ID 추측·만료 ────────────────────────────────────────────────────


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


def test_cross_account_and_cross_project_uploads_behave_as_missing(monkeypatch, tmp_path):
    app, _history, _store = make_app(monkeypatch, tmp_path)
    a = await_user(app, "alice")
    b = await_user(app, "bob")
    project_a = new_project(app, a.id, "A")
    project_b = new_project(app, b.id, "B")
    client_a = sync_session(app, a.id)
    client_b = sync_session(app, b.id)

    upload_id = _create(client_a, project_a.id, length=10)

    assert client_b.get(f"/api/projects/{project_a.id}/files").status_code in (403, 404)
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


def test_expired_upload_cannot_be_resumed_or_picked_up(monkeypatch, tmp_path):
    """청소된 업로드는 이어올리기(PATCH)도 픽업(GET)도 없다 — 전부 404."""
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
    assert _patch(client, project.id, upload_id, 5, b"56789").status_code == 404
    assert client.get(f"/api/projects/{project.id}/files/tus/{upload_id}").status_code == 404


# ── 5) 원시 바이트 헤더 ─────────────────────────────────────────────────────


def test_non_ascii_decimal_headers_never_reach_the_integer_parser(monkeypatch, tmp_path):
    """비 ASCII 십진수 헤더는 HTTP 헤더가 latin-1로 디코딩되는 특성상 도달 불가다.

    isdecimal()/정수 파서는 유니코드 십진수를 같은 값으로 정규화할 수 있지만, 원시
    UTF-8 바이트를 싣으면 latin-1 문자가 되어 십진수가 아니므로 400으로 거부된다 —
    무덧붙임, 무생성.
    """
    app, _history, _store = make_app(monkeypatch, tmp_path)
    owner = await_user(app)
    project = new_project(app, owner.id)
    client = sync_session(app, owner.id)
    upload_id = _create(client, project.id, length=10)
    url = f"/api/projects/{project.id}/files/tus/{upload_id}"

    arabic_twelve = "١٢".encode("utf-8")   # 아라비아-인도 12
    arabic_zero = "٠".encode("utf-8")      # 아라비아-인도 0
    arabic_123 = "١٢٣".encode("utf-8")

    offset_wrong = client.patch(url, content=b"X" * 8, headers={
        "Upload-Offset": arabic_twelve,
        "Content-Type": "application/offset+octet-stream",
        "Tus-Resumable": "1.0.0"})
    assert offset_wrong.status_code in (400, 409), offset_wrong.status_code
    assert _data_size(upload_id) == 0

    offset_zero = client.patch(url, content=b"01234", headers={
        "Upload-Offset": arabic_zero,
        "Content-Type": "application/offset+octet-stream",
        "Tus-Resumable": "1.0.0"})
    assert offset_zero.status_code in (400, 409), offset_zero.status_code
    assert _data_size(upload_id) == 0
    assert _head_offset(client, project.id, upload_id) == (200, 0)

    length_arabic = client.post(
        f"/api/projects/{project.id}/files/tus",
        headers={"Upload-Length": arabic_123,
                 "Upload-Metadata": tus_metadata("a.png", "image/png"),
                 "Tus-Resumable": "1.0.0"})
    assert length_arabic.status_code == 400, length_arabic.status_code
    assert _upload_entries() == {upload_id}


# ── 6) 출처(same-origin 예외의 좁음) ────────────────────────────────────────


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

    ".."가 들어간 모양은 클라이언트(httpx)가 정규화해서 같은 소유자의 진짜 경로로
    도달한다 — 같은 출처에서 204가 나오는 것은 우회가 아니라 같은 자원이고(빈 PATCH로
    아무것도 옮기지 않음을 확인), 외부 출처에서는 어떤 모양도 2xx일 수 없다.
    정규화되지 않는 모양(대소문자, 끝 슬래시)은 라우팅이 빗나가 3xx/4xx로 끝난다.
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
    before_dirs = _upload_entries()
    for shape in bypasses:
        answer = client.patch(shape, content=b"",
                              headers=dict(tus_headers, Origin=ORIGIN))
        if answer.status_code == 204:
            assert _head_offset(client, project.id, upload_id) == (200, 0), shape
            assert _upload_entries() == before_dirs, shape
        else:
            assert 300 <= answer.status_code < 500, (shape, answer.status_code)

    assert client.patch(real, content=b"0123456789",
                        headers=dict(tus_headers, Origin=ORIGIN)).status_code == 204
    assert _head_offset(client, project.id, upload_id) == (200, 10)


# ── 7) 앞단(worker.mjs·edge-proof.mjs) 헤더 계약 — 소스 근결 관측 ───────────


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


def re_search_tus(source: str) -> bool:
    return 'files\\/tus(?:\\/|$)' in source
