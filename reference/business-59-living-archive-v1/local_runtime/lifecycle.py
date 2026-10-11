"""Import/re-index lifecycle model for the B59 durable local runtime.

The nine stage names below are the complete, closed vocabulary used by the
runtime and enforced by a ``CHECK`` constraint in the ``import_stage_events``
table:

``RECEIVED``, ``VALIDATED``, ``STORED``, ``TEXT_EXTRACTED``,
``PREVIEW_RENDERED``, ``INDEXED``, ``READY``, ``PARTIAL``, ``FAILED``.

The first six are *performed* stages; the last three are terminal outcomes
recorded as the final stage event of a run:

* ``READY``   — every performed stage passed (a deferred stage is not a pass);
* ``PARTIAL`` — the original is stored and readable, but some derived stage
  failed (unsupported format, malformed extraction). Exact search is limited
  to what was actually derived.
* ``FAILED``  — the original could not be durably stored, so it is *not*
  guaranteed readable.

A stage that this slice does not perform (``PREVIEW_RENDERED``) is recorded as
``DEFERRED`` with a reason and produces no output — never a fake ``PASSED``.

Every run row persists: source id + version, implementation version, run
status, safe error code, retryable flag, whether the original remains
readable, produced outputs, run start/end, and one row per stage with its own
status, start/end, detail and outputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import json
import sqlite3
from typing import Callable, Iterable

from .source_index import _iso_timestamp


# Version of the locally implemented import/index pipeline. It is recorded on
# every run and on every derived artifact so a future change is visible in the
# durable record instead of silently rewriting history.
IMPORT_IMPLEMENTATION_VERSION = "b59-durable-local-runtime/1"


class ImportStage(StrEnum):
    """The complete stage/outcome vocabulary of one import or re-index run."""

    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    STORED = "STORED"
    TEXT_EXTRACTED = "TEXT_EXTRACTED"
    PREVIEW_RENDERED = "PREVIEW_RENDERED"
    INDEXED = "INDEXED"
    READY = "READY"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


STAGE_NAMES: tuple[str, ...] = tuple(stage.value for stage in ImportStage)
TERMINAL_STAGES: tuple[ImportStage, ...] = (
    ImportStage.READY,
    ImportStage.PARTIAL,
    ImportStage.FAILED,
)
# Stages this slice deliberately does not perform; recorded as DEFERRED.
DEFERRED_STAGE_NAMES: tuple[str, ...] = (ImportStage.PREVIEW_RENDERED.value,)
PREVIEW_DEFERRED_DETAIL = (
    "preview rendering is not implemented in this slice; recorded as deferred, "
    "not produced"
)


class StageStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    DEFERRED = "DEFERRED"


class RunStatus(StrEnum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class RunKind(StrEnum):
    IMPORT = "IMPORT"
    REINDEX = "REINDEX"


class ArtifactType(StrEnum):
    TEXT_EXTRACTION = "TEXT_EXTRACTION"
    EXACT_ANCHOR_INDEX = "EXACT_ANCHOR_INDEX"
    PREVIEW_RENDER = "PREVIEW_RENDER"


class ArtifactStatus(StrEnum):
    READY = "READY"
    FAILED = "FAILED"
    DEFERRED = "DEFERRED"


@dataclass(frozen=True, slots=True)
class StageEvent:
    stage: str
    ordinal: int
    status: str
    started_at: str
    ended_at: str
    outputs: tuple[str, ...] = ()
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ImportRun:
    """A persisted import or re-index run, reconstructed from the database."""

    run_id: str
    run_kind: str
    source_id: str
    source_version: int
    implementation_version: str
    status: str
    error_code: str | None
    retryable: bool
    original_readable: bool
    outputs: tuple[str, ...]
    started_at: str
    ended_at: str
    stages: tuple[StageEvent, ...] = ()

    def stage(self, stage: ImportStage | str) -> StageEvent | None:
        name = stage.value if isinstance(stage, ImportStage) else stage
        for event in self.stages:
            if event.stage == name:
                return event
        return None

    @property
    def failed_stages(self) -> tuple[str, ...]:
        return tuple(
            event.stage for event in self.stages if event.status == StageStatus.FAILED
        )

    @property
    def deferred_stages(self) -> tuple[str, ...]:
        return tuple(
            event.stage for event in self.stages if event.status == StageStatus.DEFERRED
        )

    @property
    def produced_outputs(self) -> tuple[str, ...]:
        """Only outputs actually produced; deferred stages contribute none."""
        return self.outputs


@dataclass(slots=True)
class StageRecorder:
    """Collects stage events with injected-clock timestamps.

    Events stay in memory until the whole run is persisted in one transaction,
    so a crashed import can never leave a half-recorded run behind.
    """

    clock: Callable[[], datetime]
    _events: list[StageEvent] = field(default_factory=list)

    def now(self) -> str:
        return _iso_timestamp(self.clock())

    def record(
        self,
        stage: ImportStage,
        status: StageStatus,
        *,
        started_at: str,
        outputs: Iterable[str] = (),
        detail: str | None = None,
    ) -> StageEvent:
        event = StageEvent(
            stage=stage.value,
            ordinal=len(self._events) + 1,
            status=status.value,
            started_at=started_at,
            ended_at=self.now(),
            outputs=tuple(outputs),
            detail=detail,
        )
        self._events.append(event)
        return event

    @property
    def events(self) -> tuple[StageEvent, ...]:
        return tuple(self._events)

    @property
    def produced_outputs(self) -> tuple[str, ...]:
        seen: list[str] = []
        for event in self._events:
            if event.status != StageStatus.PASSED:
                continue
            for output in event.outputs:
                if output not in seen:
                    seen.append(output)
        return tuple(seen)


def persist_run(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    run_kind: RunKind,
    source_id: str,
    source_version: int,
    implementation_version: str,
    status: RunStatus,
    error_code: str | None,
    retryable: bool,
    original_readable: bool,
    outputs: Iterable[str],
    started_at: str,
    ended_at: str,
    stages: Iterable[StageEvent],
) -> None:
    """Insert the run and its stage events inside the caller's transaction."""
    connection.execute(
        """
        INSERT INTO import_runs (
            run_id, run_kind, source_id, source_version, implementation_version,
            status, error_code, retryable, original_readable, outputs,
            started_at, ended_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            run_kind.value,
            source_id,
            int(source_version),
            implementation_version,
            status.value,
            error_code,
            1 if retryable else 0,
            1 if original_readable else 0,
            json.dumps(list(outputs)),
            started_at,
            ended_at,
        ),
    )
    for event in stages:
        connection.execute(
            """
            INSERT INTO import_stage_events (
                run_id, stage, ordinal, status, started_at, ended_at, detail, outputs
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                event.stage,
                event.ordinal,
                event.status,
                event.started_at,
                event.ended_at,
                event.detail,
                json.dumps(list(event.outputs)),
            ),
        )


