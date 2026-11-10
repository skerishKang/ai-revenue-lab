"""#7388: conversation deletion is a marker with a 30-day retention window.

The store, the purge pass and the operator restore run against the real D1 SQL on
sqlite with the real migrations, so the statements that decide visibility are
exercised rather than re-implemented. The connection deliberately has no
``PRAGMA foreign_keys``: the COM2 host connection has none either, which is
exactly why the purge deletes messages itself instead of relying on
``ON DELETE CASCADE``.

Contract under test (대표 결정 2026-11-10):
- deleting a conversation hides it from every product read immediately,
- the row and its messages stay for 30 days, with no user-facing restore,
- the daily pass deletes messages, the row and the R2 originals afterwards,
- account deletion keeps deleting everything immediately.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import app.conversation_purge as conversation_purge
import app.history as history_module
from app.conversation_purge import (
    DEFAULT_RETENTION_DAYS,
    HISTORY_PREVIEW_SUFFIX,
    MAX_HISTORY_MESSAGE_CHARS,
    purge_deleted_conversations,
    retention_days_from_env,
)
from app.conversation_restore import (
    NOT_DELETED,
    NOT_FOUND,
    RESTORED,
    WINDOW_CLOSED,
    restore_conversation,
)
from app.d1_sqlite import SqliteD1
from app.history import D1HistoryStore, HistoryForbidden, PRODUCT_SCOPE_CHAT
from app.local_cpython import apply_migrations

APP_DIR = Path(__file__).resolve().parents[1] / "app"
REPO_ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc)
USER = "usr_" + "a" * 32
OTHER_USER = "usr_" + "b" * 32

#: Files whose conversation SELECT is allowed to skip the marker: the account
#: purge reads by owner on purpose, so a marked row is deleted immediately.
_MARKER_GUARD_ALLOWED = {
    "account_deletion.py": "탈퇴는 삭제 표시 여부와 무관하게 그 사용자의 모든 행을 지운다",
}

#: Files whose DELETE on conversations is allowed without an adjacent messages
#: DELETE: the account purge names `messages` as its own child-before-parent
#: entry in `_USER_KEYED_TABLES`.
_DELETE_GUARD_ALLOWED = {
    "account_deletion.py": "messages가 _USER_KEYED_TABLES의 자식 항목으로 함께 지워진다",
}


def _stamp(days: float) -> str:
    return (NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


class _Bucket:
    """Minimal R2 stand-in; the purge only needs put/delete/get by key."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, body: bytes, httpMetadata=None) -> None:
        self.objects[key] = bytes(body)

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    def get(self, key: str):
        return self.objects.get(key)


@pytest.fixture
def connection(tmp_path):
    con = sqlite3.connect(str(tmp_path / "chat.sqlite3"), isolation_level=None)
    con.row_factory = sqlite3.Row
    apply_migrations(con)
    for user_id, subject in ((USER, "sub_a"), (OTHER_USER, "sub_b")):
        con.execute(
            "INSERT INTO users (id, auth_provider, provider_subject, email, "
            "display_name, picture_url, created_at, updated_at) "
            "VALUES (?, 'google', ?, ?, '', '', ?, ?)",
            (user_id, subject, f"{subject}@example.test", _stamp(1), _stamp(1)),
        )
    yield con
    con.close()


@pytest.fixture
def bucket():
    return _Bucket()


@pytest.fixture
def store(connection, bucket):
    return D1HistoryStore(SqliteD1(connection), full_context_bucket=bucket)


async def _conversation(store, text: str = "표시 확인", *, project_id=None) -> str:
    return await store.append_exchange(
        USER, None, text, "답변", project_id, product_scope=PRODUCT_SCOPE_CHAT,
    )


def _scalar(connection, sql: str, *values):
    return connection.execute(sql, values).fetchone()[0]


async def _delete_keys(bucket):
    async def delete(keys: list[str]) -> None:
        for key in keys:
            bucket.delete(key)
    return delete


# ---------------------------------------------------------------------------
# 1. The marker hides the conversation from every product surface at once.
# ---------------------------------------------------------------------------


async def test_delete_marks_the_row_and_keeps_its_messages(store, connection):
    conversation = await _conversation(store)

    assert await store.delete_conversation(
        USER, conversation, product_scope=PRODUCT_SCOPE_CHAT
    ) is True

    marked = _scalar(
        connection, "SELECT deleted_at FROM conversations WHERE id=?", conversation
    )
    assert marked is not None
    # The rows are retained, not deleted: that is what makes the window real.
    assert _scalar(
        connection, "SELECT COUNT(*) FROM messages WHERE conversation_id=?", conversation
    ) == 2


