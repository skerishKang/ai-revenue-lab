"""Synthetic tests for the staging database builder.

No Production D1, no COM2 database and no real generation: every case builds a
tiny generation folder, pointer file and migration set in a temp directory.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import sqlite3
import stat
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

staging = importlib.import_module("chat_staging_db_from_generation")

GENERATION = "20261031T042000123456Z"
MIGRATIONS = ("001_auth_history.sql", "002_projects.sql", "003_project_files.sql")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _migrations(root: Path, names: tuple[str, ...] = MIGRATIONS) -> Path:
    directory = root / "migrations"
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_text("SELECT 1;\n", encoding="utf-8")
    return directory


def _generation_db(
    root: Path,
    *,
    ledger: tuple[str, ...] = MIGRATIONS,
    extra_ledger: tuple[str, ...] = (),
    generation: str = GENERATION,
    label_db: str = "chat.sqlite3",
) -> Path:
    folder = root / "generations" / generation
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / label_db
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE users (id TEXT PRIMARY KEY, name TEXT, note TEXT);
        CREATE TABLE conversations (id TEXT PRIMARY KEY, user_id TEXT, title TEXT);
        CREATE TABLE oracle_mesh_dispatch (id TEXT PRIMARY KEY, state TEXT);
        CREATE TABLE pc_pairing_codes (code TEXT PRIMARY KEY, device TEXT);
        CREATE TABLE local_agent_broker_state (id TEXT PRIMARY KEY, payload TEXT);
        CREATE TABLE local_agent_command_material (id TEXT PRIMARY KEY, body TEXT);
        CREATE TABLE audit_lines (message TEXT);
        CREATE TABLE d1_migrations (id INTEGER PRIMARY KEY, name TEXT, applied_at TEXT);
        """
    )
    rows = [
        ("users", ("u1", "김민수", "note-1")),
        ("users", ("u2", "이영희", "note-2")),
        ("users", ("u3", "박철수", "note-3")),
        ("conversations", ("c1", "u1", "첫 대화")),
        ("conversations", ("c2", "u2", "둘째 대화")),
        ("oracle_mesh_dispatch", ("d1", "queued")),
        ("oracle_mesh_dispatch", ("d2", "done")),
        ("pc_pairing_codes", ("123456", "device-a")),
        ("local_agent_broker_state", ("b1", "state")),
        ("local_agent_command_material", ("m1", "material")),
        ("audit_lines", ("line-1",)),
        ("audit_lines", ("line-2",)),
    ]
    for table, values in rows:
        placeholders = ", ".join("?" for _ in values)
        connection.execute(f'INSERT INTO "{table}" VALUES ({placeholders})', values)
    for index, name in enumerate(ledger, start=1):
        connection.execute(
            "INSERT INTO d1_migrations (id, name, applied_at) VALUES (?, ?, ?)",
            (index, name, "2026-10-30T00:00:00Z"),
        )
    for index, name in enumerate(extra_ledger, start=100):
        connection.execute(
            "INSERT INTO d1_migrations (id, name, applied_at) VALUES (?, ?, ?)",
            (index, name, "2026-10-30T00:00:00Z"),
        )
    connection.commit()
    connection.close()
    return path


