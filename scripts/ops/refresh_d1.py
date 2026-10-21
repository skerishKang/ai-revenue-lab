#!/usr/bin/env python3
"""Refresh two Cloudflare D1 snapshots as one immutable COM2 generation.

This is the version-controlled source of the COM2 operational ``refresh_d1.py``
that ``scripts/ops/com2_periodic_sync.py`` executes in the COM2
``storage-migration`` root. The deployed COM2 copy keeps the file name
``refresh_d1.py``; the deployed bytes are this file.

The Cloudflare exports are read-only and run sequentially. The generation is
consistent as a published local pair, but it is not a distributed point-in-time
transaction across the remote D1 databases.

Wrangler is launched through the COM2 Windows DPAPI secret store
(``infrastructure/secret-store/store.py``). ``store.py run`` decrypts the stored
``CLOUDFLARE_API_TOKEN`` with the current user DPAPI profile and injects it into
the child process environment only. The token therefore never appears in argv,
in stdout/stderr captured here, or in any new plaintext file.

#5484: an export is judged by its artifact, not by the child's exit code.

The 2026-10-21 04:20 scheduled run lost a **complete** D1 export. The wrangler
log for that run records ``Downloaded to ...\\chat.sql successfully!`` 7.9 s
after the export started, but the child chain had not returned when the old
120 s budget expired, so ``subprocess.run`` raised ``TimeoutExpired`` and the
error path deleted the ``.pending`` folder together with the valid SQL file.
No generation was published and the COM2 runtime pointer stayed one generation
behind (``runtime_lag=true``).

The measured cause is process lifecycle, not the export: on 2026-10-21 the same
export completed in 6.0 s (1.48 MB) and the same wrapper chain starts in 1.2 s,
while the failing run spent ~61 s before wrangler even started and then failed
to exit for the rest of its budget. The export is therefore bounded, retried
once, and - most importantly - **a validated artifact is never discarded**
because the process lingered.

The budgets below are sized from measurement, not guessed:

* ``COM2_D1_EXPORT_TIMEOUT_SECONDS`` (default 240 s) bounds one export attempt.
  The measured export cost is 3 s (engine) / 6 s (chat) and the observed
  pathological run needed ~120 s end to end, so 240 s covers a slow but
  progressing export while still bounding a true hang.
* ``COM2_D1_REFRESH_BUDGET_SECONDS`` (default 840 s) bounds the whole refresh,
  which stays inside the caller's 900 s step budget with room for the publish.

A timeout is therefore no longer a correctness dependency: the export result is
the SQL file plus its integrity check.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "snapshots"
GENERATIONS = OUT / "generations"
DATABASES = {"chat": "padiem-chat-db", "engine": "padiem-engine"}
WRANGLER = r"D:\cli\wrangler.cmd"
DPAPI_STORE = r"D:\PADIEM-Servers\infrastructure\secret-store\store.py"
SECRET_NAME = "CLOUDFLARE_API_TOKEN"
# Non-secret COM2 Cloudflare account identifier. It is already recorded in the
# local wrangler.*.toml files; Wrangler needs it because a scoped User API Token
# cannot auto-resolve the account via the /memberships endpoint. Overridable by
# the CLOUDFLARE_ACCOUNT_ID environment variable.
ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID") or "9be14bb7b8974e65d0afba647ab16932"

#: One export attempt budget. See the module docstring for the measurement.
EXPORT_TIMEOUT_SECONDS = float(os.environ.get("COM2_D1_EXPORT_TIMEOUT_SECONDS", "240"))
#: Whole-refresh budget. Stays inside the caller's 900 s step budget.
REFRESH_BUDGET_SECONDS = float(os.environ.get("COM2_D1_REFRESH_BUDGET_SECONDS", "840"))
#: A genuine export failure is retried once; the artifact is never retried.
EXPORT_ATTEMPTS = 2
#: Pause between a failed attempt and its retry.
RETRY_DELAY_SECONDS = float(os.environ.get("COM2_D1_RETRY_DELAY_SECONDS", "5"))
#: The preflight secret-name check is cheap and stays independent of the budget.
PREFLIGHT_TIMEOUT_SECONDS = 60


class RefreshError(RuntimeError):
    """Stable failure code. The message never carries a secret or customer data."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _generation_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def wrangler_command(*arguments: str) -> list:
    """Build a Wrangler invocation routed through the DPAPI secret store.

    ``store.py run <exe> <args...>`` decrypts the registered secrets and passes
    them to the child process as environment variables. The Cloudflare token is
    never part of the argument vector, so it cannot leak through process
    listings, logs, or command history.
    """
    return [sys.executable, DPAPI_STORE, "run", WRANGLER, *arguments]