def _row_to_run(row: sqlite3.Row, stages: tuple[StageEvent, ...]) -> ImportRun:
    return ImportRun(
        run_id=row["run_id"],
        run_kind=row["run_kind"],
        source_id=row["source_id"],
        source_version=row["source_version"],
        implementation_version=row["implementation_version"],
        status=row["status"],
        error_code=row["error_code"],
        retryable=bool(row["retryable"]),
        original_readable=bool(row["original_readable"]),
        outputs=tuple(json.loads(row["outputs"])),
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        stages=stages,
    )


def _load_stages(connection: sqlite3.Connection, run_id: str) -> tuple[StageEvent, ...]:
    rows = connection.execute(
        """
        SELECT stage, ordinal, status, started_at, ended_at, detail, outputs
        FROM import_stage_events
        WHERE run_id = ?
        ORDER BY ordinal
        """,
        (run_id,),
    ).fetchall()
    return tuple(
        StageEvent(
            stage=row["stage"],
            ordinal=row["ordinal"],
            status=row["status"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            outputs=tuple(json.loads(row["outputs"])),
            detail=row["detail"],
        )
        for row in rows
    )


def load_run(connection: sqlite3.Connection, run_id: str) -> ImportRun:
    """Load one run and its stages; raises ``KeyError`` when unknown."""
    row = connection.execute(
        "SELECT * FROM import_runs WHERE run_id = ?", (run_id,)
    ).fetchone()
    if row is None:
        raise KeyError(run_id)
    return _row_to_run(row, _load_stages(connection, run_id))


def runs_for(
    connection: sqlite3.Connection,
    source_id: str | None = None,
    source_version: int | None = None,
) -> tuple[ImportRun, ...]:
    """Load runs in deterministic order, optionally filtered."""
    clauses: list[str] = []
    parameters: list[object] = []
    if source_id is not None:
        clauses.append("source_id = ?")
        parameters.append(source_id)
    if source_version is not None:
        clauses.append("source_version = ?")
        parameters.append(int(source_version))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = connection.execute(
        f"""
        SELECT * FROM import_runs
        {where}
        ORDER BY source_id, source_version, started_at, run_id
        """,
        parameters,
    ).fetchall()
    return tuple(
        _row_to_run(row, _load_stages(connection, row["run_id"])) for row in rows
    )


def run_record_exists(connection: sqlite3.Connection, run_id: str) -> bool:
    row = connection.execute("SELECT 1 FROM import_runs WHERE run_id = ?", (run_id,)).fetchone()
    return row is not None


def unique_run_id(connection: sqlite3.Connection, base: str) -> str:
    """Return ``base`` or a deterministic ``base:2``, ``base:3``… variant.

    Ids are deterministic for a given database state, and an existing run is
    never overwritten by a later run that happens to hash identically.
    """
    candidate = base
    suffix = 1
    while run_record_exists(connection, candidate):
        suffix += 1
        candidate = f"{base}:{suffix}"
    return candidate


def terminal_status_for(passed: bool, original_readable: bool) -> RunStatus:
    """Map stage results to the terminal outcome recorded for the run."""
    if not original_readable:
        return RunStatus.FAILED
    return RunStatus.READY if passed else RunStatus.PARTIAL


def terminal_stage_for(status: RunStatus) -> ImportStage:
    """The terminal stage event name for a run status (values are identical)."""
    return ImportStage(status.value)


def terminal_stage_status_for(status: RunStatus) -> StageStatus:
    """A run only *passes* when nothing failed; PARTIAL/FAILED record FAILED."""
    return StageStatus.PASSED if status is RunStatus.READY else StageStatus.FAILED


__all__ = [
    "ArtifactStatus",
    "ArtifactType",
    "DEFERRED_STAGE_NAMES",
    "IMPORT_IMPLEMENTATION_VERSION",
    "ImportRun",
    "ImportStage",
    "PREVIEW_DEFERRED_DETAIL",
    "RunKind",
    "RunStatus",
    "STAGE_NAMES",
    "StageEvent",
    "StageRecorder",
    "StageStatus",
    "TERMINAL_STAGES",
    "load_run",
    "persist_run",
    "run_record_exists",
    "runs_for",
    "terminal_stage_for",
    "terminal_stage_status_for",
    "terminal_status_for",
    "unique_run_id",
]