async def test_every_product_read_hides_the_marked_conversation(store):
    project = await store.create_project(USER, "프로젝트", "")
    live = await _conversation(store, "살아있는 대화")
    marked = await _conversation(store, "표시된 대화", project_id=project.id)

    assert await store.delete_conversation(
        USER, marked, product_scope=PRODUCT_SCOPE_CHAT
    )

    listed = [
        row["id"]
        for row in await store.list_conversations(USER, product_scope=PRODUCT_SCOPE_CHAT)
    ]
    assert marked not in listed
    assert live in listed

    hits = [
        row["id"]
        for row in await store.search_conversations(
            USER, "표시된", product_scope=PRODUCT_SCOPE_CHAT
        )
    ]
    assert marked not in hits
    live_hits = [
        row["id"]
        for row in await store.search_conversations(
            USER, "살아있는", product_scope=PRODUCT_SCOPE_CHAT
        )
    ]
    assert live_hits == [live]

    assert await store.list_project_conversations(
        USER, project.id, product_scope=PRODUCT_SCOPE_CHAT
    ) == []
    assert await store.get_conversation(
        USER, marked, product_scope=PRODUCT_SCOPE_CHAT
    ) is None
    assert await store.get_conversation_model_context(
        USER, marked, product_scope=PRODUCT_SCOPE_CHAT
    ) is None
    # A rename or a pin cannot reach a marked row either.
    assert await store.update_conversation(
        USER, marked, product_scope=PRODUCT_SCOPE_CHAT, title="새 이름"
    ) is None
    assert await store.update_conversation(
        USER, marked, product_scope=PRODUCT_SCOPE_CHAT, pinned=True
    ) is None

    # The untouched conversation keeps its content and its export path.
    context = await store.get_conversation_model_context(
        USER, live, product_scope=PRODUCT_SCOPE_CHAT
    )
    assert context is not None
    assert [message["role"] for message in context["messages"]] == ["user", "assistant"]


async def test_a_marked_conversation_is_as_absent_as_an_unknown_one(store):
    conversation = await _conversation(store)
    await store.delete_conversation(USER, conversation, product_scope=PRODUCT_SCOPE_CHAT)
    unknown = "chat_" + "0" * 32

    for candidate in (conversation, unknown):
        with pytest.raises(HistoryForbidden):
            await store.append_exchange(
                USER, candidate, "추가 질문", "답", None, product_scope=PRODUCT_SCOPE_CHAT,
            )
        with pytest.raises(HistoryForbidden):
            await store.record_txt_pending_run(
                user_id=USER, run_id="run_7388", workspace_id="ws_7388",
                user_text="텍스트", conversation_id=candidate,
            )
        assert await store.get_conversation(
            USER, candidate, product_scope=PRODUCT_SCOPE_CHAT
        ) is None
        assert await store.verify_owner_conversation_artifacts(USER, candidate) is False


async def test_delete_is_idempotent_and_keeps_the_first_deadline(store, connection):
    conversation = await _conversation(store)

    assert await store.delete_conversation(USER, conversation, product_scope=PRODUCT_SCOPE_CHAT)
    first = _scalar(
        connection, "SELECT deleted_at FROM conversations WHERE id=?", conversation
    )
    assert await store.delete_conversation(USER, conversation, product_scope=PRODUCT_SCOPE_CHAT)
    second = _scalar(
        connection, "SELECT deleted_at FROM conversations WHERE id=?", conversation
    )
    assert first == second
    assert await store.delete_conversation(
        USER, "chat_" + "f" * 32, product_scope=PRODUCT_SCOPE_CHAT
    ) is False


# ---------------------------------------------------------------------------
# 2. The daily pass: waits for the window, then removes all three copies.
# ---------------------------------------------------------------------------


async def test_purge_waits_for_the_window_then_removes_rows_and_originals(store, connection, bucket):
    conversation = await store.append_exchange(
        USER, None, "긴" * 9000, "답", None, product_scope=PRODUCT_SCOPE_CHAT,
    )
    preview = _scalar(
        connection,
        "SELECT content FROM messages WHERE conversation_id=? ORDER BY sequence_number LIMIT 1",
        conversation,
    )
    assert len(preview) == MAX_HISTORY_MESSAGE_CHARS
    assert preview.endswith(HISTORY_PREVIEW_SUFFIX)
    assert len(bucket.objects) == 1

    # 29 days: still inside the window, nothing is shed.
    connection.execute(
        "UPDATE conversations SET deleted_at=? WHERE id=?", (_stamp(29), conversation)
    )
    early = await purge_deleted_conversations(
        SqliteD1(connection), now=NOW, delete_full_keys=await _delete_keys(bucket),
    )
    assert early == {"conversations": 0, "messages": 0, "r2_keys": 0}
    assert len(bucket.objects) == 1

    # 31 days: messages, the row and the stored original go together.
    connection.execute(
        "UPDATE conversations SET deleted_at=? WHERE id=?", (_stamp(31), conversation)
    )
    late = await purge_deleted_conversations(
        SqliteD1(connection), now=NOW, delete_full_keys=await _delete_keys(bucket),
    )
    assert late == {"conversations": 1, "messages": 2, "r2_keys": 1}
    assert _scalar(
        connection, "SELECT COUNT(*) FROM conversations WHERE id=?", conversation
    ) == 0
    assert _scalar(
        connection, "SELECT COUNT(*) FROM messages WHERE conversation_id=?", conversation
    ) == 0
    assert bucket.objects == {}


