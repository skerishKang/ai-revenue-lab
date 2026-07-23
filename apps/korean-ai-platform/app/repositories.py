"""Product-local SQLite repositories for the Korean AI Platform (Business 14).

Repositories own SQL and hydration only. They never run domain transitions and
never own transactions — the application service passes an open connection
(transaction owner) into each method.

Persistence rules:
- relational rows with constraints; no JSON aggregate blobs;
- run evidence history is preserved per ``run_number`` (rework adds a new run,
  it does not overwrite previous runs);
- the latest run is hydrated into ``Task.run``;
- invalid enums / corrupted required child state fail closed with a fixed
  :class:`~app.db.PersistenceError` (never silently defaulted);
- raw API keys are never stored (only a ``registered`` boolean).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from app.db import PersistenceError
from app.domain import (
    BranchMode,
    ChangedFile,
    CostLine,
    ExternalPolicy,
    Finding,
    RunArtifact,
    StepState,
    StepStatus,
    Task,
    TaskStatus,
    TestResult,
    TestSummary,
    TimelineEvent,
    Verdict,
)
from app.store import ByokState, SecuritySettings


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _coerce(enum_cls, value: str, field: str):
    try:
        return enum_cls(value)
    except ValueError as exc:
        raise PersistenceError(exc) from exc


def _require(row, field: str):
    value = row[field] if field in row.keys() else None
    if value is None:
        raise PersistenceError(KeyError(f"missing required column {field}"))
    return value


# ---------------------------------------------------------------------------
# Run evidence hydration / persistence
# ---------------------------------------------------------------------------


def _hydrate_run(conn: sqlite3.Connection, task_id: str, run_number: int) -> RunArtifact:
    run_row = conn.execute(
        "SELECT * FROM task_runs WHERE task_id = ? AND run_number = ?",
        (task_id, run_number),
    ).fetchone()
    if run_row is None:
        raise PersistenceError(KeyError("task_runs row missing"))

    steps = [
        StepState(
            key=r["key"],
            label=r["label"],
            status=_coerce(StepStatus, r["status"], "run_steps.status"),
            detail=r["detail"],
        )
        for r in conn.execute(
            "SELECT * FROM run_steps WHERE task_id = ? AND run_number = ? ORDER BY position",
            (task_id, run_number),
        )
    ]

    changed_files = [
        ChangedFile(
            path=r["path"],
            additions=r["additions"],
            deletions=r["deletions"],
            language=r["language"],
            diff=r["diff"],
        )
        for r in conn.execute(
            "SELECT * FROM run_changed_files WHERE task_id = ? AND run_number = ? ORDER BY position",
            (task_id, run_number),
        )
    ]

    summary_row = conn.execute(
        "SELECT * FROM run_test_summaries WHERE task_id = ? AND run_number = ?",
        (task_id, run_number),
    ).fetchone()
    tests = None
    if summary_row is not None:
        results = [
            TestResult(name=r["name"], status=r["status"], detail=r["detail"])
            for r in conn.execute(
                "SELECT * FROM run_test_results WHERE task_id = ? AND run_number = ? ORDER BY position",
                (task_id, run_number),
            )
        ]
        tests = TestSummary(
            command=summary_row["command"],
            total=summary_row["total"],
            passed=summary_row["passed"],
            failed=summary_row["failed"],
            skipped=summary_row["skipped"],
            results=results,
        )

    findings = [
        Finding(level=r["level"], text=r["text"])
        for r in conn.execute(
            "SELECT * FROM run_findings WHERE task_id = ? AND run_number = ? ORDER BY position",
            (task_id, run_number),
        )
    ]

    path_violations = [
        r["text"]
        for r in conn.execute(
            "SELECT * FROM run_path_violations WHERE task_id = ? AND run_number = ? ORDER BY position",
            (task_id, run_number),
        )
    ]

    security_notes = [
        r["text"]
        for r in conn.execute(
            "SELECT * FROM run_security_notes WHERE task_id = ? AND run_number = ? ORDER BY position",
            (task_id, run_number),
        )
    ]

    cost_lines = [
        CostLine(
            model_id=r["model_id"],
            model_name=r["model_name"],
            role=r["role"],
            tokens_in=r["tokens_in"],
            tokens_out=r["tokens_out"],
            krw=r["krw"],
        )
        for r in conn.execute(
            "SELECT * FROM run_cost_lines WHERE task_id = ? AND run_number = ? ORDER BY position",
            (task_id, run_number),
        )
    ]

    timeline = [
        TimelineEvent(at=r["at"], label=r["label"], detail=r["detail"])
        for r in conn.execute(
            "SELECT * FROM run_timeline WHERE task_id = ? AND run_number = ? ORDER BY position",
            (task_id, run_number),
        )
    ]

    return RunArtifact(
        run_number=run_row["run_number"],
        steps=steps,
        plan_text=run_row["plan_text"],
        worker_claim=run_row["worker_claim"],
        changed_files=changed_files,
        tests=tests,
        verdict=_coerce(Verdict, run_row["verdict"], "task_runs.verdict"),
        findings=findings,
        path_violations=path_violations,
        security_notes=security_notes,
        cost_lines=cost_lines,
        cost_total_krw=run_row["cost_total_krw"],
        over_budget=bool(run_row["over_budget"]),
        timeline=timeline,
    )


def _save_run(conn: sqlite3.Connection, task_id: str, run: RunArtifact) -> None:
    run_number = run.run_number
    # Replace only this run_number's rows; other run_numbers (history) remain.
    for table in (
        "run_steps",
        "run_changed_files",
        "run_test_summaries",
        "run_test_results",
        "run_findings",
        "run_path_violations",
        "run_security_notes",
        "run_cost_lines",
        "run_timeline",
        "task_runs",
    ):
        conn.execute(
            f"DELETE FROM {table} WHERE task_id = ? AND run_number = ?",
            (task_id, run_number),
        )

    conn.execute(
        """
        INSERT INTO task_runs
            (task_id, run_number, plan_text, worker_claim, verdict,
             cost_total_krw, over_budget, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            task_id,
            run_number,
            run.plan_text,
            run.worker_claim,
            run.verdict.value,
            run.cost_total_krw,
            1 if run.over_budget else 0,
            _now_utc(),
        ),
    )

    conn.executemany(
        """
        INSERT INTO run_steps (task_id, run_number, position, key, label, status, detail)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (task_id, run_number, i, s.key, s.label, s.status.value, s.detail)
            for i, s in enumerate(run.steps)
        ],
    )

    conn.executemany(
        """
        INSERT INTO run_changed_files
            (task_id, run_number, position, path, additions, deletions, language, diff)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (task_id, run_number, i, f.path, f.additions, f.deletions, f.language, f.diff)
            for i, f in enumerate(run.changed_files)
        ],
    )

    if run.tests is not None:
        conn.execute(
            """
            INSERT INTO run_test_summaries
                (task_id, run_number, command, total, passed, failed, skipped)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                run_number,
                run.tests.command,
                run.tests.total,
                run.tests.passed,
                run.tests.failed,
                run.tests.skipped,
            ),
        )
        conn.executemany(
            """
            INSERT INTO run_test_results
                (task_id, run_number, position, name, status, detail)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (task_id, run_number, i, r.name, r.status, r.detail)
                for i, r in enumerate(run.tests.results)
            ],
        )

    conn.executemany(
        "INSERT INTO run_findings (task_id, run_number, position, level, text) VALUES (?, ?, ?, ?, ?)",
        [(task_id, run_number, i, f.level, f.text) for i, f in enumerate(run.findings)],
    )
    conn.executemany(
        "INSERT INTO run_path_violations (task_id, run_number, position, text) VALUES (?, ?, ?, ?)",
        [(task_id, run_number, i, v) for i, v in enumerate(run.path_violations)],
    )
    conn.executemany(
        "INSERT INTO run_security_notes (task_id, run_number, position, text) VALUES (?, ?, ?, ?)",
        [(task_id, run_number, i, n) for i, n in enumerate(run.security_notes)],
    )
    conn.executemany(
        """
        INSERT INTO run_cost_lines
            (task_id, run_number, position, model_id, model_name, role, tokens_in, tokens_out, krw)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (task_id, run_number, i, c.model_id, c.model_name, c.role, c.tokens_in, c.tokens_out, c.krw)
            for i, c in enumerate(run.cost_lines)
        ],
    )
    conn.executemany(
        "INSERT INTO run_timeline (task_id, run_number, position, at, label, detail) VALUES (?, ?, ?, ?, ?, ?)",
        [(task_id, run_number, i, e.at, e.label, e.detail) for i, e in enumerate(run.timeline)],
    )


# ---------------------------------------------------------------------------
# Task repository
# ---------------------------------------------------------------------------


class TaskRepository:
    def next_task_id(self, conn: sqlite3.Connection) -> str:
        row = conn.execute("SELECT next_value FROM task_id_sequence WHERE id = 1").fetchone()
        if row is None:
            raise PersistenceError(KeyError("task_id_sequence missing"))
        value = row["next_value"]
        conn.execute("UPDATE task_id_sequence SET next_value = ? WHERE id = 1", (value + 1,))
        return f"t-{value:03d}"

    def count_tasks(self, conn: sqlite3.Connection) -> int:
        return conn.execute("SELECT COUNT(*) AS c FROM tasks").fetchone()["c"]

    def save_task(self, conn: sqlite3.Connection, task: Task) -> None:
        conn.execute(
            """
            INSERT INTO tasks
                (id, title, instruction, project_id, worker_model_id, validator_model_id,
                 cost_limit_krw, external_policy, branch_mode, status, created_at,
                 rework_count, approver, commit_sha, branch_name, completed_at,
                 rejected_reason, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                instruction = excluded.instruction,
                project_id = excluded.project_id,
                worker_model_id = excluded.worker_model_id,
                validator_model_id = excluded.validator_model_id,
                cost_limit_krw = excluded.cost_limit_krw,
                external_policy = excluded.external_policy,
                branch_mode = excluded.branch_mode,
                status = excluded.status,
                rework_count = excluded.rework_count,
                approver = excluded.approver,
                commit_sha = excluded.commit_sha,
                branch_name = excluded.branch_name,
                completed_at = excluded.completed_at,
                rejected_reason = excluded.rejected_reason,
                updated_at = excluded.updated_at
            """,
            (
                task.id,
                task.title,
                task.instruction,
                task.project_id,
                task.worker_model_id,
                task.validator_model_id,
                task.cost_limit_krw,
                task.external_policy.value,
                task.branch_mode.value,
                task.status.value,
                task.created_at,
                task.rework_count,
                task.approver,
                task.commit_sha,
                task.branch_name,
                task.completed_at,
                task.rejected_reason,
                _now_utc(),
            ),
        )

        conn.execute("DELETE FROM task_allowed_paths WHERE task_id = ?", (task.id,))
        conn.executemany(
            "INSERT INTO task_allowed_paths (task_id, position, path) VALUES (?, ?, ?)",
            [(task.id, i, p) for i, p in enumerate(task.allowed_paths)],
        )
        conn.execute("DELETE FROM task_denied_paths WHERE task_id = ?", (task.id,))
        conn.executemany(
            "INSERT INTO task_denied_paths (task_id, position, path) VALUES (?, ?, ?)",
            [(task.id, i, p) for i, p in enumerate(task.denied_paths)],
        )
        conn.execute("DELETE FROM task_rework_reasons WHERE task_id = ?", (task.id,))
        conn.executemany(
            "INSERT INTO task_rework_reasons (task_id, position, reason) VALUES (?, ?, ?)",
            [(task.id, i, r) for i, r in enumerate(task.rework_reasons)],
        )

        if task.run is not None:
            _save_run(conn, task.id, task.run)

    def _hydrate_task(self, conn: sqlite3.Connection, row: sqlite3.Row) -> Task:
        task_id = row["id"]
        allowed = [
            r["path"]
            for r in conn.execute(
                "SELECT path FROM task_allowed_paths WHERE task_id = ? ORDER BY position",
                (task_id,),
            )
        ]
        denied = [
            r["path"]
            for r in conn.execute(
                "SELECT path FROM task_denied_paths WHERE task_id = ? ORDER BY position",
                (task_id,),
            )
        ]
        rework_reasons = [
            r["reason"]
            for r in conn.execute(
                "SELECT reason FROM task_rework_reasons WHERE task_id = ? ORDER BY position",
                (task_id,),
            )
        ]
        latest = conn.execute(
            "SELECT MAX(run_number) AS rn FROM task_runs WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        run = None
        if latest is not None and latest["rn"] is not None:
            run = _hydrate_run(conn, task_id, latest["rn"])

        return Task(
            id=task_id,
            title=row["title"],
            instruction=row["instruction"],
            project_id=row["project_id"],
            worker_model_id=row["worker_model_id"],
            validator_model_id=row["validator_model_id"],
            allowed_paths=allowed,
            denied_paths=denied,
            cost_limit_krw=row["cost_limit_krw"],
            external_policy=_coerce(ExternalPolicy, row["external_policy"], "external_policy"),
            branch_mode=_coerce(BranchMode, row["branch_mode"], "branch_mode"),
            status=_coerce(TaskStatus, row["status"], "status"),
            created_at=row["created_at"],
            run=run,
            rework_count=row["rework_count"],
            rework_reasons=rework_reasons,
            approver=row["approver"],
            commit_sha=row["commit_sha"],
            branch_name=row["branch_name"],
            completed_at=row["completed_at"],
            rejected_reason=row["rejected_reason"],
        )

    def load_task(self, conn: sqlite3.Connection, task_id: str) -> Task | None:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        return self._hydrate_task(conn, row)

    def load_all_tasks(self, conn: sqlite3.Connection) -> list[Task]:
        rows = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC, id DESC").fetchall()
        return [self._hydrate_task(conn, row) for row in rows]

    def load_run_history(self, conn: sqlite3.Connection, task_id: str) -> list[RunArtifact]:
        rows = conn.execute(
            "SELECT run_number FROM task_runs WHERE task_id = ? ORDER BY run_number",
            (task_id,),
        ).fetchall()
        return [_hydrate_run(conn, task_id, r["run_number"]) for r in rows]


# ---------------------------------------------------------------------------
# Settings repository
# ---------------------------------------------------------------------------


class SettingsRepository:
    def load_settings(self, conn: sqlite3.Connection) -> SecuritySettings:
        row = conn.execute("SELECT * FROM security_settings WHERE id = 1").fetchone()
        if row is None:
            raise PersistenceError(KeyError("security_settings row missing"))
        byok: dict[str, ByokState] = {}
        for r in conn.execute("SELECT model_id, registered FROM byok_registrations"):
            byok[r["model_id"]] = ByokState(registered=bool(r["registered"]))
        return SecuritySettings(
            domestic_first=bool(row["domestic_first"]),
            allow_external=bool(row["allow_external"]),
            block_on_secret=bool(row["block_on_secret"]),
            project_cost_limit_krw=row["project_cost_limit_krw"],
            block_push_without_approval=bool(row["block_push_without_approval"]),
            byok=byok,
        )

    def save_settings(self, conn: sqlite3.Connection, settings: SecuritySettings) -> None:
        conn.execute(
            """
            INSERT INTO security_settings
                (id, domestic_first, allow_external, block_on_secret,
                 project_cost_limit_krw, block_push_without_approval, updated_at)
            VALUES (1, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(id) DO UPDATE SET
                domestic_first = excluded.domestic_first,
                allow_external = excluded.allow_external,
                block_on_secret = excluded.block_on_secret,
                project_cost_limit_krw = excluded.project_cost_limit_krw,
                block_push_without_approval = 1,
                updated_at = excluded.updated_at
            """,
            (
                1 if settings.domestic_first else 0,
                1 if settings.allow_external else 0,
                1 if settings.block_on_secret else 0,
                settings.project_cost_limit_krw,
                _now_utc(),
            ),
        )
        conn.execute("DELETE FROM byok_registrations")
        conn.executemany(
            "INSERT INTO byok_registrations (model_id, registered, updated_at) VALUES (?, ?, ?)",
            [
                (model_id, 1 if state.registered else 0, _now_utc())
                for model_id, state in settings.byok.items()
            ],
        )


# ---------------------------------------------------------------------------
# Seed metadata
# ---------------------------------------------------------------------------


def is_seeded(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT seeded FROM seed_meta WHERE id = 1").fetchone()
    return bool(row["seeded"]) if row is not None else False


def mark_seeded(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT INTO seed_meta (id, seeded, seeded_at) VALUES (1, 1, ?)
        ON CONFLICT(id) DO UPDATE SET seeded = 1, seeded_at = excluded.seeded_at
        """,
        (_now_utc(),),
    )
