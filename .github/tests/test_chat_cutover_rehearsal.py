"""Synthetic tests for the cutover rehearsal runner.

No production target, no network and no real generation: the HTTP probe is
injected and every SQLite file is built in a temp directory. The child tools are
the real ones.
"""
from __future__ import annotations

import importlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

rehearsal = importlib.import_module("chat_cutover_rehearsal")

GENERATION = "20261031T042000123456Z"
MIGRATIONS = ("001_auth_history.sql", "002_projects.sql")
STAGING_BASE = "https://chat-com2-staging.padiem.net"


def _db(
    path: Path,
    *,
    rows: int = 3,
    omit_key: bool = False,
    ledger: tuple[str, ...] = MIGRATIONS,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE users (id TEXT PRIMARY KEY, name TEXT, object_key TEXT);
        CREATE TABLE conversations (id TEXT PRIMARY KEY, user_id TEXT, title TEXT);
        CREATE TABLE oracle_mesh_dispatch (id TEXT PRIMARY KEY, state TEXT);
        CREATE TABLE d1_migrations (id INTEGER PRIMARY KEY, name TEXT, applied_at TEXT);
        """
    )
    connection.executemany(
        "INSERT INTO users VALUES (?,?,?)",
        [(f"u{index}", f"name-{index}", f"objects/u{index}.png") for index in range(rows)],
    )
    connection.executemany(
        "INSERT INTO conversations VALUES (?,?,?)",
        [(f"c{index}", f"u{index}", f"title-{index}") for index in range(rows)],
    )
    connection.execute("INSERT INTO oracle_mesh_dispatch VALUES ('d1','queued')")
    for index, name in enumerate(ledger, start=1):
        connection.execute(
            "INSERT INTO d1_migrations (id, name, applied_at) VALUES (?,?,?)",
            (index, name, "2026-10-30T00:00:00Z"),
        )
    if omit_key:
        connection.execute("DELETE FROM users WHERE id = 'u1'")
    connection.commit()
    connection.close()
    return path


class Env:
    """One synthetic rehearsal environment."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        snapshot_b_missing_key: bool = False,
        generation_rows: int = 3,
        generation_ledger: tuple[str, ...] = MIGRATIONS,
        mirror_gap: bool = False,
    ) -> None:
        self.root = tmp_path
        self.snapshot_a = _db(tmp_path / "baseline.sqlite3")
        self.snapshot_b = _db(
            tmp_path / "window-end.sqlite3", omit_key=snapshot_b_missing_key
        )
        self.generation = _db(
            tmp_path / "generations" / GENERATION / "chat.sqlite3",
            rows=generation_rows,
            ledger=generation_ledger,
        )
        self.migrations = tmp_path / "migrations"
        self.migrations.mkdir(parents=True, exist_ok=True)
        for name in MIGRATIONS:
            (self.migrations / name).write_text("SELECT 1;\n", encoding="utf-8")

        pointer = tmp_path / "snapshots" / "current_generation.json"
        pointer.parent.mkdir(parents=True, exist_ok=True)
        pointer.write_text(
            json.dumps({"generation": GENERATION, "databases": {"chat": {}, "engine": {}}}),
            encoding="utf-8",
        )
        self.pointer = pointer
        self.generations_dir = tmp_path / "generations"

        keys = ["objects/u0.png", "objects/u2.png"] if mirror_gap else [
            f"objects/u{index}.png" for index in range(3)
        ]
        self.inventory = tmp_path / "inventory.json"
        self.inventory.write_text(json.dumps({"keys": keys}), encoding="utf-8")

        self.staging_db = tmp_path / "chat-staging" / "chat.sqlite3"
        self.sentinel = tmp_path / "chat-staging" / "MAINTENANCE"
        self.plan_out = tmp_path / "chat-staging" / "handback-plan.json"

    def config(self, **overrides) -> rehearsal.Config:
        values = {
            "base_url": STAGING_BASE,
            "staging_db": str(self.staging_db),
            "sentinel": str(self.sentinel),
            "generation_pointer": str(self.pointer),
            "generations_dir": str(self.generations_dir),
            "snapshot_a": str(self.snapshot_a),
            "snapshot_b": str(self.snapshot_b),
            "mirror_inventories": (str(self.inventory),),
            "migrations_dir": str(self.migrations),
            "queue_origin": "http://127.0.0.1:8830",
            "plan_out": str(self.plan_out),
            "synthetic": True,
            "stop_confirmations": (
                "confirm_stop_tick",
                "confirm_stop_wss",
                "confirm_stop_queue",
            ),
        }
        values.update(overrides)
        return rehearsal.Config(**values)

    def argv(self, *extra: str) -> list[str]:
        base = [
            "--base-url", STAGING_BASE,
            "--staging-db", str(self.staging_db),
            "--sentinel", str(self.sentinel),
            "--generation-pointer", str(self.pointer),
            "--generations-dir", str(self.generations_dir),
            "--snapshot-a", str(self.snapshot_a),
            "--snapshot-b", str(self.snapshot_b),
            "--mirror-inventory", str(self.inventory),
            "--migrations-dir", str(self.migrations),
            "--queue-origin", "http://127.0.0.1:8830",
            "--plan-out", str(self.plan_out),
            "--synthetic",
            "--confirm-stop-tick",
            "--confirm-stop-wss",
            "--confirm-stop-queue",
            *extra,
        ]
        return base


