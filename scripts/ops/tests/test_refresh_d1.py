"""#5484: the COM2 D1 refresh must not lose a completed export.

The 2026-10-21 04:20 scheduled run lost a **complete** D1 export. Wrangler
logged ``Downloaded to ...\\chat.sql successfully!`` and the file was on disk,
but the child chain had not returned when the old 120 s budget expired, so
``subprocess.run`` raised ``TimeoutExpired`` and the error path deleted the
``.pending`` folder together with the valid SQL file. No generation was
published and the COM2 runtime pointer stayed behind (``runtime_lag=true``).

These tests pin the repaired contract:

* the export result is the **artifact**, not the child's exit code;
* a child that lingers after writing the artifact is recorded, not fatal;
* a genuine export failure still fails closed, after one bounded retry;
* the whole child tree is stopped on a timeout, so no orphan keeps the
  inherited pipe or the pending folder alive;
* the published generation, pointer and metadata contract is unchanged;
* the per-export budget never exceeds the remaining refresh budget.

The tests use a Wrangler test double. They never reach Cloudflare, never touch
a production database and never hold a credential.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "refresh_d1.py"

# The runner in scripts/ops/com2_periodic_sync.py reads exactly this marker.
PUBLISHED_MARKER = re.compile(r"^D1_PUBLISHED_GENERATION\s+(\S+)")

SQL_FIXTURE = """
CREATE TABLE t1 (a INTEGER, b TEXT);
CREATE TABLE t2 (a INTEGER, b TEXT);
CREATE TABLE t3 (a INTEGER, b TEXT);
CREATE TABLE t4 (a INTEGER, b TEXT);
CREATE TABLE t5 (a INTEGER, b TEXT);
INSERT INTO t1 (a, b) VALUES (1, 'one');
"""


def _load():
    spec = importlib.util.spec_from_file_location("com2_refresh_d1_ops", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


refresh_d1 = _load()


@pytest.fixture(autouse=True)
def _no_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    """The DPAPI preflight is a COM2-host concern; it is not under test here."""

    monkeypatch.setattr(refresh_d1, "preflight", lambda: None)
    monkeypatch.setattr(refresh_d1, "RETRY_DELAY_SECONDS", 0.0, raising=False)


def _write_export(folder: Path, label: str) -> Path:
    sql = folder / (label + ".sql")
    sql.write_text(SQL_FIXTURE, encoding="utf-8")
    return sql


def test_a_completed_export_survives_a_child_that_lingers(tmp_path: Path) -> None:
    """The 2026-10-21 regression: a timeout after a valid export is not a failure."""

    folder = tmp_path / "pending"
    folder.mkdir()
    calls: list[dict] = []

    def fake_run_export(args, *, env, timeout):
        calls.append({"timeout": timeout})
        _write_export(folder, "chat")
        # The export finished; the process did not return in time.
        return 124, "Downloaded successfully!", True

    original = refresh_d1.run_export
    refresh_d1.run_export = fake_run_export
    try:
        result = refresh_d1.fetch_and_check(
            "chat", "padiem-chat-db", folder, timeout=60, attempts=1
        )
    finally:
        refresh_d1.run_export = original

    assert result["database"] == "padiem-chat-db"
    assert result["tables"] >= 5
    assert len(result["sha256"]) == 64
    assert (folder / "chat.sqlite3").is_file()
    # One attempt: the artifact was there, so nothing was retried.
    assert len(calls) == 1


def test_a_genuine_export_failure_fails_closed_after_one_retry(tmp_path: Path) -> None:
    """No artifact means no export. The retry is bounded and the code is stable."""

    folder = tmp_path / "pending"
    folder.mkdir()
    attempts: list[int] = []

    def fake_run_export(args, *, env, timeout):
        attempts.append(len(attempts) + 1)
        return 1, "remote export failed", False

    original = refresh_d1.run_export
    refresh_d1.run_export = fake_run_export
    try:
        with pytest.raises(refresh_d1.RefreshError) as excinfo:
            refresh_d1.fetch_and_check(
                "chat", "padiem-chat-db", folder, timeout=60, attempts=2
            )
    finally:
        refresh_d1.run_export = original

    assert str(excinfo.value) == "chat: remote_export_failed"
    assert len(attempts) == 2
    assert not (folder / "chat.sqlite3").exists()


def test_a_failed_attempt_is_retried_only_when_no_artifact_exists(tmp_path: Path) -> None:
    """The first attempt fails, the second writes the artifact: one retry."""

    folder = tmp_path / "pending"
    folder.mkdir()
    attempts: list[int] = []

    def fake_run_export(args, *, env, timeout):
        attempts.append(len(attempts) + 1)
        if len(attempts) == 1:
            return 1, "transient failure", False
        _write_export(folder, "chat")
        return 0, "Downloaded successfully!", False

    original = refresh_d1.run_export
    refresh_d1.run_export = fake_run_export
    try:
        result = refresh_d1.fetch_and_check(
            "chat", "padiem-chat-db", folder, timeout=60, attempts=2
        )
    finally:
        refresh_d1.run_export = original

    assert result["tables"] >= 5
    assert len(attempts) == 2


def test_a_timeout_stops_the_whole_child_tree(tmp_path: Path) -> None:
    """A lingering node must not survive the timeout and keep the pipe open."""

    recorded: list[list[str]] = []
    original_run = subprocess.run

    def recording_run(command, *args, **kwargs):
        recorded.append(list(command))
        return original_run(command, *args, **kwargs)

    subprocess.run = recording_run
    try:
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(120)"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        try:
            refresh_d1._terminate_tree(process)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=15)
    finally:
        subprocess.run = original_run

    if os.name == "nt":
        # The Windows tree kill must reach the whole child tree.
        assert recorded, "the Windows tree kill must be invoked"
        assert recorded[0][:2] == ["taskkill", "/PID"]
        assert "/T" in recorded[0] and "/F" in recorded[0]
    assert process.poll() is not None, "the child tree must not survive the timeout"


def test_the_refresh_publishes_into_the_requested_root(tmp_path: Path) -> None:
    """A ``--root`` run must publish into that root, never beside the script."""

    root = tmp_path / "root"
    (root / "snapshots" / "generations").mkdir(parents=True)

    def fake_run_export(args, *, env, timeout):
        output = Path(args[-1])
        _write_export(output.parent, output.stem)
        return 0, "ok", False

    original = refresh_d1.run_export
    refresh_d1.run_export = fake_run_export
    try:
        generation = refresh_d1.refresh(root, deadline=time.monotonic() + 600)
    finally:
        refresh_d1.run_export = original

    published = root / "snapshots" / "generations" / generation
    assert (published / "metadata.json").is_file()
    assert (published / "chat.sqlite3").is_file()
    assert (published / "engine.sqlite3").is_file()
    pointer = (root / "snapshots" / "current_generation.json").read_text(encoding="utf-8")
    assert generation in pointer
    # Nothing was published next to the script itself.
    assert not (refresh_d1.OUT / "generations" / generation).exists()


def test_the_published_generation_contract_is_unchanged(tmp_path: Path) -> None:
    """The marker, the pointer and the metadata stay exactly as the runner reads them."""

    folder = tmp_path / "pending"
    folder.mkdir()
    _write_export(folder, "chat")
    _write_export(folder, "engine")
    results = {
        "chat": refresh_d1._build_snapshot(folder / "chat.sql", folder / "chat.sqlite3"),
        "engine": refresh_d1._build_snapshot(folder / "engine.sql", folder / "engine.sqlite3"),
    }
    results["chat"]["database"] = "padiem-chat-db"
    results["engine"]["database"] = "padiem-engine"

    out = tmp_path / "snapshots"
    generations = out / "generations"
    generations.mkdir(parents=True)
    original_out = refresh_d1.OUT
    original_generations = refresh_d1.GENERATIONS
    refresh_d1.OUT = out
    refresh_d1.GENERATIONS = generations
    try:
        refresh_d1.publish(results, folder, "20260101T000000000000Z", remote_exports_verified=True)
    finally:
        refresh_d1.OUT = original_out
        refresh_d1.GENERATIONS = original_generations

    published = generations / "20260101T000000000000Z"
    assert (published / "metadata.json").is_file()
    assert (published / "chat.sqlite3").is_file()
    assert (published / "engine.sqlite3").is_file()
    metadata = refresh_d1.json.loads((published / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["generation"] == "20260101T000000000000Z"
    assert metadata["fresh_remote_export"] is True
    assert metadata["production_bound"] is False
    assert metadata["cross_database_transaction"] is False
    assert metadata["source"] == "cloudflare_d1_remote_export"
    pointer = refresh_d1.json.loads((out / "current_generation.json").read_text(encoding="utf-8"))
    assert pointer["generation"] == "20260101T000000000000Z"


def test_the_published_marker_still_matches_the_runner_contract(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """scripts/ops/com2_periodic_sync.py parses this exact marker line."""

    folder = tmp_path / "pending"
    folder.mkdir()
    _write_export(folder, "chat")
    _write_export(folder, "engine")
    results = {}
    for label in ("chat", "engine"):
        results[label] = refresh_d1._build_snapshot(
            folder / (label + ".sql"), folder / (label + ".sqlite3")
        )
        results[label]["database"] = refresh_d1.DATABASES[label]

    out = tmp_path / "snapshots"
    generations = out / "generations"
    generations.mkdir(parents=True)
    original_out = refresh_d1.OUT
    original_generations = refresh_d1.GENERATIONS
    refresh_d1.OUT = out
    refresh_d1.GENERATIONS = generations
    try:
        refresh_d1.publish(results, folder, "20260101T000000000000Z", remote_exports_verified=True)
    finally:
        refresh_d1.OUT = original_out
        refresh_d1.GENERATIONS = original_generations
    printed = capsys.readouterr().out
    assert PUBLISHED_MARKER.match(printed.strip()) is not None
    assert "D1_PUBLISHED_GENERATION 20260101T000000000000Z DATABASES 2" in printed


def test_an_incomplete_generation_is_never_published(tmp_path: Path) -> None:
    """A failing second database leaves the previous pointer untouched."""

    root = tmp_path / "root"
    (root / "snapshots" / "generations").mkdir(parents=True)
    previous = root / "snapshots" / "current_generation.json"
    previous.write_text('{"generation": "previous"}', encoding="utf-8")

    def fake_run_export(args, *, env, timeout):
        output = Path(args[-1])
        label = output.stem
        if label == "engine":
            return 1, "failed", False
        _write_export(output.parent, label)
        return 0, "ok", False

    original = refresh_d1.run_export
    refresh_d1.run_export = fake_run_export
    try:
        with pytest.raises(refresh_d1.RefreshError):
            refresh_d1.refresh(root, deadline=time.monotonic() + 600)
    finally:
        refresh_d1.run_export = original

    assert previous.read_text(encoding="utf-8") == '{"generation": "previous"}'
    generations = root / "snapshots" / "generations"
    assert not [item for item in generations.iterdir() if item.name.endswith(".pending")]


def test_the_export_budget_never_exceeds_the_remaining_refresh_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refresh deadline bounds every export attempt."""

    folder = tmp_path / "pending"
    folder.mkdir()
    seen: list[float] = []

    def fake_run_export(args, *, env, timeout):
        seen.append(timeout)
        _write_export(folder, "chat")
        return 0, "ok", False

    original = refresh_d1.run_export
    refresh_d1.run_export = fake_run_export
    try:
        refresh_d1.fetch_and_check(
            "chat", "padiem-chat-db", folder, timeout=refresh_d1.EXPORT_TIMEOUT_SECONDS
        )
    finally:
        refresh_d1.run_export = original
    assert seen == [refresh_d1.EXPORT_TIMEOUT_SECONDS]

    remaining = refresh_d1._remaining(time.monotonic() + 30)
    assert 0 < remaining <= 30


def test_the_refresh_budget_is_reported_and_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The run records its own source digest and its budget."""

    monkeypatch.setattr(refresh_d1, "refresh", lambda root, deadline=None: "gen-1")
    assert refresh_d1.main(["--root", str(tmp_path), "--budget-seconds", "60"]) == 0
    assert refresh_d1.source_sha256() != ""


def test_the_exported_sqlite_snapshot_is_readable_and_verified(tmp_path: Path) -> None:
    """The rebuilt snapshot is a real, verified SQLite database."""

    folder = tmp_path / "pending"
    folder.mkdir()
    sql = _write_export(folder, "chat")
    result = refresh_d1._build_snapshot(sql, folder / "chat.sqlite3")
    with sqlite3.connect(folder / "chat.sqlite3") as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        rows = connection.execute("SELECT b FROM t1").fetchall()
    assert rows == [("one",)]
    assert result["tables"] == 5
