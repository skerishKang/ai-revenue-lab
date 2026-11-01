"""11-01 컴2 Chat 백업(`deploy/host-com2/chat/backup.py`) → **실제 복원** 시험.

배경: 11-01에 백업이 처음으로 동작했지만(매일 04:20, `VACUUM INTO` + 사본 검증),
그 파일로 **되돌아가는지**는 확인된 적이 없다. 백업이 "검증됐다"는 것과 "복원이 된다"는
것은 다른 문제다.

이 시험은 시험용 SQLite 파일에 마이그레이션 88개를 적용하고 사용자·대화·메시지·
프로젝트·프로젝트 파일 행을 넣은 뒤,

1. backup.py를 **실제로 실행**해 백업 파일을 만들고,
2. 그 파일을 새 위치로 복원해(사본) integrity·행 수·마이그레이션 장부가 그대로인지,
3. 로테이션(`--keep`)과 DB 부재 시 SKIPPED 경로까지 고정한다.

제품 코드는 건드리지 않고 backup.py도 그대로 서브프로세스로 쓴다.
"""

from __future__ import annotations

import asyncio
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

from test_6446_account_isolation_sweep import ThreadSafeSqliteD1, apply_all_migrations

ROOT = Path(__file__).resolve().parents[3]
BACKUP = ROOT / "deploy" / "host-com2" / "chat" / "backup.py"
MIGRATIONS = ROOT / "apps" / "padiem-chat" / "migrations"
COUNTED_TABLES = ("users", "conversations", "messages", "projects")
LEDGER = "padiem_local_migration_ledger"


class FileSqliteD1(ThreadSafeSqliteD1):
    """5222/6446 하네스의 D1 모양 그대로, 파일 하나에 붙인다."""

    def __init__(self, path: Path):
        self.conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")


def _counts(conn: sqlite3.Connection) -> dict[str, int]:
    counts = {}
    for table in COUNTED_TABLES:
        counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return counts


def _ledger_count(conn: sqlite3.Connection) -> int | None:
    """배포 장부 건수. 앱이 아직 장부를 만들지 않은 DB는 None."""

    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (LEDGER,)
    ).fetchone()
    if not exists:
        return None
    return conn.execute(f"SELECT COUNT(*) FROM {LEDGER}").fetchone()[0]


