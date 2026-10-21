from __future__ import annotations

import importlib.util
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/b62-d1-migration-013-gate.yml"
HELPER = ROOT / ".github/scripts/b62_d1_migration_013_schema.py"
MIGRATION = ROOT / "apps/padiem-chat/migrations/013_padiem_calendar.sql"


def _load_helper():
    spec = importlib.util.spec_from_file_location("b62_d1_013", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _result(rows):
    return {"success": True, "results": rows}


def _objects() -> list[dict[str, object]]:
    return [
        {
            "name": "padiem_calendar_work_log",
            "type": "table",
            "sql": (
                "CREATE TABLE padiem_calendar_work_log ("
                "id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, "
                "owner_id TEXT NOT NULL, date TEXT NOT NULL, title TEXT NOT NULL, "
                "content TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
            ),
        },
        {
            "name": "padiem_calendar_appointment",
            "type": "table",
            "sql": (
                "CREATE TABLE padiem_calendar_appointment ("
                "id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, "
                "owner_id TEXT NOT NULL, appointment_type TEXT NOT NULL "
                "CHECK (appointment_type IN ('date_only','all_day','timed')), "
                "title TEXT NOT NULL, description TEXT, date TEXT NOT NULL, "
                "start_at TEXT, end_at TEXT, timezone TEXT, "
                "reminder_minutes INTEGER CHECK (reminder_minutes IS NULL OR "
                "(reminder_minutes >= 0 AND reminder_minutes <= 40320)), "
                "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
            ),
        },
        {
            "name": "idx_padiem_calendar_work_log_ws_date",
            "type": "index",
            "sql": (
                "CREATE INDEX idx_padiem_calendar_work_log_ws_date "
                "ON padiem_calendar_work_log (workspace_id, date, created_at)"
            ),
        },
        {
            "name": "idx_padiem_calendar_work_log_ws_owner",
            "type": "index",
            "sql": (
                "CREATE INDEX idx_padiem_calendar_work_log_ws_owner "
                "ON padiem_calendar_work_log (workspace_id, owner_id)"
            ),
        },
        {
            "name": "idx_padiem_calendar_appointment_ws_date",
            "type": "index",
            "sql": (
                "CREATE INDEX idx_padiem_calendar_appointment_ws_date "
                "ON padiem_calendar_appointment (workspace_id, date, start_at)"
            ),
        },
        {
            "name": "idx_padiem_calendar_appointment_ws_owner",
            "type": "index",
            "sql": (
                "CREATE INDEX idx_padiem_calendar_appointment_ws_owner "
                "ON padiem_calendar_appointment (workspace_id, owner_id)"
            ),
        },
    ]


def _work_log_columns() -> list[dict[str, object]]:
    return [
        {"name": name, "type": type_name, "notnull": notnull, "pk": pk}
        for name, type_name, notnull, pk in (
            ("id", "TEXT", 0, 1),
            ("workspace_id", "TEXT", 1, 0),
            ("owner_id", "TEXT", 1, 0),
            ("date", "TEXT", 1, 0),
            ("title", "TEXT", 1, 0),
            ("content", "TEXT", 0, 0),
            ("created_at", "TEXT", 1, 0),
            ("updated_at", "TEXT", 1, 0),
        )
    ]


def _appointment_columns() -> list[dict[str, object]]:
    return [
        {"name": name, "type": type_name, "notnull": notnull, "pk": pk}
        for name, type_name, notnull, pk in (
            ("id", "TEXT", 0, 1),
            ("workspace_id", "TEXT", 1, 0),
            ("owner_id", "TEXT", 1, 0),
            ("appointment_type", "TEXT", 1, 0),
            ("title", "TEXT", 1, 0),
            ("description", "TEXT", 0, 0),
            ("date", "TEXT", 1, 0),
            ("start_at", "TEXT", 0, 0),
            ("end_at", "TEXT", 0, 0),
            ("timezone", "TEXT", 0, 0),
            ("reminder_minutes", "INTEGER", 0, 0),
            ("created_at", "TEXT", 1, 0),
            ("updated_at", "TEXT", 1, 0),
        )
    ]


def _payload(*, state: str):
    if state == "missing":
        return {
            "success": True,
            "result": [_result([]), _result([]), _result([])],
        }
    objects = _objects()
    work_log_columns = _work_log_columns()
    appointment_columns = _appointment_columns()
    if state == "exact":
        return {
            "success": True,
            "result": [
                _result(objects),
                _result(work_log_columns),
                _result(appointment_columns),
            ],
        }
    if state == "partial":
        # One table applied and the other missing: the gate does not own it.
        return {
            "success": True,
            "result": [
                _result([objects[0]]),
                _result(work_log_columns),
                _result([]),
            ],
        }
    # drift: the work log table exists but its columns are not the reviewed ones.
    return {
        "success": True,
        "result": [
            _result(objects),
            _result(work_log_columns[:2]),
            _result(appointment_columns),
        ],
    }


def test_schema_classifier_missing_exact_drift() -> None:
    helper = _load_helper()
    assert helper.classify(_payload(state="missing")) == "missing"
    assert helper.classify(_payload(state="exact")) == "exact"
    assert helper.classify(_payload(state="drift")) == "drift"
    assert helper.classify(_payload(state="partial")) == "drift"


def test_source_contract_proves_the_migration_is_additive() -> None:
    helper = _load_helper()
    text = helper.source()
    assert "CREATE TABLE IF NOT EXISTS padiem_calendar_work_log" in text
    assert "CREATE TABLE IF NOT EXISTS padiem_calendar_appointment" in text
    for forbidden in (
        "DROP TABLE",
        "ALTER TABLE",
        "DELETE FROM",
        "UPDATE USERS",
        "UPDATE PASSWORD_CREDENTIALS",
        "INSERT INTO USERS",
        "PRAGMA FOREIGN_KEYS",
    ):
        assert forbidden not in text.upper()


def test_migration_is_additive_and_preserves_the_account_rows() -> None:
    db = sqlite3.connect(":memory:")
    db.executescript(
        """
        PRAGMA foreign_keys=ON;
        CREATE TABLE users (
          id TEXT PRIMARY KEY,
          auth_provider TEXT NOT NULL CHECK (auth_provider = 'google'),
          provider_subject TEXT NOT NULL,
          email TEXT NOT NULL,
          display_name TEXT NOT NULL DEFAULT '',
          picture_url TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE (auth_provider, provider_subject)
        );
        CREATE TABLE password_credentials (
          user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
          username TEXT NOT NULL COLLATE NOCASE UNIQUE,
          password_hash TEXT NOT NULL,
          failed_attempts INTEGER NOT NULL DEFAULT 0,
          locked_until TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        INSERT INTO users VALUES ('usr_1','google','sub-1','a@example.test','A','','t','t');
        INSERT INTO password_credentials VALUES ('usr_1','a@example.test','hash',0,NULL,'t','t');
        """
    )
    before_users = db.execute("SELECT * FROM users").fetchall()
    before_credentials = db.execute("SELECT * FROM password_credentials").fetchall()

    db.executescript(MIGRATION.read_text(encoding="utf-8"))

    assert db.execute("SELECT * FROM users").fetchall() == before_users
    assert db.execute("SELECT * FROM password_credentials").fetchall() == before_credentials
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []

    # A work log and an appointment of one workspace are stored and stay
    # isolated from another workspace.
    db.execute(
        "INSERT INTO padiem_calendar_work_log VALUES "
        "('log_1','ws_1','usr_1','2026-10-21','T','C','t','t')"
    )
    db.execute(
        "INSERT INTO padiem_calendar_appointment VALUES "
        "('apt_1','ws_1','usr_1','timed','T',NULL,'2026-10-21','t','t','Asia/Seoul',"
        "10,'t','t')"
    )
    db.execute(
        "INSERT INTO padiem_calendar_appointment VALUES "
        "('apt_2','ws_1','usr_1','timed','T',NULL,'2026-10-22',NULL,NULL,NULL,"
        "NULL,'t','t')"
    )
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert db.execute(
        "SELECT COUNT(*) FROM padiem_calendar_appointment WHERE workspace_id = 'ws_1'"
    ).fetchone()[0] == 2
    try:
        db.execute(
            "INSERT INTO padiem_calendar_appointment VALUES "
            "('apt_3','ws_1','usr_1','nope','T',NULL,'2026-10-21',NULL,NULL,NULL,"
            "NULL,'t','t')"
        )
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("the appointment type check must refuse an unknown type")
    try:
        db.execute(
            "INSERT INTO padiem_calendar_appointment VALUES "
            "('apt_4','ws_1','usr_1','timed','T',NULL,'2026-10-21',NULL,NULL,NULL,"
            "99999,'t','t')"
        )
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("the reminder bound must refuse an out-of-range value")


def test_migration_contains_no_existing_table_mutation() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    upper = sql.upper()
    assert "CREATE TABLE IF NOT EXISTS padiem_calendar_work_log" in sql
    assert "CREATE TABLE IF NOT EXISTS padiem_calendar_appointment" in sql
    for forbidden in (
        "DROP TABLE",
        "ALTER TABLE",
        "DELETE FROM",
        "UPDATE USERS",
        "UPDATE PASSWORD_CREDENTIALS",
        "INSERT INTO USERS",
        "PRAGMA FOREIGN_KEYS",
        "PRAGMA DEFERRED_FOREIGN_KEYS",
    ):
        assert forbidden not in upper


def test_workflow_heredocs_are_terminated_on_their_own_line() -> None:
    # A heredoc terminator that shares its line with the next command breaks
    # the script it opens, and the failure shows up as an unrelated syntax
    # error far from the edit that caused it.
    workflow = WORKFLOW.read_text(encoding="utf-8")
    for number, line in enumerate(workflow.splitlines(), start=1):
        stripped = line.strip()
        if stripped == "PY":
            continue
        if stripped.startswith("PY "):
            raise AssertionError(
                f"line {number} joins a heredoc terminator with the next command"
            )


def test_workflow_shell_blocks_parse() -> None:
    """Every ``run:`` block must be a valid shell script.

    A heredoc terminator that shares its line with the next command is a
    syntax error that only shows up when the workflow runs against Production.
    ``bash -n`` catches it in the source contract instead.
    """

    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is not available on this host")
    yaml = pytest.importorskip("yaml")
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(workflow, dict)
    jobs = workflow.get("jobs") or {}
    assert jobs
    with tempfile.TemporaryDirectory() as directory:
        for job_name, job in jobs.items():
            for index, step in enumerate(job.get("steps") or []):
                script = step.get("run")
                if not isinstance(script, str) or not script.strip():
                    continue
                path = Path(directory) / f"{job_name}-{index}.sh"
                path.write_text(script, encoding="utf-8", newline="\n")
                result = subprocess.run(
                    [bash, "-n", path.name],
                    capture_output=True,
                    text=True,
                    cwd=str(path.parent),
                )
                assert result.returncode == 0, (
                    f"{job_name} / {step.get('name')} is not a valid shell script: "
                    f"{result.stderr[:600]}"
                )


def test_workflow_is_exact_main_and_migration_specific() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert 'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"' in workflow
    assert "environment: production" in workflow
    assert "APPLY_B62_D1_MIGRATION_013_FROM_EXACT_MAIN" in workflow
    assert "apps/padiem-chat/migrations/013_padiem_calendar.sql" in workflow
    assert "B62_D1_MIGRATION_013_POST_READBACK=PASS" in workflow
    assert "SKIPPED_ALREADY_APPLIED" in workflow
    assert "existing migration 013 schema is structurally different" in workflow
    assert "D1_IDENTIFIER_OUTPUT=0" in workflow
    assert "ROW_CONTENT_READ=0" in workflow
    assert "WORKER_DEPLOYED=0" in workflow
    assert "BINDING_MUTATION=0" in workflow
    assert "UNRELATED_MIGRATION_APPLY=0" in workflow
    assert "B62_D1_MIGRATION_013_ACCOUNT_ROWS_PRESERVED=PASS" in workflow
    assert (
        "github.event_name == 'workflow_dispatch' && inputs.mode == 'apply_migration_013'"
        in workflow
    )
    for forbidden in (
        "wrangler d1 create",
        "d1 migrations apply",
        "pywrangler deploy",
        "wrangler deploy",
    ):
        assert forbidden not in workflow


if __name__ == "__main__":
    test_schema_classifier_missing_exact_drift()
    test_source_contract_proves_the_migration_is_additive()
    test_migration_is_additive_and_preserves_the_account_rows()
    test_migration_contains_no_existing_table_mutation()
    test_workflow_is_exact_main_and_migration_specific()
    print("B62_D1_MIGRATION_013_GATE_TESTS=PASS")