def _probe_ok(url: str, timeout: float) -> tuple[int, str]:
    if url.endswith(rehearsal.DEFAULT_FROZEN_PATHS):
        return 503, json.dumps({"error": {"code": "maintenance", "message": "점검"}})
    return 200, "ok"


def _probe_unfrozen(url: str, timeout: float) -> tuple[int, str]:
    if url.endswith(rehearsal.DEFAULT_FROZEN_PATHS):
        return 200, "ok"
    return 200, "ok"


def _run(
    env: Env,
    *,
    dry_run: bool = False,
    probe=_probe_ok,
    apply_pending: bool = False,
) -> rehearsal.RehearsalReport:
    runner = rehearsal.Rehearsal(
        env.config(apply_pending=apply_pending), dry_run=dry_run, probe=probe
    )
    return runner.run()


def _stages(report: rehearsal.RehearsalReport) -> list[str]:
    return [stage.stage for stage in report.stages]


def test_full_synthetic_pass_records_time_and_verdicts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = Env(tmp_path)
    report = _run(env)
    printed = capsys.readouterr().out

    assert report.passed is True
    assert _stages(report) == list(rehearsal.STAGE_ORDER)
    assert report.failed_stage is None
    assert report.rollback == []
    for stage in report.stages:
        assert stage.passed
        assert stage.started_utc and stage.ended_utc
        assert stage.started_utc <= stage.ended_utc
        assert stage.seconds >= 0.0
    assert "REHEARSAL_SUMMARY=PASS" in printed
    assert "CHAT_COPY_PARITY=MATCH" in printed
    assert "STAGING_DB_FROM_GENERATION=READY" in printed
    assert "CHAT_OBJECT_REFERENCE=MATCH" in printed
    assert env.sentinel.is_file()
    assert env.staging_db.is_file()

    created = sqlite3.connect(env.staging_db)
    try:
        assert created.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 3
        assert created.execute("SELECT COUNT(*) FROM oracle_mesh_dispatch").fetchone()[0] == 0
    finally:
        created.close()


def test_dry_run_prints_the_plan_and_touches_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = Env(tmp_path)
    assert rehearsal.main(env.argv("--dry-run")) == 0
    printed = capsys.readouterr().out

    assert "REHEARSAL_COMMAND stage=snapshot_pair" in printed
    assert "REHEARSAL_COMMAND stage=reflect" in printed
    assert "REHEARSAL_COMMAND stage=parity" in printed
    assert "REHEARSAL_COMMAND stage=object_reference" in printed
    assert "REHEARSAL_ACTION stage=freeze_on action=create_sentinel" in printed
    assert "REHEARSAL_ACTION stage=freeze_probe action=get_expect_503" in printed
    assert "REHEARSAL_SUMMARY=PASS" in printed
    assert not env.sentinel.exists()
    assert not env.staging_db.exists()
    assert not env.plan_out.exists()