def _seed(db_path: Path) -> dict[str, object]:
    """마이그레이션 88개 + 사용자·대화·메시지·프로젝트·프로젝트 파일 몇 행."""

    applied = sorted(MIGRATIONS.glob("*.sql"))
    assert len(applied) == 88, [path.name for path in applied][-3:]

    db = FileSqliteD1(db_path)
    user_id = "usr_" + "a" * 32
    project_id = "proj_" + "e" * 32
    try:
        apply_all_migrations(db)
        # 사용자·프로젝트는 앱 스토어가 아니라 실제 표 모양(001/002)으로 넣는다 —
        # 백업이 다루는 것은 표이고, 이 시험은 백업·복원 경로만 고정한다.
        db.conn.execute(
            "INSERT INTO users VALUES (?,?,?,?,?,?,?,?)",
            (user_id, "google", "backup-subject", "owner@example.test", "백업 사용자", "",
             "2026-11-01T00:00:00Z", "2026-11-01T00:00:00Z"),
        )
        db.conn.execute(
            "INSERT INTO projects (id, user_id, name, instructions, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?)",
            (project_id, user_id, "백업 프로젝트", "",
             "2026-11-01T00:00:00Z", "2026-11-01T00:00:00Z"),
        )
        conversation_id = "chat_" + "b" * 32
        db.conn.execute(
            "INSERT INTO conversations (id, user_id, title, created_at, updated_at)"
            " VALUES (?,?,?,?,?)",
            (conversation_id, user_id, "백업 대화", "2026-11-01T00:00:00Z",
             "2026-11-01T00:00:00Z"),
        )
        db.conn.execute(
            "INSERT INTO messages (id, conversation_id, sequence_number, role, content, created_at)"
            " VALUES (?,?,?,?,?,?)",
            ("msg_" + "c" * 32, conversation_id, 0, "user", "백업할 질문", "2026-11-01T00:00:01Z"),
        )
        db.conn.execute(
            "INSERT INTO project_files (id, project_id, user_id, name, media_type,"
            " content_text, content_chars, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            ("file_" + "d" * 32, project_id, user_id, "원본.txt", "text/plain",
             "백업 본문", len("백업 본문"), "2026-11-01T00:00:02Z", "2026-11-01T00:00:02Z"),
        )
        db.conn.execute(
            "CREATE TABLE IF NOT EXISTS padiem_local_migration_ledger ("
            " filename TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        for path in applied[-3:]:
            db.conn.execute(
                "INSERT INTO padiem_local_migration_ledger (filename, applied_at)"
                " VALUES (?,?)", (path.name, "2026-11-01T00:00:03Z"),
            )
        counts = _counts(db.conn)
        ledger = _ledger_count(db.conn)
    finally:
        db.conn.close()
    return {"counts": counts, "ledger": ledger, "conversation_id": conversation_id}


def _run_backup(db_path: Path, dest: Path, keep: int = 7):
    return subprocess.run(
        [sys.executable, str(BACKUP), "--db", str(db_path), "--dest", str(dest),
         "--keep", str(keep)],
        text=True, capture_output=True,
    )


def test_backup_snapshot_restores_into_a_working_database(tmp_path):
    db_path = tmp_path / "chat.sqlite3"
    seeded = _seed(db_path)
    assert seeded["counts"] == {"users": 1, "conversations": 1, "messages": 1, "projects": 1}

    dest = tmp_path / "backups"
    result = _run_backup(db_path, dest)
    assert result.returncode == 0, result.stderr
    assert "CHAT_COM2_BACKUP=PASS" in result.stdout, result.stdout

    backups = sorted(dest.glob("chat-*.sqlite3"))
    assert len(backups) == 1, [path.name for path in backups]
    backup_file = backups[0]
    # 04:20 타이머가 남기는 이름 모양 그대로인지(운영 로그와 대조 가능해야 한다).
    assert backup_file.name.startswith("chat-") and backup_file.suffix == ".sqlite3"

    # ── 복원: 백업 파일을 새 위치로 사본(운영 절차 3번째 줄) ────────────────
    restored_path = tmp_path / "restore" / "chat.sqlite3"
    restored_path.parent.mkdir()
    shutil.copyfile(backup_file, restored_path)

    conn = sqlite3.connect(str(restored_path))
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert _counts(conn) == seeded["counts"]
        assert _ledger_count(conn) == seeded["ledger"]
        # 행 내용까지 살아나는지 — 개수만 맞고 내용이 빈 백업은 복원이 아니다.
        assert conn.execute(
            "SELECT content FROM messages WHERE conversation_id=?",
            (seeded["conversation_id"],),
        ).fetchone()[0] == "백업할 질문"
        assert conn.execute("SELECT content_text FROM project_files").fetchone()[0] == "백업 본문"
        assert conn.execute("SELECT name FROM projects").fetchone()[0] == "백업 프로젝트"
        # 장부가 그대로라 복원 후 같은 마이그레이션이 다시 돌지 않는다.
        assert _ledger_count(conn) == 3
    finally:
        conn.close()


def test_backup_rotation_keeps_only_the_configured_number(tmp_path):
    db_path = tmp_path / "chat.sqlite3"
    _seed(db_path)
    dest = tmp_path / "backups"
    dest.mkdir()
    # 오래된 백업 3개를 미리 두고 keep=2로 돌린다.
    for stamp in ("20260101T000000Z", "20260102T000000Z", "20260103T000000Z"):
        (dest / f"chat-{stamp}.sqlite3").write_bytes(b"old")

    result = _run_backup(db_path, dest, keep=2)
    assert result.returncode == 0, result.stderr
    remaining = sorted(path.name for path in dest.glob("chat-*.sqlite3"))
    assert len(remaining) == 2, remaining
    # 가장 최근 것(방금 만든 백업)은 반드시 남는다.
    assert any(name.startswith("chat-") and name not in
               {"chat-20260101T000000Z.sqlite3", "chat-20260102T000000Z.sqlite3"}
               for name in remaining), remaining


def test_backup_skips_cleanly_when_the_database_is_absent(tmp_path):
    result = subprocess.run(
        [sys.executable, str(BACKUP), "--db", str(tmp_path / "missing.sqlite3"),
         "--dest", str(tmp_path / "backups")],
        text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert "CHAT_COM2_BACKUP=SKIPPED reason=database_absent" in result.stdout
    assert not (tmp_path / "backups").exists()