async def test_purge_deletes_messages_without_a_foreign_key_pragma(store, connection):
    # The exact host condition that left the orphan rows this issue was filed on.
    connection.execute("PRAGMA foreign_keys = OFF")
    assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 0
    conversation = await _conversation(store)
    connection.execute(
        "UPDATE conversations SET deleted_at=? WHERE id=?", (_stamp(31), conversation)
    )

    counts = await purge_deleted_conversations(SqliteD1(connection), now=NOW)

    assert counts["messages"] == 2
    assert _scalar(
        connection, "SELECT COUNT(*) FROM messages WHERE conversation_id=?", conversation
    ) == 0


async def test_a_dry_run_counts_what_it_would_shed_and_deletes_nothing(store, connection, bucket):
    conversation = await _conversation(store)
    connection.execute(
        "UPDATE conversations SET deleted_at=? WHERE id=?", (_stamp(31), conversation)
    )

    counted = await purge_deleted_conversations(
        SqliteD1(connection), now=NOW, dry_run=True,
        delete_full_keys=await _delete_keys(bucket),
    )

    assert counted == {"conversations": 1, "messages": 2, "r2_keys": 0}
    assert _scalar(
        connection, "SELECT COUNT(*) FROM conversations WHERE id=?", conversation
    ) == 1
    assert _scalar(
        connection, "SELECT COUNT(*) FROM messages WHERE conversation_id=?", conversation
    ) == 2


async def test_a_failed_row_delete_rolls_the_conversation_back(store, connection):
    conversation = await _conversation(store)
    connection.execute(
        "UPDATE conversations SET deleted_at=? WHERE id=?", (_stamp(31), conversation)
    )
    connection.execute(
        "CREATE TRIGGER block_conversation_delete BEFORE DELETE ON conversations "
        "BEGIN SELECT RAISE(ABORT, 'blocked'); END"
    )

    with pytest.raises(sqlite3.Error):
        await purge_deleted_conversations(SqliteD1(connection), now=NOW)

    # The messages delete came first in the same transaction: it must be undone.
    assert _scalar(
        connection, "SELECT COUNT(*) FROM messages WHERE conversation_id=?", conversation
    ) == 2
    assert _scalar(
        connection, "SELECT COUNT(*) FROM conversations WHERE id=?", conversation
    ) == 1

    connection.execute("DROP TRIGGER block_conversation_delete")
    assert (await purge_deleted_conversations(SqliteD1(connection), now=NOW))["conversations"] == 1


async def test_purge_leaves_a_conversation_an_operator_just_restored(store, connection):
    conversation = await _conversation(store)
    connection.execute(
        "UPDATE conversations SET deleted_at=? WHERE id=?", (_stamp(5), conversation)
    )
    # A restore that lands before the pass runs keeps the row and its messages.
    assert restore_conversation(connection, conversation, now=NOW) == RESTORED

    counts = await purge_deleted_conversations(SqliteD1(connection), now=NOW)

    assert counts == {"conversations": 0, "messages": 0, "r2_keys": 0}
    assert _scalar(
        connection, "SELECT COUNT(*) FROM messages WHERE conversation_id=?", conversation
    ) == 2


async def test_purge_refuses_invalid_bounds(store, connection):
    with pytest.raises(ValueError):
        await purge_deleted_conversations(SqliteD1(connection), retention_days=-1, now=NOW)
    with pytest.raises(ValueError):
        await purge_deleted_conversations(SqliteD1(connection), batch_size=0, now=NOW)


async def test_purge_sheds_one_bounded_batch_per_run(store, connection):
    conversations = [await _conversation(store, f"대화 {index}") for index in range(3)]
    for index, conversation in enumerate(conversations):
        connection.execute(
            "UPDATE conversations SET deleted_at=? WHERE id=?",
            (_stamp(40 + index), conversation),
        )

    first = await purge_deleted_conversations(SqliteD1(connection), batch_size=2, now=NOW)
    assert first["conversations"] == 2
    assert _scalar(
        connection, "SELECT COUNT(*) FROM conversations WHERE deleted_at IS NOT NULL"
    ) == 1

    second = await purge_deleted_conversations(SqliteD1(connection), batch_size=2, now=NOW)
    assert second["conversations"] == 1