def _pointer(root: Path, *, generation: str = GENERATION, databases=None) -> Path:
    snapshots = root / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    path = snapshots / "current_generation.json"
    payload = {
        "generation": generation,
        "databases": (
            databases
            if databases is not None
            else {"chat": {"tables": 8}, "engine": {"tables": 5}}
        ),
        "captured_utc": generation,
        "production_bound": False,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _lines(capsys: pytest.CaptureFixture[str]) -> str:
    return capsys.readouterr().out


def _run(root: Path, out: Path, *extra: str):
    argv = [
        "--pointer", str(_pointer(root)),
        "--generations-dir", str(root / "generations"),
        "--out", str(out),
        "--migrations-dir", str(_migrations(root)),
        *extra,
    ]
    return staging.main(argv)


def test_ready_copy_matches_generation_and_empties_owned_tables(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "sync"
    source = _generation_db(root)
    source_sha = _sha(source)
    out = tmp_path / "staging" / "chat.sqlite3"

    assert _run(root, out) == 0
    printed = _lines(capsys)

    assert "STAGING_DB_FROM_GENERATION=READY" in printed
    assert "CHAT_COPY_PARITY=MATCH" in printed
    assert "STAGING_DB_LEDGER applied=3/3 missing=0 unknown=0" in printed
    assert "STAGING_DB_SOURCE_UNCHANGED=YES" in printed
    assert "CHAT_COPY_PARITY_SUMMARY=2표 5행 불일치 0" in printed
    assert _sha(source) == source_sha

    created = sqlite3.connect(out)
    try:
        assert created.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 3
        # A table without a primary key is copied but cannot be compared; the
        # parity verdict covers the comparable tables and does not abort.
        assert created.execute("SELECT COUNT(*) FROM audit_lines").fetchone()[0] == 2
        # Another authority's tables travel as empty state, not as data.
        for table in (
            "oracle_mesh_dispatch",
            "pc_pairing_codes",
            "local_agent_broker_state",
            "local_agent_command_material",
        ):
            assert created.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] == 0
        ledger = {
            row[0]
            for row in created.execute(
                "SELECT name FROM padiem_local_migration_ledger"
            )
        }
        # The local host sees the copied schema as migrated: zero replays.
        assert ledger == set(MIGRATIONS)
        assert created.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    finally:
        created.close()
    assert not out.with_name(out.name + "-wal").exists()


def test_generation_rows_stay_untouched(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "sync"
    source = _generation_db(root)
    assert _run(root, tmp_path / "staging.sqlite3") == 0
    _lines(capsys)

    connection = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    try:
        assert connection.execute("SELECT COUNT(*) FROM oracle_mesh_dispatch").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 3
    finally:
        connection.close()


def test_incomplete_ledger_refuses_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "sync"
    _generation_db(root, ledger=MIGRATIONS[:2])
    out = tmp_path / "staging.sqlite3"

    assert _run(root, out) == 1
    assert "STAGING_DB_REFUSED reason=staging_ledger_incomplete" in _lines(capsys)
    assert not out.exists()


def test_unknown_ledger_entry_refuses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "sync"
    _generation_db(root, extra_ledger=("080_not_in_repo.sql",))
    out = tmp_path / "staging.sqlite3"

    assert _run(root, out) == 1
    assert "STAGING_DB_REFUSED reason=staging_ledger_unknown" in _lines(capsys)
    assert not out.exists()


def test_missing_ledger_table_refuses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "sync"
    source = _generation_db(root)
    connection = sqlite3.connect(source)
    connection.execute("DROP TABLE d1_migrations")
    connection.commit()
    connection.close()

    out = tmp_path / "staging.sqlite3"
    assert _run(root, out) == 1
    assert "STAGING_DB_REFUSED reason=staging_ledger_table_missing" in _lines(capsys)
    assert not out.exists()


def test_missing_pointer_is_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "sync"
    _generation_db(root)
    out = tmp_path / "staging.sqlite3"

    assert staging.main(
        [
            "--pointer", str(root / "snapshots" / "current_generation.json"),
            "--generations-dir", str(root / "generations"),
            "--out", str(out),
            "--migrations-dir", str(_migrations(root)),
        ]
    ) == 2
    assert "STAGING_DB_REFUSED reason=staging_pointer_missing" in _lines(capsys)


def test_missing_generation_folder_is_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "sync"
    _generation_db(root)
    pointer = _pointer(root, generation="20260101T000000000000Z")

    assert staging.main(
        [
            "--pointer", str(pointer),
            "--generations-dir", str(root / "generations"),
            "--out", str(tmp_path / "staging.sqlite3"),
            "--migrations-dir", str(_migrations(root)),
        ]
    ) == 2
    assert "STAGING_DB_REFUSED reason=staging_generation_missing" in _lines(capsys)


def test_pointer_without_requested_label_is_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "sync"
    _generation_db(root)
    pointer = _pointer(root, databases={"engine": {"tables": 5}})

    assert staging.main(
        [
            "--pointer", str(pointer),
            "--generations-dir", str(root / "generations"),
            "--out", str(tmp_path / "staging.sqlite3"),
            "--migrations-dir", str(_migrations(root)),
        ]
    ) == 2
    assert "STAGING_DB_REFUSED reason=staging_label_missing" in _lines(capsys)


def test_existing_output_needs_force(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "sync"
    _generation_db(root)
    out = tmp_path / "staging.sqlite3"
    out.write_text("sentinel", encoding="utf-8")

    assert _run(root, out) == 2
    assert "STAGING_DB_REFUSED reason=staging_out_exists" in _lines(capsys)
    assert out.read_text(encoding="utf-8") == "sentinel"

    assert _run(root, out, "--force") == 0
    assert "STAGING_DB_FROM_GENERATION=READY" in _lines(capsys)
    connection = sqlite3.connect(out)
    try:
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 3
    finally:
        connection.close()


def test_output_inside_generation_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "sync"
    _generation_db(root)
    out = root / "generations" / GENERATION / "staging.sqlite3"

    assert _run(root, out) == 2
    assert "STAGING_DB_REFUSED reason=staging_out_inside_generations" in _lines(capsys)
    assert not out.exists()


def test_json_report_carries_counts_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "sync"
    _generation_db(root)
    report_path = tmp_path / "report.json"

    assert _run(root, tmp_path / "staging.sqlite3", "--json", str(report_path)) == 0
    _lines(capsys)
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    assert payload["ready"] is True
    assert payload["parity_exit"] == 0
    assert payload["ledger_applied"] == 3
    assert payload["local_ledger_rows"] == 3
    assert payload["source_unchanged"] is True
    assert payload["emptied_tables"]["oracle_mesh_dispatch"] == 2
    text = report_path.read_text(encoding="utf-8")
    for content in ("김민수", "이영희", "note-1", "첫 대화"):
        assert content not in text


def test_digest_implementation_is_shared(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The builder must not grow a second idea of what a row is."""

    assert _run(tmp_path / "unused", tmp_path / "x.sqlite3") in {1, 2}
    _lines(capsys)

    parity = importlib.import_module("chat_copy_parity")
    digest = importlib.import_module("chat_d1_digest")
    assert staging.digest is digest
    assert staging.parity is parity
    assert parity.digest is digest


def _run_with_migrations(
    root: Path, out: Path, migrations: Path, *extra: str
) -> int:
    return staging.main(
        [
            "--pointer", str(_pointer(root)),
            "--generations-dir", str(root / "generations"),
            "--out", str(out),
            "--migrations-dir", str(migrations),
            *extra,
        ]
    )


def test_a_pending_tail_is_applied_after_the_parity_verdict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The 2026-10-31 case: the generation stops at 078, the repo has 079."""

    root = tmp_path / "sync"
    source = _generation_db(root, ledger=MIGRATIONS[:2])
    source_sha = _sha(source)
    out = tmp_path / "staging" / "chat.sqlite3"

    assert _run(root, out, "--apply-pending") == 0
    printed = _lines(capsys)

    assert "STAGING_DB_PENDING_APPLIED count=1" in printed
    assert "names=003_project_files.sql" in printed
    assert "STAGING_DB_FROM_GENERATION=READY" in printed
    assert "STAGING_DB_SOURCE_UNCHANGED=YES" in printed
    # The copy matched the generation before it was advanced.
    assert printed.index("CHAT_COPY_PARITY=MATCH") < printed.index(
        "STAGING_DB_PENDING_APPLIED"
    )
    assert _sha(source) == source_sha

    created = sqlite3.connect(out)
    try:
        d1 = {row[0] for row in created.execute("SELECT name FROM d1_migrations")}
        local = {
            row[0]
            for row in created.execute("SELECT name FROM padiem_local_migration_ledger")
        }
        assert d1 == set(MIGRATIONS)
        assert local == set(MIGRATIONS)
        assert created.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 3
    finally:
        created.close()


def test_the_pending_migration_sql_really_runs_on_the_copy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "sync"
    _generation_db(root, ledger=MIGRATIONS[:2])
    migrations = _migrations(root, MIGRATIONS[:2])
    (migrations / "003_project_files.sql").write_text(
        "CREATE TABLE staging_probe (id TEXT PRIMARY KEY);\n"
        "INSERT INTO staging_probe VALUES ('ok');\n",
        encoding="utf-8",
    )
    out = tmp_path / "staging.sqlite3"

    assert _run_with_migrations(root, out, migrations, "--apply-pending") == 0
    _lines(capsys)

    created = sqlite3.connect(out)
    try:
        assert created.execute("SELECT id FROM staging_probe").fetchall() == [("ok",)]
    finally:
        created.close()


def test_without_the_flag_the_historical_refusal_is_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "sync"
    _generation_db(root, ledger=MIGRATIONS[:2])
    out = tmp_path / "staging.sqlite3"

    assert _run(root, out) == 1
    assert "STAGING_DB_REFUSED reason=staging_ledger_incomplete" in _lines(capsys)
    assert not out.exists()


def test_an_unknown_ledger_name_still_refuses_while_pending_is_allowed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "sync"
    _generation_db(
        root, ledger=MIGRATIONS[:2], extra_ledger=("080_not_in_repo.sql",)
    )
    out = tmp_path / "staging.sqlite3"

    assert _run(root, out, "--apply-pending") == 1
    assert "STAGING_DB_REFUSED reason=staging_ledger_unknown" in _lines(capsys)
    assert not out.exists()


def test_a_hole_in_the_pending_set_refuses_instead_of_replaying(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """003 applied while 002 is missing is not "one migration behind"."""

    root = tmp_path / "sync"
    _generation_db(root, ledger=(MIGRATIONS[0], MIGRATIONS[2]))
    out = tmp_path / "staging.sqlite3"

    assert _run(root, out, "--apply-pending") == 1
    assert "STAGING_DB_REFUSED reason=staging_ledger_gap" in _lines(capsys)
    assert not out.exists()


def test_a_parity_mismatch_stops_before_the_copy_is_advanced(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "sync"
    _generation_db(root, ledger=MIGRATIONS[:2])
    out = tmp_path / "staging.sqlite3"
    monkeypatch.setattr(
        staging.parity, "main", lambda argv: staging.parity.EXIT_DRIFT
    )

    assert _run(root, out, "--apply-pending") == 1
    printed = _lines(capsys)
    assert "STAGING_DB_PENDING_APPLIED count=0" in printed

    created = sqlite3.connect(out)
    try:
        names = {row[0] for row in created.execute("SELECT name FROM d1_migrations")}
        assert names == set(MIGRATIONS[:2])
    finally:
        created.close()


def test_a_failing_pending_migration_leaves_no_staging_database(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "sync"
    source = _generation_db(root, ledger=MIGRATIONS[:2])
    source_sha = _sha(source)
    migrations = _migrations(root, MIGRATIONS[:2])
    (migrations / "003_project_files.sql").write_text(
        "CREATE TABLE broken (id TEXT PRIMARY KEY;\n", encoding="utf-8"
    )
    out = tmp_path / "staging.sqlite3"

    assert _run_with_migrations(root, out, migrations, "--apply-pending") == 1
    assert (
        "STAGING_DB_REFUSED reason=staging_pending_migration_failed"
        in _lines(capsys)
    )
    assert not out.exists()
    assert _sha(source) == source_sha


def _record_metadata(monkeypatch: pytest.MonkeyPatch, sink: list) -> None:
    def chown(path, uid, gid):
        sink.append(("chown", uid, gid))

    def chmod(path, mode):
        sink.append(("chmod", mode))

    monkeypatch.setattr(staging.os, "chown", chown, raising=False)
    monkeypatch.setattr(staging, "_chmod", chmod)


def test_replacing_keeps_the_existing_owner_and_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The root-run bug: a replaced chat.sqlite3 must stay openable by the service."""

    root = tmp_path / "sync"
    _generation_db(root)
    out = tmp_path / "staging.sqlite3"
    out.write_text("old staging file", encoding="utf-8")
    info = out.stat()
    calls: list = []
    _record_metadata(monkeypatch, calls)

    assert _run(root, out, "--force") == 0
    printed = _lines(capsys)

    mode = stat.S_IMODE(info.st_mode)
    assert f"STAGING_DB_OWNERSHIP source=existing uid={info.st_uid} gid={info.st_gid}" in printed
    assert f"mode={mode:04o}" in printed
    assert ("chown", info.st_uid, info.st_gid) in calls
    assert ("chmod", mode) in calls
    assert "STAGING_DB_FROM_GENERATION=READY" in printed


def test_a_new_database_uses_the_requested_owner_and_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "sync"
    _generation_db(root)
    out = tmp_path / "staging.sqlite3"
    calls: list = []
    _record_metadata(monkeypatch, calls)

    assert _run(root, out, "--owner", "1234:5678", "--mode", "0640") == 0
    printed = _lines(capsys)

    assert "STAGING_DB_OWNERSHIP source=argument uid=1234 gid=5678 mode=0640" in printed
    assert ("chown", 1234, 5678) in calls
    assert ("chmod", 0o640) in calls


def test_an_unapplied_owner_refuses_and_leaves_no_database(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "sync"
    _generation_db(root)
    out = tmp_path / "staging.sqlite3"
    out.write_text("old staging file", encoding="utf-8")

    def refuse(path, mode):
        raise OSError("chmod not permitted")

    monkeypatch.setattr(staging, "_chmod", refuse)

    assert _run(root, out, "--force") == 1
    assert "STAGING_DB_REFUSED reason=staging_owner_unapplied" in _lines(capsys)
    assert not out.exists()


def test_a_root_run_without_an_owner_argument_refuses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "sync"
    _generation_db(root)
    out = tmp_path / "staging.sqlite3"
    monkeypatch.setattr(staging, "_effective_uid", lambda: 0)

    assert _run(root, out) == 2
    assert "STAGING_DB_REFUSED reason=staging_owner_required" in _lines(capsys)
    assert not out.exists()


def test_an_invalid_owner_argument_is_a_usage_refusal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "sync"
    _generation_db(root)
    out = tmp_path / "staging.sqlite3"

    assert _run(root, out, "--mode", "999") == 2
    assert "STAGING_DB_REFUSED reason=staging_owner_invalid" in _lines(capsys)
    assert not out.exists()