def child_environment() -> dict:
    """Environment for the DPAPI-routed Wrangler call (no secret values here).

    Only the non-secret account selector is added; ``store.py run`` injects the
    decrypted CLOUDFLARE_API_TOKEN into the grandchild Wrangler process itself.
    """
    env = os.environ.copy()
    env["CLOUDFLARE_ACCOUNT_ID"] = ACCOUNT_ID
    return env


def preflight() -> None:
    """Fail closed before touching any snapshot if the token path is unusable.

    ``store.py list`` prints only secret *names* (never values), so this check
    is safe to run and gives a clear early error when the DPAPI store or the
    Cloudflare token slot is missing.
    """
    if not Path(DPAPI_STORE).is_file():
        raise RefreshError("dpapi_store_missing")
    listed = subprocess.run([sys.executable, DPAPI_STORE, "list"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            encoding="utf-8", errors="replace",
                            timeout=PREFLIGHT_TIMEOUT_SECONDS)
    if listed.returncode != 0:
        raise RefreshError("dpapi_store_unavailable")
    if SECRET_NAME not in listed.stdout.split():
        raise RefreshError("dpapi_secret_missing:" + SECRET_NAME)


def _terminate_tree(process: subprocess.Popen) -> None:
    """Stop the whole child tree so no orphan keeps the inherited pipe alive.

    ``store.py run`` hands the command to ``wrangler.cmd``, which hands it to
    node. Killing only the direct child leaves the node process holding the
    inherited stdout pipe, so the caller keeps waiting for a pipe EOF that never
    arrives, and an orphan can keep writing into the pending folder.
    """
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=60, check=False)
        else:
            process.terminate()
    except Exception:  # noqa: BLE001 - teardown must never mask the real error
        return
    try:
        process.wait(timeout=30)
    except Exception:  # noqa: BLE001
        try:
            process.kill()
            process.wait(timeout=15)
        except Exception:  # noqa: BLE001
            pass