@pytest.mark.parametrize(
    "override",
    [
        {"base_url": "https://chat.padiem.net"},
        {"base_url": "https://www.padiem.net"},
        {"staging_db": "/mnt/d/padiem/chat-com2/chat.sqlite3"},
        {"sentinel": "/mnt/d/padiem/chat-com2/MAINTENANCE"},
        {"queue_origin": "http://127.0.0.1:8797"},
        {"plan_out": "D:/PADIEM-Servers/b62-chat-api/runtime/handback-plan.json"},
    ],
)
def test_production_targets_are_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], override: dict
) -> None:
    env = Env(tmp_path)
    runner = rehearsal.Rehearsal(env.config(**override), probe=_probe_ok)
    with pytest.raises(rehearsal.RehearsalError) as refusal:
        rehearsal.guard_target(runner.config)
    assert str(refusal.value) in {"production_target", "queue_origin_production"}
    capsys.readouterr()

    # The same refusal through the CLI: nothing is created.
    env2 = Env(tmp_path / "second")
    override_argv = []
    for key, value in override.items():
        flag = "--" + key.replace("_", "-")
        override_argv += [flag, value]
    assert rehearsal.main(env2.argv(*override_argv)) == 2
    printed = capsys.readouterr().out
    assert "REHEARSAL_REFUSED reason=" in printed
    assert not env2.sentinel.exists()


