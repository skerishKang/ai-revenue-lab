"""#4489 — owner-scoped keyset pagination over every stored project file.

The Library used to read 20 projects and fan out one request per project, so an account
with more history could never reach its older files. `GET /api/project-files` replaces
that walk with bounded keyset pages. These tests run the real D1 SQL against SQLite and
prove the properties the UI is allowed to claim:

* a full walk returns every owner file exactly once, in the server's stated order;
* only the signed-in owner's rows can appear, and no file content crosses the route;
* a cursor is refused when malformed and cannot widen the read when well-formed;
* page bounds are enforced on the request, not silently clamped;
* a store without the capability returns an honest 503 instead of falling back to a
  partial per-project read.
"""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlencode

from starlette.requests import Request

from app.project_file_routes import owner_files_collection
from app.project_files import (
    DEFAULT_OWNER_FILES_PAGE,
    MAX_OWNER_FILES_PAGE,
    D1ProjectFileStore,
    OwnerFileCursorError,
    OwnerFileProjection,
    decode_owner_file_cursor,
    encode_owner_file_cursor,
)

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"

OWNER = "usr_" + "a" * 32
FOREIGN = "usr_" + "b" * 32
EMPTY_OWNER = "usr_" + "c" * 32
PROJECT_ONE = "proj_" + "1" * 32
PROJECT_TWO = "proj_" + "2" * 32
FOREIGN_PROJECT = "proj_" + "9" * 32

ID_NEWEST = "file_" + "a" * 32
ID_TIE_A = "file_" + "b" * 32
ID_TIE_B = "file_" + "c" * 32
ID_MIDDLE = "file_" + "d" * 32
ID_OLDEST = "file_" + "e" * 32
ID_FOREIGN = "file_" + "f" * 32

# Keyset order is (updated_at DESC, id DESC). Two rows share one timestamp, so the id
# tie-break is what separates them; a cursor built on time alone would repeat or skip
# exactly there.
MARKS = [
    (ID_NEWEST, PROJECT_ONE, "newest.txt", "2026-10-13T00:00:05.000Z"),
    (ID_TIE_A, PROJECT_ONE, "tie-a.txt", "2026-10-13T00:00:04.000Z"),
    (ID_TIE_B, PROJECT_TWO, "tie-b.txt", "2026-10-13T00:00:04.000Z"),
    (ID_MIDDLE, PROJECT_TWO, "middle.txt", "2026-10-13T00:00:03.000Z"),
    (ID_OLDEST, PROJECT_ONE, "oldest.txt", "2026-10-13T00:00:01.000Z"),
]
EXPECTED_ORDER = [ID_NEWEST, ID_TIE_B, ID_TIE_A, ID_MIDDLE, ID_OLDEST]
PROJECT_NAMES = {PROJECT_ONE: "견적 작업", PROJECT_TWO: "계약 검토"}


class D1Statement:
    def __init__(self, connection, sql, values=()):
        self.conn, self.sql, self.values = connection, sql, values

    def bind(self, *values):
        return D1Statement(self.conn, self.sql, values)

    async def first(self):
        row = self.conn.execute(self.sql, self.values).fetchone()
        return dict(row) if row is not None else None

    async def run(self):
        cursor = self.conn.execute(self.sql, self.values)
        return SimpleNamespace(
            results=[dict(row) for row in cursor.fetchall()],
            meta={"changes": cursor.rowcount},
        )


class D1Sqlite:
    def __init__(self, connection):
        self.connection = connection

    def prepare(self, sql):
        return D1Statement(self.connection, sql)


def setup_database() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    for name in ("001_auth_history.sql", "002_projects.sql", "003_project_files.sql"):
        db.executescript((MIGRATIONS / name).read_text(encoding="utf-8"))
    for owner, subject in (
        (OWNER, "subject-owner"), (FOREIGN, "subject-foreign"), (EMPTY_OWNER, "subject-empty"),
    ):
        db.execute(
            "INSERT INTO users(id,auth_provider,provider_subject,email,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (owner, "google", subject, f"{subject}@example.invalid", "2026-10-01", "2026-10-01"),
        )
    for project, owner, name in (
        (PROJECT_ONE, OWNER, PROJECT_NAMES[PROJECT_ONE]),
        (PROJECT_TWO, OWNER, PROJECT_NAMES[PROJECT_TWO]),
        (FOREIGN_PROJECT, FOREIGN, "남의 프로젝트"),
    ):
        db.execute(
            "INSERT INTO projects(id,user_id,name,instructions,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (project, owner, name, "", "2026-10-01", "2026-10-01"),
        )
    for file, project, name, stamp in MARKS:
        db.execute(
            "INSERT INTO project_files(id,project_id,user_id,name,media_type,content_text,"
            "content_chars,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (file, project, OWNER, name, "text/plain", "SECRET-CONTENT-" + name, 14, stamp, stamp),
        )
    db.execute(
        "INSERT INTO project_files(id,project_id,user_id,name,media_type,content_text,"
        "content_chars,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (ID_FOREIGN, FOREIGN_PROJECT, FOREIGN, "foreign.txt", "text/plain",
         "SECRET-CONTENT-FOREIGN", 20, "2026-10-13T00:00:09.000Z", "2026-10-13T00:00:09.000Z"),
    )
    db.commit()
    return db


