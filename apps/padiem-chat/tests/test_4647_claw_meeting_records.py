"""#4647 meeting ledger: real D1-shaped SQL on SQLite plus the record API boundary.

No Google Drive call, no Engine call, no model call and no production database.
Migrations 049-051 are applied in their documented order, twice, to prove the
additive-only claim the COM2 migration owner needs.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app import claw_meeting_routes as api
from app.claw_meeting_store import D1ClawMeetingStore, MeetingRecordError

MIGRATIONS = ("049_claw_meetings.sql", "050_claw_meeting_artifacts.sql",
              "051_claw_meeting_actions.sql")
MIGRATION_DIR = Path(__file__).resolve().parents[1] / "migrations"
ORIGIN = "https://chat.example.test"
OWNER = "usr_" + "a" * 32
FOREIGN = "usr_" + "b" * 32
WORKSPACE = "workspace_own"
OTHER_WORKSPACE = "workspace_other"


class D1Sqlite:
    """The same D1 statement surface the Worker gives the store, backed by SQLite."""

    def __init__(self, conn):
        self.conn = conn

    def prepare(self, query):
        return Statement(self.conn, query)


class Statement:
    def __init__(self, conn, query):
        self.conn, self.query, self.args = conn, query, ()

    def bind(self, *args):
        self.args = args
        return self

    async def run(self):
        self.conn.execute(self.query, self.args)
        return {"meta": {"changes": self.conn.execute("SELECT CHANGES()").fetchone()[0]}}

    async def first(self):
        row = self.conn.execute(self.query, self.args).fetchone()
        return dict(row) if row else None

    async def all(self):
        return [dict(r) for r in self.conn.execute(self.query, self.args).fetchall()]


def apply_meeting_schema(conn, *, twice=False):
    for _ in range(2 if twice else 1):
        for name in MIGRATIONS:
            conn.executescript((MIGRATION_DIR / name).read_text(encoding="utf-8"))


def connection():
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT NOT NULL,"
                 " created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
    for seed in (OWNER, FOREIGN):
        conn.execute("INSERT INTO users (id,email,created_at,updated_at) "
                     "VALUES (?,?,datetime('now'),datetime('now'))",
                     (seed, seed.replace("usr_", "owner") + "@example.test"))
    apply_meeting_schema(conn)
    return conn


def store(conn):
    return D1ClawMeetingStore(D1Sqlite(conn))


def make_request(payload=None, *, method="POST", path=api.MEETINGS_PATH,
                 origin=ORIGIN, meeting_store=None, workspace=WORKSPACE,
                 authed=True, owner=OWNER, signed=False):
    raw = b"" if payload is None else json.dumps(payload).encode()
    headers = [(b"origin", origin.encode())]
    if raw:
        headers.append((b"content-type", b"application/json"))
    state = SimpleNamespace(
        settings=SimpleNamespace(public_base_url=ORIGIN),
        claw_meeting_store=meeting_store,
    )
    param_name = ("action_ref" if path == api.MEETING_ACTION_PATH else "meeting_ref")
    scope = {"type": "http", "method": method, "path": path, "query_string": b"",
             "headers": headers, "app": SimpleNamespace(state=state),
             "path_params": {param_name: signed} if signed else {}}

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}

    request = Request(scope, receive=receive)
    request._authed = authed  # noqa: SLF001 - monkeypatch target below
    return request


@pytest.fixture
def patched(monkeypatch):
    monkeypatch.setattr(api, "auth_ready", lambda _: True)
    monkeypatch.setattr(api, "current_user_id", lambda _: OWNER)
    async def workspace_of(request, user_id):
        return WORKSPACE
    monkeypatch.setattr(api, "_resolve_memory_workspace", workspace_of)
    return monkeypatch


async def call(handler, request):
    return await handler(request)


# ── schema ───────────────────────────────────────────────────────────────────

def test_migrations_apply_in_documented_order_and_are_idempotent():
    conn = connection()
    apply_meeting_schema(conn, twice=True)
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"claw_meetings", "claw_meeting_artifacts", "claw_meeting_actions"} <= tables
    conn.close()


def test_schema_rejects_states_that_code_must_not_have_to_guard_alone():
    conn = connection()
    meeting = "mtg_" + "1" * 32
    conn.execute("INSERT INTO claw_meetings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (meeting, OWNER, WORKSPACE, "t", "both", "active",
                  "2026-10-18T00:00:00+00:00", None,
                  "2026-10-18T00:00:00+00:00", "2026-10-18T00:00:00+00:00"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO claw_meeting_artifacts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     ("mfa_" + "1" * 32, meeting, OWNER, WORKSPACE, "audio", "drive_saved",
                      None, "a.webm", "audio/webm", 10, "now", "now"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO claw_meetings VALUES (?,?,?,?,?,?,?,?,?,?)",
                     ("mtg_" + "2" * 32, OWNER, WORKSPACE, "t", "streaming", "active",
                      None, None, "now", "now"))
    conn.close()


@pytest.mark.asyncio
async def test_artifact_rows_replace_per_kind_and_go_with_the_meeting():
    conn = connection()
    ledger = store(conn)
    meeting = await ledger.create(owner_id=OWNER, workspace_id=WORKSPACE,
                                  title="주 1회 운영 회의", mode="both")
    ref = meeting["meeting_ref"]
    await ledger.put_artifact(owner_id=OWNER, workspace_id=WORKSPACE, meeting_ref=ref,
                              kind="audio", state="local_only", filename="a.webm")
    await ledger.put_artifact(owner_id=OWNER, workspace_id=WORKSPACE, meeting_ref=ref,
                              kind="audio", state="drive_saved",
                              drive_file_id="Dr1vF1leId0000000", filename="a.webm",
                              mime_type="audio/webm", byte_size=1234)
    rows = await ledger.list_artifacts(owner_id=OWNER, workspace_id=WORKSPACE,
                                       meeting_ref=ref)
    assert [dict(row) for row in rows] == [{
        "artifact_ref": rows[0]["artifact_ref"], "kind": "audio", "state": "drive_saved",
        "drive_file_id": "Dr1vF1leId0000000", "filename": "a.webm",
        "mime_type": "audio/webm", "byte_size": 1234,
        "created_at": rows[0]["created_at"], "updated_at": rows[0]["updated_at"]}]
    assert await ledger.delete(owner_id=OWNER, workspace_id=WORKSPACE, meeting_ref=ref) is True
    assert conn.execute("SELECT COUNT(*) FROM claw_meeting_artifacts").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM claw_meetings").fetchone()[0] == 0
    conn.close()


# ── ledger behaviour ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_lists_and_loads_only_for_its_own_owner_and_workspace():
    conn = connection()
    ledger = store(conn)
    first = await ledger.create(owner_id=OWNER, workspace_id=WORKSPACE,
                                title="10월 운영 회의", mode="record")
    await ledger.create(owner_id=FOREIGN, workspace_id=WORKSPACE,
                        title="다른 고객 회의", mode="both")
    await ledger.create(owner_id=OWNER, workspace_id=OTHER_WORKSPACE,
                        title="다른 워크스페이스 회의", mode="transcribe")
    listed = await ledger.list_owner(owner_id=OWNER, workspace_id=WORKSPACE)
    assert [row["meeting_ref"] for row in listed] == [first["meeting_ref"]]
    assert await ledger.load(owner_id=FOREIGN, workspace_id=WORKSPACE,
                             meeting_ref=first["meeting_ref"]) is None
    assert await ledger.load(owner_id=OWNER, workspace_id=OTHER_WORKSPACE,
                             meeting_ref=first["meeting_ref"]) is None
    assert (await ledger.rename(owner_id=FOREIGN, workspace_id=WORKSPACE,
                                meeting_ref=first["meeting_ref"], title="탈취")) is False
    conn.close()


@pytest.mark.asyncio
async def test_status_machine_ends_once_and_never_reopens():
    conn = connection()
    ledger = store(conn)
    meeting = await ledger.create(owner_id=OWNER, workspace_id=WORKSPACE,
                                  title="종료 테스트", mode="both")
    ref = meeting["meeting_ref"]
    assert await ledger.finish(owner_id=OWNER, workspace_id=WORKSPACE, meeting_ref=ref) is True
    assert await ledger.finish(owner_id=OWNER, workspace_id=WORKSPACE, meeting_ref=ref) is False
    row = await ledger.load(owner_id=OWNER, workspace_id=WORKSPACE, meeting_ref=ref)
    assert row["status"] == "ended" and row["ended_at"]
    assert await ledger.rename(owner_id=OWNER, workspace_id=WORKSPACE,
                               meeting_ref=ref, title="후속 수정") is True
    conn.close()


@pytest.mark.asyncio
async def test_discarded_meetings_leave_the_list_but_stay_addressable_for_nobody():
    conn = connection()
    ledger = store(conn)
    meeting = await ledger.create(owner_id=OWNER, workspace_id=WORKSPACE,
                                  title="버린 회의", mode="record")
    ref = meeting["meeting_ref"]
    assert await ledger.finish(owner_id=OWNER, workspace_id=WORKSPACE,
                               meeting_ref=ref, discard=True) is True
    assert await ledger.list_owner(owner_id=OWNER, workspace_id=WORKSPACE) == []
    assert await ledger.rename(owner_id=OWNER, workspace_id=WORKSPACE,
                               meeting_ref=ref, title="되살리기") is False
    conn.close()


@pytest.mark.asyncio
async def test_ledger_refuses_invalid_vocabularies_and_sizes():
    conn = connection()
    ledger = store(conn)
    meeting = await ledger.create(owner_id=OWNER, workspace_id=WORKSPACE,
                                  title="검증 회의", mode="both")
    ref = meeting["meeting_ref"]
    for bad in ({"mode": "streaming"}, {"title": " "}, {"title": "x" * 201}):
        kwargs = {"owner_id": OWNER, "workspace_id": WORKSPACE,
                  "title": bad.get("title", "t"), "mode": bad.get("mode", "record")}
        with pytest.raises(MeetingRecordError):
            await ledger.create(**kwargs)
    with pytest.raises(MeetingRecordError):
        await ledger.put_artifact(owner_id=OWNER, workspace_id=WORKSPACE, meeting_ref=ref,
                                  kind="audio", state="drive_saved",
                                  drive_file_id="short", filename="a.webm")
    with pytest.raises(MeetingRecordError):
        await ledger.put_artifact(owner_id=OWNER, workspace_id=WORKSPACE, meeting_ref=ref,
                                  kind="minutes", state="local_only",
                                  drive_file_id="Dr1vF1leId0000000", filename="m.txt")
    with pytest.raises(MeetingRecordError):
        await ledger.add_action(owner_id=OWNER, workspace_id=WORKSPACE, meeting_ref=ref,
                                kind="decision", summary="결정", due_date="다음 주")
    with pytest.raises(MeetingRecordError):
        await ledger.add_action(owner_id=OWNER, workspace_id=WORKSPACE, meeting_ref=ref,
                                kind="followup", summary="후속",
                                evidence_start=10, evidence_end=4)
    conn.close()


@pytest.mark.asyncio
async def test_action_candidates_move_only_between_human_states():
    conn = connection()
    ledger = store(conn)
    meeting = await ledger.create(owner_id=OWNER, workspace_id=WORKSPACE,
                                  title="액션 테스트", mode="transcribe")
    ref = meeting["meeting_ref"]
    action = await ledger.add_action(owner_id=OWNER, workspace_id=WORKSPACE, meeting_ref=ref,
                                     kind="followup", summary="견적서 수정",
                                     owner_label="김담당", due_date="2026-10-23",
                                     evidence_start=0, evidence_end=42)
    assert action["status"] == "candidate"
    with pytest.raises(MeetingRecordError):
        await ledger.decide_action(owner_id=OWNER, workspace_id=WORKSPACE,
                                   action_ref=action["action_ref"], status="registered")
    assert await ledger.decide_action(owner_id=OWNER, workspace_id=WORKSPACE,
                                      action_ref=action["action_ref"],
                                      status="confirmed") is True
    assert await ledger.decide_action(owner_id=OWNER, workspace_id=WORKSPACE,
                                      action_ref=action["action_ref"],
                                      status="dismissed") is False
    assert await ledger.delete_action(owner_id=OWNER, workspace_id=WORKSPACE,
                                      action_ref=action["action_ref"]) is True
    assert await ledger.list_actions(owner_id=OWNER, workspace_id=WORKSPACE,
                                     meeting_ref=ref) == []
    conn.close()


# ── HTTP boundary ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_api_creates_lists_and_deletes_without_claiming_drive_deletion(patched):
    conn = connection()
    ledger = store(conn)
    created = await call(api.claw_meetings,
                         make_request({"title": "주간 회의", "mode": "both"},
                                      meeting_store=ledger))
    assert created.status_code == 201
    ref = json.loads(created.body)["meeting"]["meeting_ref"]

    listed = await call(api.claw_meetings, make_request(method="GET", meeting_store=ledger))
    assert [m["meeting_ref"] for m in json.loads(listed.body)["meetings"]] == [ref]

    removed = await call(api.claw_meeting_detail,
                         make_request(method="DELETE", path=api.MEETING_PATH,
                                      meeting_store=ledger, signed=ref))
    body = json.loads(removed.body)
    assert removed.status_code == 200
    assert body["record_deleted"] is True
    assert body["drive_files_deleted"] is False
    assert "Google Drive 파일은 사용자 Drive에 남아 있습니다" in body["drive_note"]
    conn.close()


@pytest.mark.asyncio
async def test_api_detail_patch_end_and_action_routes(patched):
    conn = connection()
    ledger = store(conn)
    ref = (await ledger.create(owner_id=OWNER, workspace_id=WORKSPACE,
                               title="상세 테스트", mode="record"))["meeting_ref"]

    detail = await call(api.claw_meeting_detail,
                        make_request(method="GET", path=api.MEETING_PATH,
                                     meeting_store=ledger, signed=ref))
    assert json.loads(detail.body)["meeting"]["title"] == "상세 테스트"

    renamed = await call(api.claw_meeting_detail,
                         make_request({"title": "이름 변경"}, method="PATCH",
                                      path=api.MEETING_PATH, meeting_store=ledger, signed=ref))
    assert json.loads(renamed.body)["meeting"]["title"] == "이름 변경"

    artifact = await call(api.claw_meeting_artifact,
                          make_request({"kind": "transcript", "state": "drive_saved",
                                        "drive_file_id": "Dr1vF1leId0000000",
                                        "filename": "padiem-meeting.txt",
                                        "mime_type": "text/plain", "byte_size": 21},
                                       path=api.MEETING_ARTIFACT_PATH,
                                       meeting_store=ledger, signed=ref))
    assert artifact.status_code == 201

    action = await call(api.claw_meeting_action_create,
                        make_request({"kind": "decision", "summary": "예산 승인"},
                                     path=api.MEETING_ACTIONS_PATH,
                                     meeting_store=ledger, signed=ref))
    assert action.status_code == 201
    aref = json.loads(action.body)["action"]["action_ref"]

    decided = await call(api.claw_meeting_action,
                         make_request({"status": "confirmed"}, method="PATCH",
                                      path=api.MEETING_ACTION_PATH,
                                      meeting_store=ledger, signed=aref))
    assert decided.status_code == 200

    refused = await call(api.claw_meeting_action,
                         make_request({"status": "registered"}, method="PATCH",
                                      path=api.MEETING_ACTION_PATH,
                                      meeting_store=ledger, signed=aref))
    assert refused.status_code == 400

    ended = await call(api.claw_meeting_end,
                       make_request({}, path=api.MEETING_END_PATH,
                                    meeting_store=ledger, signed=ref))
    assert ended.status_code == 200 and json.loads(ended.body)["meeting"]["status"] == "ended"

    again = await call(api.claw_meeting_end,
                       make_request({}, path=api.MEETING_END_PATH,
                                    meeting_store=ledger, signed=ref))
    assert again.status_code == 409
    conn.close()


@pytest.mark.asyncio
async def test_api_guards_origin_auth_store_shape_and_unknown_refs(patched):
    conn = connection()
    ledger = store(conn)
    ref = (await ledger.create(owner_id=OWNER, workspace_id=WORKSPACE,
                               title="가드 테스트", mode="record"))["meeting_ref"]

    evil = await call(api.claw_meetings, make_request({"title": "t", "mode": "record"},
                                                      origin="https://evil.example",
                                                      meeting_store=ledger))
    assert evil.status_code == 403

    patched.setattr(api, "auth_ready", lambda _: False)
    assert (await call(api.claw_meetings,
                       make_request(method="GET", meeting_store=ledger))).status_code == 401
    patched.setattr(api, "auth_ready", lambda _: True)

    assert (await call(api.claw_meetings,
                       make_request(method="GET", meeting_store=None))).status_code == 503

    injected = await call(api.claw_meetings,
                          make_request({"title": "t", "mode": "record",
                                        "user_id": FOREIGN, "workspace_id": OTHER_WORKSPACE},
                                       meeting_store=ledger))
    assert injected.status_code == 400
    assert await ledger.load(owner_id=FOREIGN, workspace_id=OTHER_WORKSPACE,
                             meeting_ref=ref) is None

    for bad_path in ("mtg_short", "mtg_" + "z" * 32, "mct_" + "1" * 32):
        response = await call(api.claw_meeting_detail,
                              make_request(method="GET", path=api.MEETING_PATH,
                                           meeting_store=ledger, signed=bad_path))
        assert response.status_code == 404, bad_path
    conn.close()
