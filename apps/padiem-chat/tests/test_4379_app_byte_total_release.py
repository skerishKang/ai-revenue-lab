"""#4379: the D1 metadata surfaces carry no PADIEM byte total.

Migration 060 released the 10 MiB upper bound that 008, 026 and 027 declared
on their byte-length columns. The application side still imposed the same
product total on the same surfaces, so this slice removes it there too and
releases the B66 quote asset ceiling on both sides at once: the app constant
and the D1 CHECK move together, because releasing one side alone would turn a
clean rejection into a database failure.

Every real control stays: the empty payload, the media-type magic, the
container proof, the metadata non-empty rule, the integrity digest and the
owner scope. The sqlite rehearsal below runs the real forward migration.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
APP = Path(__file__).resolve().parents[1] / "app"
STATIC = Path(__file__).resolve().parents[1] / "static"
FORWARD = "061_b66_quote_asset_byte_length_ceiling_release.sql"
USER = "usr_" + "a" * 32
OVER_OLD_CEILING = 11 * 1024 * 1024
OVER_QUOTE_CEILING = 256 * 1024 + 1

ASSET = (
    "INSERT INTO b66_quote_asset (id,user_id,workspace_id,asset_kind,media_type,"
    "object_key,byte_length,sha256,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)"
)


def database(*, with_forward: bool) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    for path in sorted(MIGRATIONS.glob("*.sql")):
        if path.name == FORWARD and not with_forward:
            continue
        conn.executescript(path.read_text(encoding="utf-8"))
    conn.execute(
        "INSERT INTO users (id,auth_provider,provider_subject,email,created_at,updated_at) "
        "VALUES (?,'google','subject','owner@example.test','2026-01-01','2026-01-01')",
        (USER,),
    )
    return conn


def asset_row(row_id="a_1", *, byte_length=7, object_key=None):
    return (row_id, USER, "ws", "logo", "image/png", object_key or f"key/{row_id}",
            byte_length, "a" * 64, "approved", "2026-01-01", "2026-01-01")


def refused(conn, sql, values) -> str:
    try:
        conn.execute(sql, values)
    except sqlite3.IntegrityError as exc:
        return str(exc)
    return ""


def test_no_application_byte_total_remains_on_the_released_d1_surfaces() -> None:
    # The app twins of the released D1 CHECK are gone, so the only remaining
    # bound on these surfaces is the platform and provider limit.
    for name in (
        "workspace_storage.py",
        "claw_durable_drive_artifact_routes.py",
        "claw_artifact_preview_routes.py",
    ):
        text = (APP / name).read_text(encoding="utf-8")
        # #5573 keeps generic D1 metadata free of byte ceilings. The separately
        # authorized WEB XLSX input limit is now 1GiB and is not that surface.
        if name == "workspace_storage.py":
            text = "\n".join(line for line in text.splitlines()
                             if not line.startswith("MAX_WEB_XLSX_BYTES = "))
        assert "10 * 1024 * 1024" not in text, name
        assert "10485760" not in text, name
        assert "SINGLE_FILE_MAX_BYTES" not in text, name
        assert "_MAX_BYTES" not in text, name
        assert "_MAX_PDF" not in text, name

    preview = (STATIC / "claw-pdf-preview.js").read_text(encoding="utf-8")
    assert "MAX_PDF" not in preview
    assert "10 * 1024 * 1024" not in preview


def test_the_real_controls_survive_the_release() -> None:
    storage = (APP / "workspace_storage.py").read_text(encoding="utf-8")
    assert storage.count("if not payload:") == 1

    drive = (APP / "claw_durable_drive_artifact_routes.py").read_text(encoding="utf-8")
    assert "len(data) != record.size_bytes" in drive
    assert "hashlib.sha256(data).hexdigest() != record.integrity_ref" in drive
    assert 'not data.startswith(b"%PDF-")' in drive
    assert 'not data.startswith(b"PK' in drive

    preview = (APP / "claw_artifact_preview_routes.py").read_text(encoding="utf-8")
    assert "len(content) < 8" in preview
    assert 'not content.startswith(b"%PDF-")' in preview
    assert 'b"%%EOF" not in content[-1024:]' in preview

    quote = (APP / "b66_quote_assets.py").read_text(encoding="utf-8")
    assert quote.count("if not body:") == 1
    assert quote.count("if not _magic_matches(media_type, body):") == 1
    assert quote.count("or meta.byte_length < 1") == 1
    assert "MAX_B66_QUOTE_ASSET_BYTES" not in quote


def test_the_released_schema_did_refuse_a_quote_asset_over_the_old_ceiling() -> None:
    conn = database(with_forward=False)
    try:
        error = refused(conn, ASSET, asset_row(byte_length=OVER_QUOTE_CEILING))
        assert "CHECK constraint failed" in error
        assert "byte_length <= 262144" in error
    finally:
        conn.close()


def test_the_forward_migration_carries_every_row_and_keeps_the_floor() -> None:
    conn = database(with_forward=False)
    try:
        conn.execute(ASSET, asset_row("a_keep", byte_length=9 * 1024))

        conn.executescript((MIGRATIONS / FORWARD).read_text(encoding="utf-8"))

        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%_next'"
        )] == []
        assert tuple(conn.execute(
            "SELECT id, byte_length, sha256, status FROM b66_quote_asset").fetchone()) == (
                "a_keep", 9 * 1024, "a" * 64, "approved")
        names = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
        assert "idx_b66_quote_asset_owner_workspace_status" in names

        # Every column is still there, so the rebuild copied rather than narrowed.
        assert len(conn.execute("PRAGMA table_info(b66_quote_asset)").fetchall()) == 11

        assert refused(conn, ASSET, asset_row("a_zero", byte_length=0))
        assert refused(conn, ASSET, asset_row("a_big", byte_length=OVER_QUOTE_CEILING)) == ""
    finally:
        conn.close()


def test_the_forward_migration_keeps_the_unrelated_row_constraints() -> None:
    conn = database(with_forward=True)
    try:
        assert "CHECK constraint failed" in refused(
            conn, ASSET, asset_row("a_kind", )[:3] + ("mark",) + asset_row("a_kind")[4:])
        assert "CHECK constraint failed" in refused(
            conn, ASSET, asset_row("a_media")[:4] + ("image/gif",) + asset_row("a_media")[5:])
        assert "CHECK constraint failed" in refused(
            conn, ASSET, asset_row("a_status")[:8] + ("pending",) + asset_row("a_status")[9:])
        conn.execute(ASSET, asset_row("a_existing", object_key="key/a_1"))
        assert "UNIQUE constraint failed" in refused(
            conn, ASSET, asset_row("a_dup", object_key="key/a_1"))
        unknown_owner = asset_row("a_owner")[:1] + ("usr_missing",) + asset_row("a_owner")[2:]
        assert "FOREIGN KEY constraint failed" in refused(conn, ASSET, unknown_owner)
    finally:
        conn.close()


def test_a_fresh_database_replays_every_migration_in_order() -> None:
    conn = database(with_forward=True)
    try:
        table_sql = conn.execute(
            "SELECT SQL FROM sqlite_master WHERE name='b66_quote_asset'").fetchone()[0]
        assert "262144" not in table_sql
        assert "byte_length >= 1" in table_sql
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name = 'b66_quote_asset'"
        ).fetchone()[0] == 1
    finally:
        conn.close()