def build_request(store, *, query=None) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/api/project-files",
        "query_string": urlencode(query or {}).encode(),
        "headers": [],
        "app": SimpleNamespace(state=SimpleNamespace(
            project_file_store=store,
            history_store=None,
        )),
    })


async def _call(store, *, query=None, owner=OWNER, ready=True):
    request = build_request(store, query=query)
    with patch("app.project_file_routes.auth_ready", return_value=ready), \
         patch("app.project_file_routes.current_user_id",
               return_value=owner if ready else None):
        response = await owner_files_collection(request)
    return response.status_code, json.loads(response.body.decode())


def call(store, **kwargs):
    return asyncio.run(_call(store, **kwargs))


def projection(**overrides) -> OwnerFileProjection:
    base = dict(
        id=ID_OLDEST, project_id=PROJECT_ONE, project_name="", name="oldest.txt",
        media_type="text/plain", content_chars=14,
        created_at="2026-10-13T00:00:01.000Z", updated_at="2026-10-13T00:00:01.000Z",
    )
    base.update(overrides)
    return OwnerFileProjection(**base)


def test_full_walk_returns_every_owner_file_exactly_once():
    db = setup_database()
    try:
        store = D1ProjectFileStore(D1Sqlite(db))
        seen: list[str] = []
        positions: list[tuple[str, str]] = []
        cursor = None
        pages = 0
        while True:
            query = {"limit": "2"}
            if cursor:
                query["cursor"] = cursor
            code, body = call(store, query=query)
            assert code == 200, body
            pages += 1
            assert pages <= 4, "the walk must terminate on the server's own has_more flag"
            for item in body["files"]:
                seen.append(item["id"])
                positions.append((item["updated_at"], item["id"]))
            if not body["has_more"]:
                assert body["next_cursor"] is None
                break
            cursor = body["next_cursor"]
        assert seen == EXPECTED_ORDER, seen
        assert len(set(seen)) == len(seen), "a page boundary repeated a file"
        assert positions == sorted(positions, reverse=True)
        assert pages == 3
    finally:
        db.close()


def test_projection_labels_the_owning_project_and_never_carries_content():
    db = setup_database()
    try:
        store = D1ProjectFileStore(D1Sqlite(db))
        code, body = call(store, query={"limit": "100"})
        assert code == 200
        assert len(body["files"]) == 5
        by_name = {item["name"]: item for item in body["files"]}
        assert by_name["oldest.txt"]["project_name"] == PROJECT_NAMES[PROJECT_ONE]
        assert by_name["middle.txt"]["project_name"] == PROJECT_NAMES[PROJECT_TWO]
        assert by_name["tie-a.txt"]["project_id"] == PROJECT_ONE
        blob = json.dumps(body, ensure_ascii=False)
        for forbidden in ("content_text", "SECRET-CONTENT", "usr_", FOREIGN_PROJECT, ID_FOREIGN):
            assert forbidden not in blob, forbidden
    finally:
        db.close()


def test_another_owner_sees_only_its_own_rows():
    db = setup_database()
    try:
        store = D1ProjectFileStore(D1Sqlite(db))
        code, body = call(store, query={"limit": "100"}, owner=FOREIGN)
        assert code == 200
        assert [item["name"] for item in body["files"]] == ["foreign.txt"]
        assert body["has_more"] is False and body["next_cursor"] is None
    finally:
        db.close()


def test_account_without_files_is_an_honest_empty_page():
    db = setup_database()
    try:
        store = D1ProjectFileStore(D1Sqlite(db))
        code, body = call(store, query={"limit": "100"}, owner=EMPTY_OWNER)
        assert code == 200, body
        assert body["files"] == []
        assert body["has_more"] is False
        assert body["next_cursor"] is None
    finally:
        db.close()