# ---------------------------------------------------------------------------
# 3. Operator restore: inside the window only, and never for a live row.
# ---------------------------------------------------------------------------


async def test_restore_clears_the_marker_only_inside_the_window(store, connection):
    conversation = await _conversation(store, "복구 대상")
    await store.delete_conversation(USER, conversation, product_scope=PRODUCT_SCOPE_CHAT)

    assert restore_conversation(connection, conversation, now=NOW) == RESTORED
    assert await store.get_conversation(
        USER, conversation, product_scope=PRODUCT_SCOPE_CHAT
    ) is not None
    assert restore_conversation(connection, conversation, now=NOW) == NOT_DELETED

    connection.execute(
        "UPDATE conversations SET deleted_at=? WHERE id=?", (_stamp(31), conversation)
    )
    assert restore_conversation(connection, conversation, now=NOW) == WINDOW_CLOSED
    assert restore_conversation(connection, "chat_" + "f" * 32, now=NOW) == NOT_FOUND

    with pytest.raises(ValueError):
        restore_conversation(connection, "not-a-conversation", now=NOW)


def test_the_ops_script_runs_the_restore_module():
    script = (REPO_ROOT / "ops" / "restore_conversation.sh").read_text(encoding="utf-8")
    assert "-m app.conversation_restore" in script
    assert "exec " in script


# ---------------------------------------------------------------------------
# 4. Retention knobs and the constants the purge shares with the store.
# ---------------------------------------------------------------------------


def test_the_retention_window_defaults_to_thirty_days():
    assert DEFAULT_RETENTION_DAYS == 30
    assert retention_days_from_env({}) == 30
    assert retention_days_from_env(
        {"PADIEM_CHAT_CONVERSATION_RETENTION_DAYS": "45"}
    ) == 45
    # Zero, negative and unparsable values fall back to the default rather than
    # deleting everything on the next tick.
    for raw in ("0", "-3", "x", ""):
        assert retention_days_from_env(
            {"PADIEM_CHAT_CONVERSATION_RETENTION_DAYS": raw}
        ) == 30


def test_the_purge_shares_the_store_preview_rule():
    assert conversation_purge.MAX_HISTORY_MESSAGE_CHARS == history_module.MAX_HISTORY_MESSAGE_CHARS
    assert conversation_purge.HISTORY_PREVIEW_SUFFIX == history_module.HISTORY_PREVIEW_SUFFIX


# ---------------------------------------------------------------------------
# 5. Static guards: the two ways this regresses are both refused here.
# ---------------------------------------------------------------------------


def _source_files():
    return sorted(path for path in APP_DIR.glob("*.py") if path.name != "__init__.py")


def test_every_conversation_read_carries_the_marker_condition():
    missing = []
    pattern = re.compile(r"\bFROM\s+conversations\b", re.IGNORECASE)
    for path in _source_files():
        if path.name in _MARKER_GUARD_ALLOWED:
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if pattern.search(line) is None:
                continue
            # Writes are the other guard's business; this one is about reads.
            if re.search(r"\b(?:DELETE|UPDATE|INSERT)\b", line, re.IGNORECASE):
                continue
            window = "\n".join(lines[index:index + 6])
            if "deleted_at" not in window:
                missing.append(f"{path.name}:{index + 1}")
    assert missing == []


def test_no_conversation_delete_skips_its_messages():
    missing = []
    for path in _source_files():
        if path.name in _DELETE_GUARD_ALLOWED:
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if "DELETE FROM conversations" not in line:
                continue
            start = max(0, index - 8)
            window = "\n".join(lines[start:index + 9])
            if "DELETE FROM messages" not in window:
                missing.append(f"{path.name}:{index + 1}")
    assert missing == []


async def test_account_deletion_still_deletes_a_marked_conversation_now(store, connection):
    from app import account_deletion

    conversation = await _conversation(store)
    await store.delete_conversation(USER, conversation, product_scope=PRODUCT_SCOPE_CHAT)

    statements = account_deletion._delete_batch(
        SqliteD1(connection), USER, include_pc_queue_data=False, bookai_subjects=(),
    )
    await SqliteD1(connection).batch(statements)

    assert _scalar(
        connection, "SELECT COUNT(*) FROM conversations WHERE user_id=?", USER
    ) == 0
    assert _scalar(
        connection, "SELECT COUNT(*) FROM messages WHERE conversation_id=?", conversation
    ) == 0
    assert _scalar(connection, "SELECT COUNT(*) FROM users WHERE id=?", USER) == 0