def run_export(
    args: Sequence[str],
    *,
    env: Mapping[str, str],
    timeout: float,
) -> tuple[int, str, bool]:
    """Run one export attempt and report ``(exit_code, output, timed_out)``.

    A timeout is reported as a result, not raised: the caller decides success
    from the artifact, because the export writes its file before the wrangler
    process is finished.
    """
    process = subprocess.Popen(
        list(args),
        env=dict(env),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        stdout, _ = process.communicate(timeout=max(1.0, timeout))
        return process.returncode, stdout or "", False
    except subprocess.TimeoutExpired:
        _terminate_tree(process)
        try:
            stdout, _ = process.communicate(timeout=30)
        except Exception:  # noqa: BLE001
            stdout = ""
        return 124, stdout or "", True


def _build_snapshot(sql: Path, db: Path) -> dict:
    """Rebuild the SQLite database from the export and verify its integrity."""
    try:
        with closing(sqlite3.connect(db)) as connection:
            connection.execute("PRAGMA journal_mode=OFF")
            connection.execute("PRAGMA synchronous=OFF")
            connection.executescript(sql.read_text(encoding="utf-8-sig"))
            connection.commit()
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            tables = connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()[0]
    except sqlite3.Error as error:
        raise RefreshError("export_sqlite_build_failed:" + type(error).__name__) from None
    if integrity != "ok" or tables < 5:
        raise RefreshError("invalid_snapshot")
    return {"tables": tables, "bytes": db.stat().st_size,
            "sha256": hashlib.sha256(db.read_bytes()).hexdigest()}


def fetch_and_check(
    label: str,
    remote: str,
    folder: Path,
    *,
    timeout: float,
    attempts: int = EXPORT_ATTEMPTS,
) -> dict:
    """Export one remote database and publish its verified local snapshot.

    Success is the validated artifact. A child that lingers after the export
    already wrote its file is not a failure, and a failed attempt is retried
    once without touching the published generations.
    """
    sql = folder / (label + ".sql")
    db = folder / (label + ".sqlite3")
    args = wrangler_command("d1", "export", remote, "--remote", "--output", str(sql))
    started = time.monotonic()
    exit_code = 124
    output = ""
    timed_out = False
    for attempt in range(1, max(1, attempts) + 1):
        exit_code, output, timed_out = run_export(
            args, env=child_environment(), timeout=timeout
        )
        if sql.is_file():
            # The artifact decides. A lingering child is recorded, not fatal.
            break
        if attempt < attempts:
            print(
                "D1_EXPORT_RETRY label=%s attempt=%d exit=%s timed_out=%s"
                % (label, attempt, exit_code, str(timed_out).lower()),
                flush=True,
            )
            if RETRY_DELAY_SECONDS > 0:
                time.sleep(RETRY_DELAY_SECONDS)
    seconds = round(time.monotonic() - started, 1)
    if not sql.is_file():
        raise RefreshError(label + ": remote_export_failed")
    print(
        "D1_EXPORT label=%s seconds=%s exit=%s timed_out=%s bytes=%s"
        % (label, seconds, exit_code, str(timed_out).lower(), sql.stat().st_size),
        flush=True,
    )
    result = _build_snapshot(sql, db)
    result["database"] = remote
    return result


def publish(
    results: dict,
    folder: Path,
    generation: str,
    *,
    out: Path | None = None,
    generations: Path | None = None,
    remote_exports_verified: bool = False,
) -> None:
    for label in DATABASES:
        if label not in results or not (folder / (label + ".sqlite3")).is_file():
            raise RefreshError("incomplete_generation")
    out = Path(out) if out is not None else OUT
    generations = Path(generations) if generations is not None else GENERATIONS
    folder.rename(generations / generation)
    metadata = {"generation": generation, "databases": results, "captured_utc": generation,
                "fresh_remote_export": remote_exports_verified,
                "production_bound": False,
                "cross_database_transaction": False,
                "source": "cloudflare_d1_remote_export" if remote_exports_verified else "offline_contract_test"}
    (generations / generation / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    marker = out / "current_generation.json"
    temp = out / "current_generation.next.json"
    temp.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    os.replace(temp, marker)
    print("D1_PUBLISHED_GENERATION", generation, "DATABASES", len(results))


def _remaining(deadline: float | None) -> float:
    if deadline is None:
        return EXPORT_TIMEOUT_SECONDS
    return max(0.0, deadline - time.monotonic())


def refresh(root: Path, *, deadline: float | None = None) -> str:
    """Run the whole refresh and publish one generation. Returns the generation id."""
    root = Path(root)
    out = root / "snapshots"
    generations = out / "generations"
    preflight()
    generations.mkdir(parents=True, exist_ok=True)
    now = _generation_id()
    pending = generations / (now + ".pending")
    pending.mkdir()
    try:
        results: dict[str, dict] = {}
        for name, remote in DATABASES.items():
            budget = _remaining(deadline)
            if budget <= 0:
                raise RefreshError("refresh_budget_exhausted:" + name)
            results[name] = fetch_and_check(
                name, remote, pending, timeout=min(EXPORT_TIMEOUT_SECONDS, budget)
            )
        publish(
            results,
            pending,
            now,
            out=out,
            generations=generations,
            remote_exports_verified=True,
        )
    except BaseException:
        shutil.rmtree(pending, ignore_errors=True)
        raise
    return now


def source_sha256() -> str:
    """SHA-256 of this file, so a run records which source produced it."""
    try:
        return hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest()
    except OSError:
        return ""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root",
        default=None,
        help="COM2 storage-migration root that holds snapshots/ (default: this file's folder)",
    )
    parser.add_argument(
        "--budget-seconds",
        type=float,
        default=None,
        help="total refresh budget (default: COM2_D1_REFRESH_BUDGET_SECONDS)",
    )
    args = parser.parse_args(argv)
    root = Path(args.root).resolve() if args.root else ROOT
    budget = args.budget_seconds if args.budget_seconds is not None else REFRESH_BUDGET_SECONDS
    print(
        "D1_REFRESH_SOURCE_SHA256=%s root=%s budget_seconds=%s"
        % (source_sha256(), root, budget),
        flush=True,
    )
    deadline = time.monotonic() + budget
    try:
        refresh(root, deadline=deadline)
    except RefreshError as error:
        print("D1_REFRESH_FAILED code=%s" % error, flush=True)
        return 1
    except Exception as error:  # noqa: BLE001 - a stable code is the contract
        print("D1_REFRESH_FAILED code=%s" % type(error).__name__, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