def test_unknown_host_and_queue_are_refused_without_synthetic(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = Env(tmp_path)
    capsys.readouterr()

    for override, reason in (
        ({"base_url": "https://example.workers.dev"}, "unknown_target"),
        ({"queue_origin": "https://queue.padiem.net"}, "queue_origin_unexpected"),
        ({"queue_origin": "http://127.0.0.1:8831"}, "queue_origin_unexpected"),
    ):
        with pytest.raises(rehearsal.RehearsalError) as refusal:
            rehearsal.guard_target(env.config(**override))
        assert str(refusal.value) == reason

    # Loopback is only the staging port 8801, and only in a real run.
    with pytest.raises(rehearsal.RehearsalError) as refusal:
        rehearsal.guard_target(
            env.config(base_url="http://127.0.0.1:9999", synthetic=False)
        )
    assert str(refusal.value) == "unknown_target"
    with pytest.raises(rehearsal.RehearsalError) as refusal:
        rehearsal.guard_target(
            env.config(base_url="http://127.0.0.1:8801", synthetic=False)
        )
    assert str(refusal.value) == "staging_root_outside"


def test_missing_artifact_and_tool_are_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    env = Env(tmp_path)
    capsys.readouterr()

    with pytest.raises(rehearsal.RehearsalError) as refusal:
        rehearsal.guard_target(env.config(snapshot_b=str(tmp_path / "not-there.sqlite3")))
    assert str(refusal.value) == "artifact_missing:snapshot_b"

    monkeypatch.setitem(rehearsal.TOOLS, "object_reference", tmp_path / "missing.py")
    with pytest.raises(rehearsal.RehearsalError) as refusal:
        rehearsal.guard_target(env.config())
    assert str(refusal.value) == "tool_missing:object_reference"


def test_stop_confirmation_missing_stops_before_freezing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = Env(tmp_path)
    report = _run(env, probe=_probe_ok)
    assert report.passed

    env2 = Env(tmp_path / "second")
    capsys.readouterr()
    runner = rehearsal.Rehearsal(
        env2.config(stop_confirmations=("confirm_stop_tick", "confirm_stop_wss")),
        probe=_probe_ok,
    )
    report2 = runner.run()
    printed = capsys.readouterr().out

    assert report2.passed is False
    assert report2.failed_stage == "stop_before_window"
    assert _stages(report2)[-1] == "stop_before_window"
    assert "REHEARSAL_STOP_CONFIRMATION_MISSING=confirm_stop_queue" in printed
    assert "REHEARSAL_ROLLBACK=SKIPPED reason=artifact_missing:chat.sqlite3" in printed
    assert not env2.sentinel.exists()
    assert not env2.staging_db.exists()


def test_unfrozen_read_path_stops_at_the_probe(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = Env(tmp_path)
    report = _run(env, probe=_probe_unfrozen)
    printed = capsys.readouterr().out

    assert report.failed_stage == "freeze_probe"
    assert "REHEARSAL_STAGE=freeze_probe RESULT=FAIL" in printed
    assert "/auth/google/callback:200" in printed
    assert "REHEARSAL_ROLLBACK=SKIPPED" in printed
    assert env.sentinel.is_file()  # the window stays open for the CTO
    assert not env.staging_db.exists()


def test_window_drift_stops_at_snapshot_pair_and_rollback_is_skipped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = Env(tmp_path, snapshot_b_missing_key=True)
    report = _run(env)
    printed = capsys.readouterr().out

    assert report.failed_stage == "snapshot_pair"
    assert "CHAT_COPY_PARITY=DRIFT" in printed
    assert "REHEARSAL_ROLLBACK=SKIPPED" in printed
    assert not env.staging_db.exists()


def test_parity_drift_runs_the_read_only_handback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A drift caught after the staging copy exists exercises plan → verify."""

    env = Env(tmp_path)
    report = _run(env, probe=_probe_ok)
    assert report.passed

    # snapshot_pair compares A with B, so keep the window copy clean and let the
    # generation differ from it: parity then fails after reflect.
    env2 = Env(tmp_path / "second", generation_rows=2)
    capsys.readouterr()
    report2 = _run(env2)
    printed = capsys.readouterr().out

    assert report2.failed_stage == "parity"
    assert "REHEARSAL_ROLLBACK=PLAN result=PASS" in printed
    assert "CHAT_HANDBACK_PLAN=OK" in printed
    assert "CHAT_HANDBACK_VERIFY=PASS" in printed
    assert "REHEARSAL_ROLLBACK=VERIFY result=PASS" in printed
    assert env2.plan_out.is_file()


def test_object_gap_fails_last_stage_and_reports_rollback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = Env(tmp_path, mirror_gap=True)
    report = _run(env)
    printed = capsys.readouterr().out

    assert report.failed_stage == "object_reference"
    assert "CHAT_OBJECT_REFERENCE=GAP" in printed
    assert "CHAT_OBJECT_MISSING_DIGEST=" in printed
    assert "REHEARSAL_ROLLBACK=VERIFY result=PASS" in printed


def test_two_bucket_inventories_reach_the_object_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = Env(tmp_path)
    workspace = tmp_path / "workspace-inventory.json"
    workspace.write_text(json.dumps({"keys": ["objects/u0.png"]}), encoding="utf-8")

    assert rehearsal.main(env.argv("--dry-run", "--mirror-inventory", str(workspace))) == 0
    printed = capsys.readouterr().out

    command = next(
        line
        for line in printed.splitlines()
        if line.startswith("REHEARSAL_COMMAND stage=object_reference")
    )
    assert command.count("--inventory") == 2
    assert str(env.inventory) in command
    assert str(workspace) in command


def test_one_missing_inventory_stops_the_run(tmp_path: Path) -> None:
    env = Env(tmp_path)
    config = env.config(
        mirror_inventories=(str(env.inventory), str(tmp_path / "absent.json"))
    )
    with pytest.raises(rehearsal.RehearsalError) as refusal:
        rehearsal.guard_target(config)
    assert str(refusal.value) == "artifact_missing:mirror_inventory"


def test_an_inventory_in_a_production_path_is_refused(tmp_path: Path) -> None:
    env = Env(tmp_path)
    config = env.config(
        mirror_inventories=(str(env.inventory), "D:/PADIEM-Servers/b62-chat-api/r2.json")
    )
    with pytest.raises(rehearsal.RehearsalError) as refusal:
        rehearsal.guard_target(config)
    assert str(refusal.value) == "production_target"


def test_sentinel_is_the_only_write_in_the_window(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = Env(tmp_path)
    report = _run(env)
    printed = capsys.readouterr().out
    assert report.passed
    # The runner never unfreezes: closing the window is a separate CTO action.
    assert env.sentinel.is_file()
    assert "REHEARSAL_SUMMARY=PASS" in printed
    assert "unfreeze" not in printed

    # The dry run lists the frozen paths from the classification table.
    assert len(rehearsal.DEFAULT_FROZEN_PATHS) == 4


def test_a_lagging_generation_stops_at_reflect_without_the_option(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Production D1 applying 078 of 079 leaves the copy behind the repository."""

    env = Env(tmp_path, generation_ledger=("001_auth_history.sql",))
    report = _run(env)
    printed = capsys.readouterr().out

    assert report.failed_stage == "reflect"
    assert _stages(report)[-1] == "reflect"
    assert "STAGING_DB_REFUSED reason=staging_ledger_incomplete" in printed
    assert not env.staging_db.exists()
    assert env.sentinel.is_file()


def test_apply_pending_finishes_the_rehearsal_on_a_lagging_generation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = Env(tmp_path, generation_ledger=("001_auth_history.sql",))
    report = _run(env, apply_pending=True)
    printed = capsys.readouterr().out

    assert report.passed is True
    assert _stages(report) == list(rehearsal.STAGE_ORDER)
    assert "STAGING_DB_PENDING_APPLIED count=1 requested=YES names=002_projects.sql" in printed
    assert "STAGING_DB_FROM_GENERATION=READY" in printed
    assert "CHAT_COPY_PARITY=MATCH" in printed

    applied = sqlite3.connect(env.staging_db)
    try:
        names = [
            row[0]
            for row in applied.execute("SELECT name FROM d1_migrations ORDER BY id")
        ]
    finally:
        applied.close()
    assert names == list(MIGRATIONS)


def test_the_option_travels_to_the_reflect_command_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = Env(tmp_path)
    assert rehearsal.main(env.argv("--dry-run")) == 0
    without = [
        line for line in capsys.readouterr().out.splitlines() if "stage=reflect" in line
    ]
    assert len(without) == 1
    assert "--apply-pending" not in without[0]

    assert rehearsal.main(env.argv("--dry-run", "--apply-pending")) == 0
    with_flag = [
        line for line in capsys.readouterr().out.splitlines() if "stage=reflect" in line
    ]
    assert len(with_flag) == 1
    assert with_flag[0].endswith("--apply-pending")
    assert "--migrations-dir" in with_flag[0] and "--force" in with_flag[0]
    assert not env.staging_db.exists()


def test_apply_pending_uses_the_reflect_match_instead_of_a_post_apply_drift(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A pending migration that changes rows is not a window DRIFT."""

    env = Env(tmp_path, generation_ledger=("001_auth_history.sql",))
    (env.migrations / "002_projects.sql").write_text(
        "UPDATE users SET name = 'migrated' WHERE id = 'u0';\n", encoding="utf-8"
    )

    report = _run(env, apply_pending=True)
    printed = capsys.readouterr().out

    assert report.passed is True
    parity_stage = [stage for stage in report.stages if stage.stage == "parity"][0]
    assert parity_stage.skipped is True
    assert "REHEARSAL_STAGE=parity RESULT=SKIPPED" in printed
    assert "REHEARSAL_PARITY=EVIDENCE=reflect_pre_apply" in printed
    assert "STAGING_DB_PENDING_APPLIED count=1" in printed
    assert "CHAT_COPY_PARITY=MATCH" in printed

    applied = sqlite3.connect(env.staging_db)
    try:
        assert applied.execute("SELECT name FROM users WHERE id = 'u0'").fetchone()[0] == "migrated"
    finally:
        applied.close()


def test_apply_pending_needs_the_pre_apply_match_in_the_reflect_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def short_reflect(argv, timeout):
        if "chat_staging_db_from_generation.py" in argv[1]:
            # Health and pending counts, but the pre-apply parity verdict is gone.
            return 0, "STAGING_DB_FROM_GENERATION=READY\nSTAGING_DB_PENDING_APPLIED count=1"
        return 0, "CHAT_COPY_PARITY=MATCH"

    monkeypatch.setattr(rehearsal, "_run_child", short_reflect)
    env = Env(tmp_path)

    report = _run(env, apply_pending=True)
    printed = capsys.readouterr().out

    assert report.failed_stage == "reflect"
    assert "verdict_token_missing" in report.stages[-1].detail
    assert "REHEARSAL_STAGE=parity" not in printed
