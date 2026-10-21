"""#4379: the D1 metadata ceiling is released by a forward migration, not rewritten.

The three released migrations (008, 026, 027) each declared a 10 MiB upper bound
on a byte-length column. That bound was a PADIEM product total, not a platform or
Provider limit, so 060 rebuilds the tables without it. These guards run the real
migration SQL: the bound must have been live before 060, every row must survive
the rebuild, and the non-empty rule plus every other constraint must remain.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
FORWARD = "060_byte_length_capacity_ceiling_release.sql"
USER = "usr_" + "a" * 32
CHAT = "chat_" + "c" * 32
RUN = "run_" + "e" * 24
HASH = "a" * 64
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
OVER_OLD_CEILING = 11 * 1024 * 1024

TEMPLATE = (
    "INSERT INTO b66_template_source (id,user_id,workspace_id,media_type,original_filename,"
    "object_key,byte_length,sha256,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)"
)
DOCUMENT = (
    "INSERT INTO claw_document_metadata (document_id,tenant_id,object_key,filename,media_type,"
    "byte_length,created_at,expires_at,deleted_at) VALUES (?,?,?,?,?,?,?,?,NULL)"
)
ARTIFACT = (
    "INSERT INTO claw_conversation_artifact_index (artifact_id,user_id,conversation_id,"
    "workspace_ref,source_run_ref,filename,media_type,size_bytes,integrity_ref,location_kind,"
    "location_ref,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
)


def template_row(row_id="t_1", *, byte_length=7, object_key=None):
    return (row_id, USER, "ws", "application/pdf", "form.pdf",
            object_key or f"key/{row_id}", byte_length, HASH, "uploaded",
            "2026-01-01", "2026-01-01")


def document_row(row_id="d_1", *, byte_length=7):
    return (row_id, "tenant", f"key/{row_id}", "quote.docx", DOCX,
            byte_length, "2026-01-01", "2026-01-02")


def artifact_row(row_id="a_1", *, size_bytes=7, integrity_ref=None):
    return (row_id, USER, CHAT, "ws", RUN, "quote.xlsx", XLSX, size_bytes,
            HASH if integrity_ref is None else integrity_ref, "r2", f"key/{row_id}",
            "2026-01-01")


def database(*, with_forward: bool) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    for path in sorted(MIGRATIONS.glob("*.sql")):
        if path.name == FORWARD and not with_forward:
            continue
        conn.executescript(path.read_text(encoding="utf-8"))
    # 027 turns foreign keys on for the rest of the connection.
    conn.execute(
        "INSERT INTO users (id,auth_provider,provider_subject,email,created_at,updated_at) "
        "VALUES (?,'google','subject','owner@example.test','2026-01-01','2026-01-01')",
        (USER,),
    )
    conn.execute(
        "INSERT INTO conversations (id,user_id,title,created_at,updated_at) "
        "VALUES (?,?,'title','2026-01-01','2026-01-01')",
        (CHAT, USER),
    )
    conn.execute(
        "INSERT INTO claw_run_history (id,user_id,run_id,channel,action,title,status,"
        "created_at,updated_at,conversation_id,workspace_id) "
        "VALUES ('rh',?,?,'telegram','run','title','completed',"
        "'2026-01-01','2026-01-01',?,'ws')",
        (USER, RUN, CHAT),
    )
    return conn


def refused(conn, sql, values) -> str:
    try:
        conn.execute(sql, values)
    except sqlite3.IntegrityError as exc:
        return str(exc)
    return ""


def test_the_released_schema_did_refuse_a_row_over_the_old_ceiling() -> None:
    conn = database(with_forward=False)
    try:
        for sql, values, column in (
            (TEMPLATE, template_row(byte_length=OVER_OLD_CEILING), "byte_length"),
            (DOCUMENT, document_row(byte_length=OVER_OLD_CEILING), "byte_length"),
            (ARTIFACT, artifact_row(size_bytes=OVER_OLD_CEILING), "size_bytes"),
        ):
            error = refused(conn, sql, values)
            assert "CHECK constraint failed" in error, column
            assert f"{column} <= 10485760" in error, column
    finally:
        conn.close()


def test_the_forward_migration_carries_every_row_and_keeps_the_floor() -> None:
    conn = database(with_forward=False)
    try:
        conn.execute(TEMPLATE, template_row("t_keep", byte_length=9 * 1024 * 1024))
        conn.execute(DOCUMENT, document_row("d_keep", byte_length=42))
        conn.execute(ARTIFACT, artifact_row("a_keep", size_bytes=120))

        conn.executescript((MIGRATIONS / FORWARD).read_text(encoding="utf-8"))

        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%_next'"
        )] == []
        assert tuple(conn.execute(
            "SELECT id, byte_length, sha256 FROM b66_template_source").fetchone()) == (
                "t_keep", 9 * 1024 * 1024, HASH)
        assert tuple(conn.execute(
            "SELECT document_id, byte_length FROM claw_document_metadata").fetchone()) == (
                "d_keep", 42)
        assert tuple(conn.execute(
            "SELECT artifact_id, size_bytes FROM claw_conversation_artifact_index").fetchone()) == (
                "a_keep", 120)
        names = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
        for index in (
            "idx_claw_document_metadata_tenant_active",
            "idx_claw_conversation_artifact_owner",
            "idx_b66_template_source_owner_workspace_status",
        ):
            assert index in names, index

        # Every column is still there, so the rebuild copied rather than narrowed.
        for table, expected in (
            ("claw_document_metadata", 9),
            ("claw_conversation_artifact_index", 13),
            ("b66_template_source", 11),
        ):
            assert len(conn.execute(f"PRAGMA table_info({table})").fetchall()) == expected, table

        assert refused(conn, TEMPLATE, template_row("t_zero", byte_length=0))
        assert refused(conn, DOCUMENT, document_row("d_zero", byte_length=0))
        assert refused(conn, ARTIFACT, artifact_row("a_zero", size_bytes=0))
        for sql, values in (
            (TEMPLATE, template_row("t_big", byte_length=OVER_OLD_CEILING)),
            (DOCUMENT, document_row("d_big", byte_length=OVER_OLD_CEILING)),
            (ARTIFACT, artifact_row("a_big", size_bytes=OVER_OLD_CEILING)),
        ):
            assert refused(conn, sql, values) == ""
    finally:
        conn.close()


def test_the_forward_migration_keeps_the_unrelated_row_constraints() -> None:
    conn = database(with_forward=True)
    try:
        certified = template_row("t_status")[:8] + ("certified",) + template_row("t_status")[9:]
        assert "CHECK constraint failed" in refused(conn, TEMPLATE, certified)
        assert "CHECK constraint failed" in refused(
            conn, ARTIFACT, artifact_row("a_short", integrity_ref="short"))
        conn.execute(TEMPLATE, template_row("t_existing", object_key="key/t_1"))
        assert "UNIQUE constraint failed" in refused(
            conn, TEMPLATE, template_row("t_dup", object_key="key/t_1"))
        unknown_owner = template_row("t_owner")[:1] + ("usr_missing",) + template_row("t_owner")[2:]
        assert "FOREIGN KEY constraint failed" in refused(conn, TEMPLATE, unknown_owner)
    finally:
        conn.close()


def test_a_fresh_database_replays_every_migration_in_order() -> None:
    conn = database(with_forward=True)
    try:
        assert conn.execute(
            "SELECT SQL FROM sqlite_master WHERE name='b66_template_source'").fetchone()[0].count(
                "10485760") == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name IN "
            "('claw_document_metadata','claw_conversation_artifact_index','b66_template_source')"
        ).fetchone()[0] == 3
    finally:
        conn.close()
