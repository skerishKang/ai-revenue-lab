#!/usr/bin/env python3
"""One-command staging rehearsal for the Chat D1 cutover (#5115 step ③).

The rehearsal document
(``docs/operations/CHAT_D1_CUTOVER_WRITE_FREEZE_AND_REHEARSAL_20261031.md``) §5
lists the steps. Run by hand, a step can be skipped or its verdict misread, so
this runner calls the *existing* tools in that order and records nothing but
their own exit codes and verdict lines:

1. ``preflight``          — staging-only target guards and artifact presence.
2. ``stop_before_window`` — §4b: tick stop, WSS drain, queue consumption stop
                            confirmed by the operator.
3. ``freeze_on``          — the COM2 host sentinel file the window opens with.
4. ``freeze_probe``       — the 4 frozen GET paths answer 503 ``maintenance``
                            while ``/health`` and ``/api/auth/status`` answer 200.
5. ``snapshot_pair``      — ``chat_copy_parity`` between two D1 copies taken
                            across the observation window.
6. ``reflect``            — ``chat_staging_db_from_generation`` builds the
                            staging database from the published generation.
7. ``parity``             — ``chat_copy_parity`` between the D1 copy and the
                            staging database.
8. ``object_reference``   — ``chat_object_reference_check`` referenced keys vs
                            the mirror inventory.

No stage invents a verdict: every PASS/FAIL is the child tool's own exit code
and its own printed token. On the first failure the runner stops, prints the
rollback guidance, and runs the two rollback calls that only read
(``chat_d1_handback_gate plan`` → ``verify``). ``apply`` is never run here: the
approval for it stays with the CTO.

The runner refuses to touch production. A target address, database path,
sentinel path or queue origin that names production
(``chat.padiem.net``, ``/mnt/d/padiem/chat-com2``, ``b62-chat-api``, queue
``8797``) is rejected before anything runs; so is an address that is neither
the staging host nor loopback. ``--synthetic`` relaxes the "under the staging
data root" placement rule for tests and keeps every production refusal.

Usage:
    python .github/scripts/chat_cutover_rehearsal.py \\
        --base-url https://chat-com2-staging.padiem.net \\
        --generation-pointer D:/.../snapshots/current_generation.json \\
        --generations-dir D:/.../snapshots/generations \\
        --snapshot-a /mnt/d/padiem/chat-staging/baseline.sqlite3 \\
        --snapshot-b /mnt/d/padiem/chat-staging/window-end.sqlite3 \\
        --staging-db /mnt/d/padiem/chat-staging/chat.sqlite3 \\
        --sentinel /mnt/d/padiem/chat-staging/MAINTENANCE \\
        --mirror-inventory /mnt/d/padiem/chat-staging/r2-inventory.json \\
        --confirm-stop-tick --confirm-stop-wss --confirm-stop-queue

Exit codes: 0 every stage passed, 1 a stage failed, 2 refused (target/usage).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

EXIT_PASS = 0
EXIT_FAILED = 1
EXIT_REFUSED = 2

SCRIPTS_DIR = Path(__file__).resolve().parent
TOOLS = {
    "parity": SCRIPTS_DIR / "chat_copy_parity.py",
    "staging_db": SCRIPTS_DIR / "chat_staging_db_from_generation.py",
    "object_reference": SCRIPTS_DIR / "chat_object_reference_check.py",
    "handback": SCRIPTS_DIR / "chat_d1_handback_gate.py",
}

#: The only rehearsal target. Loopback is accepted for the local run.
STAGING_HOSTS = frozenset({"chat-com2-staging.padiem.net"})
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
STAGING_LOOPBACK_PORT = 8801
#: Production Chat and its throwaway siblings.
PRODUCTION_HOST_SUFFIXES = ("padiem.net",)
#: Strings that only appear in production targets, never in the staging root.
PRODUCTION_MARKERS = ("chat-com2", "b62-chat-api", "padiem-chat-db", "padiem-engine", "8797")
STAGING_DATA_ROOT = "/mnt/d/padiem/chat-staging"
STAGING_QUEUE_PORT = 8830
#: Production Chat and its siblings all live under this suffix.
PRODUCTION_HOST_SUFFIX = "padiem.net"

#: From CHAT_LATE_WRITE_INVENTORY_20261031.md (#6367) — the write-effect GETs.
DEFAULT_FROZEN_PATHS = (
    "/auth/google/callback",
    "/auth/lovetree/start",
    "/api/connectors/github/start",
    "/api/connectors/github/callback",
)
DEFAULT_HEALTH_PATHS = ("/health", "/api/auth/status")
MAINTENANCE_TOKEN = "maintenance"

STAGE_ORDER = (
    "preflight",
    "stop_before_window",
    "freeze_on",
    "freeze_probe",
    "snapshot_pair",
    "reflect",
    "parity",
    "object_reference",
)

STOP_CONFIRMATIONS = (
    ("stop_tick", "confirm_stop_tick", "새 예약 실행 tick 중단"),
    ("stop_wss", "confirm_stop_wss", "열린 WSS 연결 종료·드레인"),
    ("stop_queue", "confirm_stop_queue", "운영 큐(8797) 소비 중지"),
)

ROLLBACK_GUIDANCE = (
    "REHEARSAL_ROLLBACK=keep the freeze window open, use the handback plan below,",
    "REHEARSAL_ROLLBACK=then report to the CTO before unfreezing; apply needs approval",
)

class RehearsalError(Exception):
    """A fixed, public-safe refusal. Never carries a secret or row data."""


@dataclass(slots=True)
class StageResult:
    stage: str
    passed: bool
    detail: str = ""
    started_utc: str = ""
    ended_utc: str = ""
    seconds: float = 0.0
    commands: list[list[str]] = field(default_factory=list)


@dataclass(slots=True)
class RehearsalReport:
    target: str = ""
    dry_run: bool = False
    stages: list[StageResult] = field(default_factory=list)
    failed_stage: str | None = None
    rollback: list[StageResult] = field(default_factory=list)
    rollback_skipped: str = ""
    elapsed_seconds: float = 0.0

    @property
    def passed(self) -> bool:
        return self.failed_stage is None and len(self.stages) == len(STAGE_ORDER)


@dataclass(slots=True)
class Config:
    base_url: str
    staging_db: str
    sentinel: str
    generation_pointer: str
    generations_dir: str
    snapshot_a: str
    snapshot_b: str
    mirror_inventory: str
    migrations_dir: str = ""
    queue_origin: str = ""
    frozen_paths: tuple[str, ...] = DEFAULT_FROZEN_PATHS
    health_paths: tuple[str, ...] = DEFAULT_HEALTH_PATHS
    plan_out: str = ""
    timeout_seconds: float = 300.0
    synthetic: bool = False
    stop_confirmations: tuple[str, ...] = ()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _http_probe(url: str, timeout: float) -> tuple[int, str]:
    """One GET; returns ``(status, body)``. Never follows a redirect target."""

    request = urllib.request.Request(
        url, method="GET", headers={"user-agent": "chat-cutover-rehearsal/1.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status), response.read(8192).decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return int(error.code), error.read(8192).decode("utf-8", "replace")


def _run_child(argv: list[str], timeout: float) -> tuple[int, str]:
    completed = subprocess.run(
        argv, capture_output=True, text=True, timeout=timeout, check=False
    )
    return completed.returncode, (completed.stdout or "") + (completed.stderr or "")


def _marker_hits(*values: str) -> list[str]:
    hits: list[str] = []
    for value in values:
        text = str(value or "")
        lowered = text.replace("\\", "/").lower()
        for marker in PRODUCTION_MARKERS:
            if marker in lowered:
                hits.append(f"{marker} in {text}")
    return hits


def guard_target(config: Config) -> None:
    """Refuse a production (or unidentified) target before anything runs."""

    parsed = urlparse(config.base_url)
    host = (parsed.hostname or "").lower()
    if not host or parsed.scheme not in {"http", "https"}:
        raise RehearsalError("base_url_invalid")
    if host in STAGING_HOSTS:
        pass
    elif host in LOOPBACK_HOSTS:
        if not config.synthetic and (
            parsed.port != STAGING_LOOPBACK_PORT or parsed.scheme != "http"
        ):
            raise RehearsalError("unknown_target")
    elif host == PRODUCTION_HOST_SUFFIX or host.endswith("." + PRODUCTION_HOST_SUFFIX):
        raise RehearsalError("production_target")
    else:
        raise RehearsalError("unknown_target")

    hits = _marker_hits(
        config.staging_db,
        config.sentinel,
        config.plan_out,
        config.queue_origin,
    )
    if hits:
        raise RehearsalError("production_target")

    if config.queue_origin:
        queue = urlparse(config.queue_origin)
        if not queue.hostname or queue.hostname.lower() not in LOOPBACK_HOSTS:
            raise RehearsalError("queue_origin_unexpected")
        if queue.port != STAGING_QUEUE_PORT:
            raise RehearsalError(
                "queue_origin_production"
                if queue.port == 8797
                else "queue_origin_unexpected"
            )

    if not config.synthetic:
        root = Path(STAGING_DATA_ROOT)
        try:
            Path(config.staging_db).resolve().relative_to(root)
        except ValueError:
            raise RehearsalError("staging_root_outside") from None

    for name, tool in TOOLS.items():
        if not tool.is_file():
            raise RehearsalError(f"tool_missing:{name}")
    for name in (
        "generation_pointer",
        "snapshot_a",
        "snapshot_b",
        "mirror_inventory",
    ):
        if not Path(getattr(config, name)).is_file():
            raise RehearsalError(f"artifact_missing:{name}")
    if not Path(config.generations_dir).is_dir():
        raise RehearsalError("artifact_missing:generations_dir")


class Rehearsal:
    """Runs the §5 steps, in order, with the tools that already exist."""

    def __init__(self, config: Config, *, dry_run: bool = False, probe=None) -> None:
        self.config = config
        self.dry_run = dry_run
        self._probe = probe
        self.report = RehearsalReport(
            target=config.base_url,
            dry_run=dry_run,
        )
        self._started = time.monotonic()

    # -- infrastructure -------------------------------------------------

    def _probe_url(self, url: str) -> tuple[int, str]:
        probe = self._probe or _http_probe
        try:
            return probe(url, self.config.timeout_seconds)
        except OSError:
            # Unreachable is a probe failure, not a runner crash: status 0.
            return 0, ""

    def _child(self, stage: str, argv: list[str], expect: str) -> StageResult:
        """Run one existing tool and take its own exit code as the verdict."""

        result = StageResult(stage=stage, passed=False, commands=[argv])
        if self.dry_run:
            result.passed = True
            result.detail = "dry_run"
            print("REHEARSAL_COMMAND stage=%s argv=%s" % (stage, " ".join(argv)))
            return result

        result.started_utc = _utc_now()
        started = time.monotonic()
        try:
            code, output = _run_child(argv, self.config.timeout_seconds)
        except subprocess.TimeoutExpired:
            code, output = 124, ""
        result.seconds = round(time.monotonic() - started, 2)
        result.ended_utc = _utc_now()
        for line in output.splitlines():
            if line.strip():
                print("  | " + line)
        result.detail = f"exit={code} expect={expect}"
        result.passed = code == 0 and expect in output
        if not result.passed and expect not in output:
            result.detail += " verdict_token_missing"
        return result

    def _stage(self, stage: str, detail: str, passed: bool) -> StageResult:
        result = StageResult(stage=stage, passed=passed, detail=detail)
        if not self.dry_run:
            result.started_utc = _utc_now()
            result.ended_utc = result.started_utc
        return result

    # -- stages ---------------------------------------------------------

    def _preflight(self) -> StageResult:
        pending = [
            flag
            for _name, flag, _label in STOP_CONFIRMATIONS
            if flag not in self.config.stop_confirmations
        ]
        parsed = urlparse(self.config.base_url)
        return self._stage(
            "preflight",
            f"staging_target={parsed.hostname} staging_db={self.config.staging_db} "
            f"frozen_paths={len(self.config.frozen_paths)} "
            f"pending_confirmations={len(pending)}",
            True,
        )

    def _stop_before_window(self) -> StageResult:
        missing = [
            flag
            for name, flag, _label in STOP_CONFIRMATIONS
            if flag not in self.config.stop_confirmations
        ]
        if missing:
            print("REHEARSAL_STOP_CONFIRMATION_MISSING=" + ",".join(missing))
            return self._stage(
                "stop_before_window",
                "missing=" + ",".join(missing),
                False,
            )
        return self._stage(
            "stop_before_window",
            "confirmed=" + ",".join(flag for _n, flag, _l in STOP_CONFIRMATIONS),
            True,
        )

    def _freeze_on(self) -> StageResult:
        sentinel = Path(self.config.sentinel)
        if self.dry_run:
            print(f"REHEARSAL_ACTION stage=freeze_on action=create_sentinel path={sentinel}")
            return self._stage("freeze_on", f"sentinel={sentinel}", True)
        try:
            sentinel.parent.mkdir(parents=True, exist_ok=True)
            sentinel.write_text(
                "cutover rehearsal write freeze — remove to close the window\n",
                encoding="utf-8",
            )
        except OSError:
            return self._stage("freeze_on", "sentinel_unwritable", False)
        return self._stage("freeze_on", f"sentinel={sentinel} size={sentinel.stat().st_size}", True)

    def _freeze_probe(self) -> StageResult:
        if self.dry_run:
            for path in self.config.frozen_paths:
                print(f"REHEARSAL_ACTION stage=freeze_probe action=get_expect_503 path={path}")
            for path in self.config.health_paths:
                print(f"REHEARSAL_ACTION stage=freeze_probe action=get_expect_200 path={path}")
            return self._stage("freeze_probe", "dry_run", True)

        failures: list[str] = []
        for path in self.config.frozen_paths:
            status, body = self._probe_url(self.config.base_url + path)
            print(f"FREEZE_PROBE path={path} status={status}")
            if status != 503 or MAINTENANCE_TOKEN not in body:
                failures.append(f"{path}:{status}")
        for path in self.config.health_paths:
            status, _body = self._probe_url(self.config.base_url + path)
            print(f"FREEZE_PROBE path={path} status={status}")
            if status != 200:
                failures.append(f"{path}:{status}")
        detail = (
            f"frozen={len(self.config.frozen_paths)} health={len(self.config.health_paths)}"
            if not failures
            else "unexpected=" + ",".join(failures)
        )
        return self._stage("freeze_probe", detail, not failures)

    def _snapshot_pair(self) -> StageResult:
        return self._child(
            "snapshot_pair",
            [
                sys.executable, str(TOOLS["parity"]),
                "--d1", self.config.snapshot_a,
                "--com2", self.config.snapshot_b,
            ],
            "CHAT_COPY_PARITY=MATCH",
        )

    def _reflect(self) -> StageResult:
        argv = [
            sys.executable, str(TOOLS["staging_db"]),
            "--pointer", self.config.generation_pointer,
            "--generations-dir", self.config.generations_dir,
            "--out", self.config.staging_db,
            "--force",
        ]
        if self.config.migrations_dir:
            argv += ["--migrations-dir", self.config.migrations_dir]
        return self._child("reflect", argv, "STAGING_DB_FROM_GENERATION=READY")

    def _parity(self) -> StageResult:
        return self._child(
            "parity",
            [
                sys.executable, str(TOOLS["parity"]),
                "--d1", self.config.snapshot_b,
                "--com2", self.config.staging_db,
            ],
            "CHAT_COPY_PARITY=MATCH",
        )

    def _object_reference(self) -> StageResult:
        return self._child(
            "object_reference",
            [
                sys.executable, str(TOOLS["object_reference"]),
                "--db", self.config.snapshot_b,
                "--inventory", self.config.mirror_inventory,
            ],
            "CHAT_OBJECT_REFERENCE=MATCH",
        )

    # -- rollback (read-only) -------------------------------------------

    def _rollback(self) -> None:
        plan_out = self.config.plan_out or str(
            Path(self.config.staging_db).with_name("handback-plan.json")
        )
        needs = (self.config.snapshot_a, self.config.staging_db)
        missing = [path for path in needs if not Path(path).is_file()]
        if missing:
            self.report.rollback_skipped = "artifact_missing:" + ",".join(Path(p).name for p in missing)
            print(f"REHEARSAL_ROLLBACK=SKIPPED reason={self.report.rollback_skipped}")
            return

        plan = self._child(
            "rollback_plan",
            [
                sys.executable, str(TOOLS["handback"]), "plan",
                "--baseline", self.config.snapshot_a,
                "--handback", self.config.staging_db,
                "--out", plan_out,
            ],
            "CHAT_HANDBACK_PLAN=OK",
        )
        self.report.rollback.append(plan)
        print(f"REHEARSAL_ROLLBACK=PLAN result={'PASS' if plan.passed else 'FAIL'} plan={plan_out}")

        verify = self._child(
            "rollback_verify",
            [
                sys.executable, str(TOOLS["handback"]), "verify",
                "--baseline", self.config.snapshot_a,
                "--handback", self.config.staging_db,
                "--plan", plan_out,
            ],
            "CHAT_HANDBACK_VERIFY=PASS",
        )
        self.report.rollback.append(verify)
        print(f"REHEARSAL_ROLLBACK=VERIFY result={'PASS' if verify.passed else 'FAIL'}")

    # -- driver ---------------------------------------------------------

    def _run_plan(self) -> None:
        for stage in STAGE_ORDER:
            if self.dry_run:
                self._preflight()
                self._emit_plan_actions()
                return
            print("== " + stage)
            started = time.monotonic()
            result = getattr(self, "_" + stage)()
            result.seconds = round(time.monotonic() - started, 2)
            result.ended_utc = _utc_now()
            self.report.stages.append(result)
            print(
                "REHEARSAL_STAGE=%s RESULT=%s seconds=%s started=%s ended=%s detail=%s"
                % (
                    result.stage,
                    "PASS" if result.passed else "FAIL",
                    result.seconds,
                    result.started_utc,
                    result.ended_utc,
                    result.detail,
                )
            )
            if not result.passed:
                self.report.failed_stage = result.stage
                print(f"REHEARSAL_FAILED stage={result.stage} detail={result.detail}")
                for line in ROLLBACK_GUIDANCE:
                    print(line)
                self._rollback()
                return

    def _emit_plan_actions(self) -> None:
        """Dry run: print the remaining stages' actions, then stop."""

        print("REHEARSAL_ACTION stage=stop_before_window action=require_confirmations")
        print(f"REHEARSAL_ACTION stage=freeze_on action=create_sentinel path={self.config.sentinel}")
        for path in self.config.frozen_paths:
            print(f"REHEARSAL_ACTION stage=freeze_probe action=get_expect_503 path={path}")
        for path in self.config.health_paths:
            print(f"REHEARSAL_ACTION stage=freeze_probe action=get_expect_200 path={path}")
        for stage, argv, _token in self._planned_commands():
            print("REHEARSAL_COMMAND stage=%s argv=%s" % (stage, " ".join(argv)))
        self.report.stages = [
            self._stage(name, "dry_run", True) for name in STAGE_ORDER
        ]

    def _planned_commands(self) -> list[tuple[str, list[str], str]]:
        return [
            ("snapshot_pair", [sys.executable, str(TOOLS["parity"]),
                               "--d1", self.config.snapshot_a,
                               "--com2", self.config.snapshot_b], "CHAT_COPY_PARITY=MATCH"),
            ("reflect", [sys.executable, str(TOOLS["staging_db"]),
                         "--pointer", self.config.generation_pointer,
                         "--generations-dir", self.config.generations_dir,
                         "--out", self.config.staging_db, "--force",
                         *(["--migrations-dir", self.config.migrations_dir]
                            if self.config.migrations_dir else [])],
             "STAGING_DB_FROM_GENERATION=READY"),
            ("parity", [sys.executable, str(TOOLS["parity"]),
                        "--d1", self.config.snapshot_b,
                        "--com2", self.config.staging_db], "CHAT_COPY_PARITY=MATCH"),
            ("object_reference", [sys.executable, str(TOOLS["object_reference"]),
                                  "--db", self.config.snapshot_b,
                                  "--inventory", self.config.mirror_inventory],
             "CHAT_OBJECT_REFERENCE=MATCH"),
        ]

    def run(self) -> RehearsalReport:
        self._run_plan()
        self.report.elapsed_seconds = round(time.monotonic() - self._started, 2)
        if self.report.passed:
            print(
                "REHEARSAL_SUMMARY=PASS stages=%d passed=%d failed=0 elapsed=%ss"
                % (
                    len(self.report.stages),
                    sum(1 for stage in self.report.stages if stage.passed),
                    self.report.elapsed_seconds,
                )
            )
        else:
            print(
                "REHEARSAL_SUMMARY=STOPPED stages=%d passed=%d failed=%s elapsed=%ss"
                % (
                    len(self.report.stages),
                    sum(1 for stage in self.report.stages if stage.passed),
                    sum(1 for stage in self.report.stages if not stage.passed),
                    self.report.elapsed_seconds,
                )
            )
        return self.report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", required=True, help="staging Chat origin")
    parser.add_argument("--staging-db", required=True, help="staging chat.sqlite3 target")
    parser.add_argument("--sentinel", required=True, help="COM2 host freeze sentinel file")
    parser.add_argument("--generation-pointer", required=True, help="snapshots/current_generation.json")
    parser.add_argument("--generations-dir", required=True, help="snapshots/generations")
    parser.add_argument("--snapshot-a", required=True, help="D1 copy at the window start")
    parser.add_argument("--snapshot-b", required=True, help="D1 copy at the window end")
    parser.add_argument("--mirror-inventory", required=True, help="R2 mirror inventory JSON")
    parser.add_argument("--queue-origin", default="", help="staging queue origin (8830)")
    parser.add_argument("--migrations-dir", default="",
                        help="apps/padiem-chat/migrations (default: the repository set)")
    parser.add_argument("--frozen-path", action="append", dest="frozen_paths",
                        help="frozen read path (repeatable; default: classification table)")
    parser.add_argument("--health-path", action="append", dest="health_paths",
                        help="read path that must stay 200 (repeatable)")
    parser.add_argument("--plan-out", default="", help="handback plan JSON path")
    parser.add_argument("--timeout", type=float, default=300.0, help="per-stage seconds")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, run nothing")
    parser.add_argument("--synthetic", action="store_true",
                        help="allow a non-staging-root placement (tests; production stays refused)")
    parser.add_argument("--confirm-stop-tick", action="store_true",
                        help="§4b: no new scheduled execution tick")
    parser.add_argument("--confirm-stop-wss", action="store_true",
                        help="§4b: WSS gateway connections drained")
    parser.add_argument("--confirm-stop-queue", action="store_true",
                        help="§4b: production queue consumption stopped")
    parser.add_argument("--json", help="write the per-stage report as JSON")
    return parser


