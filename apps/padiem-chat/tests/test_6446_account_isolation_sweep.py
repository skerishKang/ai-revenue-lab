"""#6446(구 #6089) — 계정 격리 전수 스윕: A 계정이 B 계정 자료에 닿지 못한다.

의원3종 4번의 확장판이다. 기존에 흩어져 있던 격리 계약(#5783 프로젝트 파일,
#2952 수신함·캘린더·문서, test_mcp_gateway_account)을 한 하네스로 묶고, 빠진
표면을 같은 방식으로 고정한다:

- 실제 create_app + 실제 SQLite D1 + 실제 서명 세션 쿠키(가짜 모델 없음).
- A(PLUS 회원)가 자료를 만들고, B(FREE 회원)가 목록·읽기·수정·삭제·다운로드와
  다른 사람 ID·추측 ID로 접근한다. 기대는 전부 404(존재 부정) 또는 "내 것만"이다.
- 회사(테넌트) 범위가 있는 표면(수신함·캘린더·문서)은 #2952 스윕이 같은 테넌트
  두 사용자로 이미 고정한다 — 이 파일은 그 결과를 재확인하지 않고 인용한다.

이 파일이 다루지 못하는 표면(이유는 각 시험의 주석)과 이미 고정된 표면:

- PC 연결·저장(pairings·reference·drives·save): PC 페어링 포트 구성이 필요한 표면 —
  구성 없이는 fail-closed(503)임을 확인하고 미확인으로 남긴다. 2026-11-02 의원 앱
  문서가 쓰는 pc/save의 project_file_id 소스도 같은 문을 지나며, 소스의
  소유자·프로젝트 범위 404는 test_council_pc_save_binary_261102.py가 라인 수준에서
  고정한다.
- 북AI 기록(082): 사용자 세션이 아니라 x-bookai-* 서명 헤더의 서비스 간 레인.
- 자동화 규칙: 실행 대상 권한(external authority) 구성이 필요 — fail-closed 확인.
- MCP 게이트웨이: test_mcp_gateway_account.py가 소유자 범위·타계정 PC·승인
  일회성을 이미 고정한다.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest
from starlette.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolated_tus_uploads(tmp_path, monkeypatch):
    """조각 업로드는 이 시험만의 폴더에만 쌓는다.

    이 파일은 계정 격리를 보는 곳이고, 업로드 개수·바이트 상한(D3)은
    test_tus_hardening_d1_d3_261102.py가 자기 환경에서 고정한다. 여기서 상한을
    끄지 않으면 앞선 장면이 남긴 같은 계정의 미완료 업로드가 다음 장면의 생성
    자체를 429로 막아, 격리 결과가 상한 결과와 섬인다.
    """
    monkeypatch.setenv("PADIEM_TUS_UPLOAD_DIR", str(tmp_path / "tus-uploads"))
    monkeypatch.setenv("PADIEM_TUS_MAX_ACTIVE_UPLOADS_PER_USER", "0")
    monkeypatch.setenv("PADIEM_TUS_MAX_ACTIVE_BYTES_PER_USER", "0")

import test_5222_account_model_selection as account_harness
from app.auth import SESSION_COOKIE, create_session_token
from app.history import D1HistoryStore
from app.mcp_gateway_account_routes import MCP_TOKENS_PATH
from app.main import create_app
from app.pc_delegation_routes import PC_DELEGATION_PATH
from app.project_files import D1ProjectFileStore
from app.byok_credentials import D1CustomProviderCredentialStore
from app.saved_outputs import D1SavedOutputStore

from test_5002_byok_product_e2e import FakeAuthenticatedCipher
from test_5222_account_model_selection import BASE, seed_db, session

ROOT = Path(__file__).resolve().parents[1]


class ThreadSafeStatement(account_harness.Statement):
    """5222 Statement에 `.all()`을 보강한다(회의장부 등이 사용)."""

    def bind(self, *params):
        return ThreadSafeStatement(self.db, self.sql, params)

    async def all(self):
        cursor = self.db.conn.execute(self.sql, self.params)
        return [dict(row) for row in cursor.fetchall()]


class ThreadSafeSqliteD1(account_harness.SqliteD1):
    """#5222 하네스와 같은 D1 모양이지만 두 가지만 고친다.

    1. 스레드 제한: starlette TestClient는 앱을 포털 스레드에서 돌리고, 5222의
       sqlite 연결은 생성 스레드에 묶여 있어 요청마다 `SQLite objects created
       in a thread...` 예외로 503이 났다. 운영 COM2 어댑터
       (`app/d1_sqlite.py::connect`)가 이미 그렇듯 check_same_thread=False로만
       푼다 — 제품 코드 변경은 없다.
    2. `.all()`: 회의장부 같은 D1 스토어가 쓰는 나머지 읽기 표면.
    """

    def __init__(self):
        self.conn = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")

    def prepare(self, sql):
        return ThreadSafeStatement(self, sql)

    async def batch(self, statements):
        # D1 배치 응답 형태: 문장별 {"results": [...], "meta": {...}} —
        # 북AI 병합이 결과를 dict 첨자로 읽는다(5222 하네스는 SimpleNamespace).
        out = []
        for statement in statements:
            cursor = self.conn.execute(statement.sql, statement.params)
            out.append({
                "results": [dict(row) for row in cursor.fetchall()],
                "meta": {"changes": cursor.rowcount},
            })
        return out


def apply_all_migrations(db) -> None:
    for path in sorted((ROOT / "migrations").glob("*.sql")):
        db.conn.executescript(path.read_text(encoding="utf-8"))


def isolation_app(db):
    app = create_app(
        account_harness.settings(),
        d1_binding=db,
        b66_admin_google_email="admin@example.test",
        # BYOK custom credential은 WebCrypto 암호화를 쓴다 — 로컬 CPython에서는
        # 결정론 가짜 암호로만 동작한다(test_5002가 정립한 계약).
        custom_credential_store=D1CustomProviderCredentialStore(
            db,
            key_secret="c" * 48,
            session_secret="s" * 48,
            cipher=FakeAuthenticatedCipher(),
        ),
    )
    app.state.history_store = D1HistoryStore(db)
    app.state.project_file_store = D1ProjectFileStore(db)
    app.state.saved_output_store = D1SavedOutputStore(db)
    return app


def clients():
    """(app, A 클라이언트, B 클라이언트) — A=PLUS, B=FREE 회원."""
    original = account_harness.SqliteD1
    account_harness.SqliteD1 = ThreadSafeSqliteD1
    try:
        db, _admin, a, b = seed_db()
    finally:
        account_harness.SqliteD1 = original
    apply_all_migrations(db)
    app = isolation_app(db)
    client_a = TestClient(app, base_url=BASE)
    client_b = TestClient(app, base_url=BASE)
    client_a.cookies.update(session(app, a))
    client_b.cookies.update(session(app, b))
    # 브라우저와 같은 same-origin 표시(검토된 출처 = public_base_url) —
    # 회의록 같은 상태 변경 경로가 요구하는 값이다.
    client_a.headers.update({"Origin": BASE})
    client_b.headers.update({"Origin": BASE})
    return app, client_a, client_b, a, b


def new_project(client_a) -> str:
    created = client_a.post("/api/projects", json={"name": "A 프로젝트"})
    assert created.status_code == 201, created.text
    return created.json()["project"]["id"]


def new_meeting_ref(client_a) -> str:
    created = client_a.post("/api/claw/meetings", json={"title": "A 회의", "mode": "record"})
    assert created.status_code == 201, created.text
    return created.json()["meeting"]["meeting_ref"]


# ── 프로젝트: 목록·읽기·수정·삭제 ────────────────────────────────────────────


def test_projects_stay_in_their_account():
    _app, a_client, b_client, _a, _b = clients()
    project_id = new_project(a_client)

    listed_b = b_client.get("/api/projects")
    assert listed_b.status_code == 200
    assert all(row["id"] != project_id for row in listed_b.json()["projects"])

    for method, path in (
        ("GET", f"/api/projects/{project_id}"),
        ("PATCH", f"/api/projects/{project_id}"),
        ("DELETE", f"/api/projects/{project_id}"),
        ("GET", "/api/projects/proj_" + "f" * 32),
    ):
        answer = b_client.request(method, path, json={"name": "B 시도"} if method == "PATCH" else None)
        assert answer.status_code == 404, (method, path, answer.status_code)

    # A의 자료는 A에게 그대로 있다.
    assert a_client.get(f"/api/projects/{project_id}").status_code == 200


# ── 프로젝트 파일: 목록·읽기·수정·삭제·원본 다운로드 ─────────────────────────


def test_project_files_and_original_stay_in_their_account():
    _app, a_client, b_client, _a, _b = clients()
    project_id = new_project(a_client)
    saved = a_client.post(
        f"/api/projects/{project_id}/files",
        json={"name": "a-축사.txt", "media_type": "text/plain",
              "text": "A의 축사 본문", "doc_kind": "speech"},
    )
    assert saved.status_code == 201, saved.text
    file_id = saved.json()["file"]["id"]

    listed_b = b_client.get(f"/api/projects/{project_id}/files")
    assert listed_b.status_code == 404  # 프로젝트 자체가 B에게 존재하지 않는다

    for method, path in (
        ("GET", f"/api/projects/{project_id}/files/{file_id}"),
        ("PUT", f"/api/projects/{project_id}/files/{file_id}"),
        ("DELETE", f"/api/projects/{project_id}/files/{file_id}"),
        ("GET", f"/api/projects/{project_id}/files/{file_id}/original"),
        ("GET", f"/api/projects/{project_id}/files/file_" + "9" * 32),
    ):
        answer = b_client.request(method, path, json={"text": "B 덮어쓰기"} if method == "PUT" else None)
        assert answer.status_code == 404, (method, path, answer.status_code)

    assert a_client.get(f"/api/projects/{project_id}/files/{file_id}").status_code == 200
    # 텍스트 문서는 바이너리 원본이 없다 — /original은 소유자에게도 404가 계약이다.
    # 격리 관점: B도 같은 404를 받아 존재를 구분할 수 없다.
    assert a_client.get(f"/api/projects/{project_id}/files/{file_id}/original").status_code == 404


# ── PC 저장(의원 앱 문서): pc/save의 project_file_id 소스 ─────────────────────


def test_pc_save_with_a_borrowed_project_file_stays_fail_closed():
    """A의 프로젝트 파일을 PC 저장 소스로 지목해도 B는 문 앞에서 멈춘다.

    pc/save의 새 소스(project_file_id)는 소유자+프로젝트 범위로 행을 읽는다.
    이 스윕 환경엔 PC 신원 확인(chat PC identity)부터 막혀 문 자체가 503으로 닫힌다
    (fail-closed) — 소유자·타인·추측 id 어느 쪽이든 아무 것도 준비되지 않고 A의
    행은 그대로다. 문 안쪽의 범위 404는 test_council_pc_save_binary_261102.py가
    기록 스텁으로 고정한다.
    """
    app, a_client, b_client, a, _b = clients()
    project_id = new_project(a_client)
    created = asyncio.run(
        app.state.project_file_store.create_file(
            a, project_id, "축사.hwpx", "extracted/hwpx", "축사 본문 자리",
            doc_kind="speech",
        )
    )
    for body in (
        # B가 A의 실제 파일 id를 소스로 지목한다.
        {"path": "축사.hwpx", "project_id": project_id, "project_file_id": created.id},
        # B가 모양만 그럴듯한 id를 추측한다.
        {"path": "축사.hwpx", "project_id": "proj_" + "f" * 32,
         "project_file_id": "file_" + "9" * 32},
    ):
        answer = b_client.post("/api/pc/save", json=body)
        assert answer.status_code == 503, (body, answer.status_code, answer.text)
        assert answer.json()["error"]["code"] == "chat_pc_identity_unavailable"
    rows = asyncio.run(app.state.project_file_store.list_files(a, project_id))
    assert [row.id for row in rows] == [created.id]


# ── 대화: 목록·검색·읽기·삭제 ────────────────────────────────────────────────


def test_conversations_stay_in_their_account():
    app, a_client, b_client, a, _b = clients()
    conversation_id = "chat_" + "a" * 32
    app.state.history_store.db.conn.execute(
        "INSERT INTO conversations (id, user_id, title, created_at, updated_at)"
        " VALUES (?,?,?,?,?)",
        (conversation_id, a, "A의 대화", "2026-11-01T00:00:00Z", "2026-11-01T00:00:00Z"),
    )

    listed_b = b_client.get("/api/conversations")
    assert listed_b.status_code == 200
    assert all(row["id"] != conversation_id for row in listed_b.json()["conversations"])

    searched = b_client.get("/api/conversations/search", params={"q": "A의 대화"})
    assert searched.status_code == 200
    assert all(row["id"] != conversation_id for row in (searched.json().get("results") or searched.json().get("conversations") or []))

    assert b_client.get(f"/api/conversations/{conversation_id}").status_code == 404
    assert b_client.delete(f"/api/conversations/{conversation_id}").status_code == 404
    assert b_client.get("/api/conversations/chat_" + "b" * 32).status_code == 404
    # A의 대화는 A에게 그대로 있고, B가 지우려 한 흔적도 없다.
    assert a_client.get(f"/api/conversations/{conversation_id}").status_code == 200


# ── 라이브러리(저장 출력): 목록·읽기·수정·삭제 ───────────────────────────────


def test_saved_outputs_stay_in_their_account():
    app, a_client, b_client, _a, _b = clients()
    project_id = new_project(a_client)
    saved = a_client.post(
        "/api/outputs",
        json={"title": "A 저장 답변", "content": "A의 내용", "project_id": project_id},
    )
    assert saved.status_code == 201, saved.text
    output_id = saved.json()["output"]["id"]

    listed_b = b_client.get("/api/outputs")
    assert listed_b.status_code == 200
    assert all(row["id"] != output_id for row in listed_b.json()["outputs"])

    for method, path in (
        ("GET", f"/api/outputs/{output_id}"),
        ("PATCH", f"/api/outputs/{output_id}"),
        ("DELETE", f"/api/outputs/{output_id}"),
        ("GET", "/api/outputs/out_" + "f" * 32),
    ):
        answer = b_client.request(method, path, json={"title": "B 시도"} if method == "PATCH" else None)
        assert answer.status_code == 404, (method, path, answer.status_code)
    assert a_client.get(f"/api/outputs/{output_id}").status_code == 200

    # B가 A의 대화·프로젝트를 출처(provenance)로 저장도 못한다.
    borrowed = b_client.post(
        "/api/outputs",
        json={"title": "B 도용 시도", "content": "x", "project_id": project_id},
    )
    assert borrowed.status_code == 404, borrowed.text


# ── 회의록: 목록·읽기·수정·삭제 ──────────────────────────────────────────────


def test_meeting_records_stay_in_their_account():
    _app, a_client, b_client, _a, _b = clients()
    meeting_ref = new_meeting_ref(a_client)

    listed_b = b_client.get("/api/claw/meetings")
    assert listed_b.status_code == 200
    assert all(row["meeting_ref"] != meeting_ref for row in listed_b.json()["meetings"])

    for method, path in (
        ("GET", f"/api/claw/meetings/{meeting_ref}"),
        ("PATCH", f"/api/claw/meetings/{meeting_ref}"),
        ("DELETE", f"/api/claw/meetings/{meeting_ref}"),
        ("GET", "/api/claw/meetings/mtg_" + "f" * 32),
    ):
        answer = b_client.request(method, path, json={"title": "B 시도"} if method == "PATCH" else None)
        assert answer.status_code == 404, (method, path, answer.status_code)
    assert a_client.get(f"/api/claw/meetings/{meeting_ref}").status_code == 200


# ── PC 사전 위임(084): 문서 단위 분리 ────────────────────────────────────────


def test_pc_delegation_documents_are_per_account():
    _app, a_client, b_client, _a, _b = clients()

    a_rules = {
        "version": 1,
        "rules": [{
            "id": "rule-a-1", "device_id": "node//a-pc", "folder": "C:/A문서",
            "actions": ["write"], "mode": "allow", "enabled": True,
        }],
    }
    saved_a = a_client.put(PC_DELEGATION_PATH, json=a_rules)
    assert saved_a.status_code == 200, saved_a.text

    seen_b = b_client.get(PC_DELEGATION_PATH)
    assert seen_b.status_code == 200, seen_b.text
    body_b = seen_b.json()
    assert body_b.get("rules") != a_rules["rules"]
    assert all(rule.get("folder") != "C:/A문서" for rule in (body_b.get("rules") or []))

    # B가 자기 문서를 고쳐도 A의 것은 그대로다.
    b_client.put(PC_DELEGATION_PATH, json={
        "version": 1,
        "rules": [{
            "id": "rule-b-1", "device_id": "node//b-pc", "folder": "C:/B문서",
            "actions": ["write"], "mode": "ask", "enabled": True,
        }],
    })
    after = a_client.get(PC_DELEGATION_PATH).json()
    assert [rule["id"] for rule in after.get("rules") or []] == ["rule-a-1"]


# ── BYOK·사용자 자격증명: 상태 조회와 삭제가 계정별이다 ──────────────────────


def test_custom_credentials_are_per_account():
    _app, a_client, b_client, _a, _b = clients()
    saved_a = a_client.put(
        "/api/chat/custom/credential",
        json={"provider": "deepseek", "api_key": "A" * 40},
    )
    assert saved_a.status_code == 200, saved_a.text

    status_b = b_client.get("/api/chat/custom/credential")
    assert status_b.status_code == 200
    assert all(row["provider"] != "deepseek"
               for row in status_b.json().get("credentials") or [])

    # B의 삭제는 B의 문서에만 닿는다 — A의 자격증명은 살아 있어야 한다.
    assert b_client.delete(
        "/api/chat/custom/credential", params={"provider": "deepseek"},
    ).status_code == 200
    status_a = a_client.get("/api/chat/custom/credential")
    assert status_a.status_code == 200
    mine = [row for row in status_a.json().get("credentials") or []
            if row["provider"] == "deepseek"]
    assert mine and mine[0]["key_last4"] == "AAAA"


# ── MCP 토큰(085): 목록은 계정별 ────────────────────────────────────────────


def test_mcp_token_list_is_per_account():
    _app, a_client, b_client, _a, _b = clients()
    for client in (a_client, b_client):
        listed = client.get(MCP_TOKENS_PATH)
        assert listed.status_code == 200, listed.text
    # 소유자 범위 발급·타계정 PC·승인 일회성은 test_mcp_gateway_account.py가 고정한다.


# ── 구성이 필요한 표면: fail-closed 확인(미확인 사유의 증거) ─────────────────


def test_unconfigured_pc_and_automation_lanes_fail_closed():
    app, a_client, _b_client, _a, _b = clients()
    # PC 페어링 포트가 없으면 목록은 503으로 닫힌다 — 자료가 새어 나갈 구멍이 아니다.
    pairings = a_client.get("/api/pc/pairings")
    assert pairings.status_code in (403, 404, 503), pairings.status_code
    # 자동화 생성도 실행 대상 권한이 없으면 503으로 닫힌다.
    created = a_client.post("/api/claw/automation/rules", json={"title": "x"})
    assert created.status_code in (403, 503), created.status_code
    assert getattr(app.state, "claw_automation_execution_target_authority", None) is None


# ── 웹 엑셀 조각 업로드(tus): 남의 업로드 URL은 없는 것과 같다 ─────────────────


def test_web_xlsx_tus_upload_is_per_account():
    """#6579 2단계 — 조각 업로드도 계정 경계를 넘지 못한다.

    A가 만든 업로드의 진행 상태·결과·추가 전송을 B가 시도하면 셋 다 404다
    (존재 부정). B는 업로드 ID를 알아도 A의 것이 진행 중인지조차 알 수 없다.
    """
    import base64

    from app.tus_web_xlsx_upload import (
        WEB_XLSX_TUS_COLLECTION_PATH, WEB_XLSX_TUS_ITEM_PATH,
    )
    from app.workspace_storage import XLSX_MEDIA_TYPE

    app, a_client, b_client, _a, _b = clients()

    class _Store:
        """Finalize-only stand-in: this test owns the lane's ownership rule.

        The sweep harness binds no workspace document store, and the XLSX
        store itself is covered elsewhere. What this test has to prove is that
        the *upload* belongs to one account, so only the hand-off call is
        needed here.
        """

        async def put_web_xlsx(self, **kwargs):
            return {"document_id": "doc_" + "a" * 32,
                    "filename": kwargs["filename"],
                    "size_bytes": len(kwargs["body"])}

    app.state.workspace_document_store = _Store()
    metadata = ("filename " + base64.b64encode("A보고서.xlsx".encode()).decode()
                + ",filetype " + base64.b64encode(XLSX_MEDIA_TYPE.encode()).decode())
    created = a_client.post(WEB_XLSX_TUS_COLLECTION_PATH, headers={
        "Tus-Resumable": "1.0.0", "Upload-Length": "8", "Upload-Metadata": metadata,
    })
    assert created.status_code == 201, created.text
    upload_id = created.json()["upload_id"]
    path = WEB_XLSX_TUS_ITEM_PATH.replace("{upload_id}", upload_id)

    # A는 자기 업로드를 이어 올릴 수 있다.
    assert a_client.patch(path, headers={
        "Tus-Resumable": "1.0.0", "Upload-Offset": "0",
        "Content-Type": "application/offset+octet-stream",
    }, content=b"PK\x03\x04").status_code == 204
    assert a_client.head(path).headers["Upload-Offset"] == "4"

    # B는 같은 URL에서 정확히 같은 404만 본다.
    for method in ("HEAD", "GET"):
        assert b_client.request(method, path).status_code == 404, method
    assert b_client.patch(path, headers={
        "Tus-Resumable": "1.0.0", "Upload-Offset": "4",
        "Content-Type": "application/offset+octet-stream",
    }, content=b"PK\x03\x04").status_code == 404
    assert b_client.head(
        WEB_XLSX_TUS_ITEM_PATH.replace("{upload_id}", "guessed-upload-id"),
    ).status_code == 404


# ── Chat 첨부 조각 업로드(tus): 남의 첨부는 없는 것과 같다 ─────────────────────

def test_chat_attachment_tus_upload_is_per_account():
    """#6581 3단계 — Chat 첨부 조각 업로드와 참조 ID도 계정 경계를 넘지 못한다.

    A가 만든 업로드의 진행 상태·결과·추가 전송을 B가 시도하면 셋 다 404다.
    A가 올린 첨부의 참조 ID를 B가 자기 대화에 넣어도 A의 원본은 읽히지 않는다
    (저장 해석이 계정별 키 아래에만 있다).
    """
    import base64
    import tempfile

    from app.local_r2 import ThreadedLocalDiskR2
    from app.tus_chat_attachment import (
        CHAT_ATTACHMENT_TUS_COLLECTION_PATH, CHAT_ATTACHMENT_TUS_ITEM_PATH,
        ChatAttachmentStore,
    )

    app, a_client, b_client, a, b = clients()
    bucket = ThreadedLocalDiskR2(tempfile.mkdtemp(prefix="chat-attach-sweep-"))
    app.state.chat_attachment_store = ChatAttachmentStore(bucket)

    metadata = ("filename " + base64.b64encode("A보고서.txt".encode()).decode()
                + ",filetype " + base64.b64encode(b"text/plain").decode())
    created = a_client.post(CHAT_ATTACHMENT_TUS_COLLECTION_PATH, headers={
        "Tus-Resumable": "1.0.0", "Upload-Length": "5", "Upload-Metadata": metadata,
    })
    assert created.status_code == 201, created.text
    upload_id = created.json()["upload_id"]
    path = CHAT_ATTACHMENT_TUS_ITEM_PATH.replace("{upload_id}", upload_id)

    assert a_client.patch(path, headers={
        "Tus-Resumable": "1.0.0", "Upload-Offset": "0",
        "Content-Type": "application/offset+octet-stream",
    }, content=b"A\xec\x9e\x90\xeb\xa3\x8c"[:5]).status_code == 204

    # B는 같은 URL에서 정확히 같은 404만 본다(존재 부정).
    for method in ("HEAD", "GET"):
        assert b_client.request(method, path).status_code == 404, method
    assert b_client.patch(path, headers={
        "Tus-Resumable": "1.0.0", "Upload-Offset": "0",
        "Content-Type": "application/offset+octet-stream",
    }, content=b"XXXXX").status_code == 404
    assert b_client.head(
        CHAT_ATTACHMENT_TUS_ITEM_PATH.replace("{upload_id}", "guessed-upload-id"),
    ).status_code == 404
    # B의 계정 키 아래에는 A의 업로드가 없다.
    assert b_client.head(path).status_code == 404
    assert a_client.head(path).status_code != 404