def test_malformed_cursor_is_refused_and_empty_cursor_is_the_first_page():
    db = setup_database()
    try:
        store = D1ProjectFileStore(D1Sqlite(db))
        for bad in ("not-base64-%", "!!!", "aHRlbG8", "eQ", "QQ==" * 60):
            code, body = call(store, query={"cursor": bad})
            assert code == 400, (bad, body)
            assert body["error"]["code"] == "invalid_cursor", (bad, body)
        # A URL builder that emits `cursor=` is asking for the first page, not a position.
        code, body = call(store, query={"cursor": "", "limit": "2"})
        assert code == 200, body
        assert [item["id"] for item in body["files"]] == EXPECTED_ORDER[:2]
    finally:
        db.close()


def test_a_wellformed_cursor_cannot_reach_other_accounts():
    db = setup_database()
    try:
        store = D1ProjectFileStore(D1Sqlite(db))
        # Position taken from a FOREIGN row: user_id is bound from the session, never
        # from the cursor, so this only moves the owner's own window.
        cross = encode_owner_file_cursor(projection(id=ID_FOREIGN))
        code, body = call(store, query={"cursor": cross, "limit": "100"})
        assert code == 200, body
        assert all(item["id"] in EXPECTED_ORDER for item in body["files"]), body
        assert ID_FOREIGN not in [item["id"] for item in body["files"]]
        # Keyset order is newest-first, so a position *newer* than every row is simply
        # the start of the walk, and a position older than every row is the end of it.
        ahead = base64.urlsafe_b64encode(
            b"2026-10-14T00:00:00.000Z|" + ID_OLDEST.encode()
        ).decode().rstrip("=")
        code, body = call(store, query={"cursor": ahead, "limit": "100"})
        assert code == 200 and len(body["files"]) == 5 and body["has_more"] is False
        past_end = base64.urlsafe_b64encode(
            b"2026-10-01T00:00:00.000Z|" + ID_OLDEST.encode()
        ).decode().rstrip("=")
        code, body = call(store, query={"cursor": past_end, "limit": "100"})
        assert code == 200 and body["files"] == [] and body["has_more"] is False
    finally:
        db.close()


def test_limit_is_validated_not_clamped():
    db = setup_database()
    try:
        store = D1ProjectFileStore(D1Sqlite(db))
        for bad in ("0", "-1", "abc", "1.5", str(MAX_OWNER_FILES_PAGE + 1), "999999"):
            code, body = call(store, query={"limit": bad})
            assert code == 400, (bad, body)
            assert body["error"]["code"] == "invalid_limit", (bad, body)
        code, body = call(store)
        assert code == 200 and body["limit"] == DEFAULT_OWNER_FILES_PAGE
        code, body = call(store, query={"limit": str(MAX_OWNER_FILES_PAGE)})
        assert code == 200 and body["limit"] == MAX_OWNER_FILES_PAGE
    finally:
        db.close()


def test_unauthenticated_and_unavailable_auth_fail_closed():
    db = setup_database()
    try:
        store = D1ProjectFileStore(D1Sqlite(db))
        code, body = call(store, ready=False)
        assert code == 503 and body["error"]["code"] == "project_files_unavailable"
        code, body = call(store, owner=None)
        assert code == 401 and body["error"]["code"] == "unauthorized"
    finally:
        db.close()


def test_store_without_the_capability_returns_unavailable_not_a_partial_read():
    class LegacyStore:
        async def list_files(self, user_id, project_id):
            raise AssertionError("the per-project fallback walk must not be attempted")

    code, body = call(LegacyStore(), query={"limit": "2"})
    assert code == 503, body
    assert body["error"]["code"] == "project_files_unavailable"


def test_cursor_token_round_trip_is_strict():
    token = encode_owner_file_cursor(projection())
    assert decode_owner_file_cursor(token) == ("2026-10-13T00:00:01.000Z", ID_OLDEST)
    for bad in (None, 7, "   ", "a" * 300, base64.urlsafe_b64encode(b"no-separator").decode()):
        try:
            decode_owner_file_cursor(bad)
        except OwnerFileCursorError:
            continue
        raise AssertionError(f"accepted a malformed cursor: {bad!r}")
    # A cursor carrying a non-canonical timestamp is a forgery, not a position.
    smuggled = base64.urlsafe_b64encode(f"2026-10-13 00:00:01|{ID_OLDEST}".encode()).decode()
    try:
        decode_owner_file_cursor(smuggled.rstrip("="))
    except OwnerFileCursorError:
        pass
    else:
        raise AssertionError("accepted a non-canonical cursor timestamp")