def config_from_args(args: argparse.Namespace) -> Config:
    confirmations = tuple(
        flag
        for _name, flag, _label in STOP_CONFIRMATIONS
        if getattr(args, flag, False)
    )
    return Config(
        base_url=args.base_url.rstrip("/"),
        staging_db=args.staging_db,
        sentinel=args.sentinel,
        generation_pointer=args.generation_pointer,
        generations_dir=args.generations_dir,
        snapshot_a=args.snapshot_a,
        snapshot_b=args.snapshot_b,
        mirror_inventory=args.mirror_inventory,
        migrations_dir=args.migrations_dir,
        queue_origin=args.queue_origin,
        frozen_paths=tuple(args.frozen_paths or DEFAULT_FROZEN_PATHS),
        health_paths=tuple(args.health_paths or DEFAULT_HEALTH_PATHS),
        plan_out=args.plan_out,
        timeout_seconds=args.timeout,
        synthetic=args.synthetic,
        stop_confirmations=confirmations,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = config_from_args(args)

    try:
        guard_target(config)
    except RehearsalError as exc:
        print(f"REHEARSAL_REFUSED reason={exc}")
        return EXIT_REFUSED

    rehearsal = Rehearsal(config, dry_run=args.dry_run)
    try:
        report = rehearsal.run()
    except (OSError, subprocess.SubprocessError):
        print("REHEARSAL_FAILED reason=rehearsal_io_error")
        return EXIT_FAILED

    if args.json:
        destination = Path(args.json)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(asdict(report), ensure_ascii=False, indent=1, sort_keys=True),
            encoding="utf-8",
        )
    return EXIT_PASS if report.passed else EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
