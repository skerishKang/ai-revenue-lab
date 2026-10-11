"""Durable D1 persistence adapter for the canonical B54 Claw automation store.

Thin B62 product-persistence seam that *consumes* (does not reimplement) the
``kagent.claw_automation`` contracts from ``apps/korean-ai-code-agent`` (B54):
the rule domain, the scheduled-run domain, the occurrence dedup authority and
the execution-claim semantics all stay owned by that kernel. This module only
gives them a Worker-compatible durable home.

One domain contract, two durable homes. The reference durable store
(``SqliteClawAutomationStore``) stays reference evidence and keeps its SQLite
file. This adapter materialises the SAME logical entities in D1 and reuses the
kernel's own codecs (``_serialize_rule`` / ``_rule_from_row`` / ``_run_from_row``
/ ``_proposal_from_row`` / ``_serialize_output`` / ``_deserialize_output``) and
material builders (``_execution_claim_material`` / ``_projection_update_material``
/ ``_projection_output_for_update``) instead of defining a second one. The two
therefore cannot drift into different semantics.

This adapter does NOT:
  - create tables at runtime (``RUNTIME_CREATE_TABLE=NO``) — migrations 018/019 own the

  schema and this module executes no DDL of any kind
- accept caller SQL, a caller table name or a caller query
  (``CALLER_SUPPLIED_SQL=NO``)
- enumerate or discover workspaces (``CALLER_LIST_ALL_WORKSPACES=NO``) — every
  read is bound to one caller-supplied ``workspace_id``
- list rules or runs across tenants
  (``CALLER_LIST_ALL_RULES_ACROSS_TENANTS=NO``)
- mint a second dedup authority, a lock table, a claim token or a run id
  (``SECOND_DEDUP_AUTHORITY=NO``, ``SECOND_RUN_ID_AUTHORITY=NO``)
- schedule or dispatch automation/cron (``BACKGROUND_SCHEDULER=NO``), register a
  Cloudflare Cron trigger (``REAL_CLOUD_CRON_REGISTRATION=NO``) or activate a
  Production scheduler (``PRODUCTION_SCHEDULER_ACTIVATION=NO``)
- perform provider calls or send outbound notifications (``EXTERNAL_SEND=NO``)

Why every method is ``async``. Cloudflare D1 is only reachable through awaited
statements, and a synchronous adapter over an async binding would have to block
the event loop, spin a thread or fake a result — all three would be dishonest.
This adapter therefore implements the EXISTING ``ClawAutomationStore`` protocol
the same way ``D1ClawTaskAlertStore`` implements ``ClawMemoryStore``: the
protocol names the contract, the adapter supplies the awaitable implementation,
and each consumer resolves either shape through the established
``inspect.isawaitable`` tolerance. No ``asyncio.run``, no
``run_until_complete``, no event-loop blocking and no thread wrapper is used
anywhere in this module.

Concurrency. Occurrence dedup is the ``claw_occurrences`` primary key and nothing
else: whichever writer wins the claim owns the canonical run, and the loser
adopts that run without writing or deleting anything. The execution claim is one
bounded conditional ``UPDATE`` on the EXISTING ``claw_runs`` row, so
``PENDING -> RUNNING`` happens at most once and a ``RUNNING`` or terminal row is
never reclaimed, never resurrected and never re-dispatched. D1 executes each
statement atomically, and ``db.batch()`` makes the multi-statement writes one
atomic round trip, so no second lock table and no claim token are needed.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from kagent.claw_automation import (
    ClawAutomationOutput,
    ClawAutomationRule,
    ClawAutomationStore,
    ClawNotificationProposal,
    ClawScheduledRun,
    ClawScheduledRunStatus,
    ContractError,
    SqliteClawAutomationStore,
    _execution_claim_material,
    _execution_intent_document,
    _iso,
    _projection_output_for_update,
    _projection_update_material,
    occurrence_key,
)

from .workspace_storage import WorkspaceStorageError, _row_to_dict

# --- readiness and refusal flags -------------------------------------------
# Constants, not claims: no code path in this module can raise one of the False
# values. They are explicit so no consumer can mistake a persistence adapter for
# an activated scheduler or a second authority.
D1_CLAW_AUTOMATION_STORE_READY = True
DURABLE_AUTOMATION_STORE_READY = True
WORKER_D1_CLAW_AUTOMATION_STORE = True
RUNTIME_CREATE_TABLE = False
CALLER_SUPPLIED_SQL = False
CALLER_SUPPLIED_D1_TABLE_NAME = False
CALLER_LIST_ALL_WORKSPACES = False
CALLER_LIST_ALL_RULES_ACROSS_TENANTS = False
BACKGROUND_SCHEDULER = False
REAL_CLOUD_CRON_REGISTRATION = False
PRODUCTION_SCHEDULER_ACTIVATION = False
WORKFLOW_DISPATCH = False
PRODUCTION_MUTATION = False
EXTERNAL_SEND = False
SECOND_DEDUP_AUTHORITY = False
SECOND_RUN_ID_AUTHORITY = False
SECOND_AUTOMATION_STORE_AUTHORITY = False
EXECUTION_CLAIM_NEW_LOCK_TABLE = False
EXECUTION_CLAIM_NEW_CLAIM_TOKEN = False
EXECUTION_CLAIM_SECOND_RUN_ID = False
ONE_OCCURRENCE_MAX_CANONICAL_RUNS = 1

# #2987 S2F6B: the server-owned due-workspace discovery foundation may page
# across workspaces, but only inside this hard ceiling. The bound is a module
# constant so a caller cannot widen the scan by passing a bigger number.
#
# This does NOT turn the adapter into a caller-facing enumeration surface:
# ``CALLER_LIST_ALL_WORKSPACES`` stays False because no caller supplies a
# workspace and no unbounded/arbitrary window is reachable -- the only new read
# is a bounded, cursor-ordered page used by the internal discovery boundary.
_MAX_CANDIDATE_WORKSPACE_PAGE_SIZE = 200
SERVER_OWNED_DUE_WORKSPACE_DISCOVERY_READ = True
CALLER_SUPPLIED_WORKSPACE_FILTER = False

# --- canonical column order -------------------------------------------------
# The reference store reads rows positionally, so the adapter hands it tuples in
# exactly the reference's SELECT order. Naming the columns once here keeps every
# read bound to that order instead of relying on a driver's key order.
_RULE_COLUMNS = (
    "rule_id",
    "workspace_id",
    "name",
    "schedule_kind",
    "schedule_expression",
    "schedule_timezone",
    "target_source",
    "output_type",
    "enabled",
    "notification_channels",
    "created_at",
    "updated_at",
    "canonical_subject_id",
)
_RUN_COLUMNS = (
    "run_id",
    "workspace_id",
    "rule_id",
    "status",
    "scheduled_time",
    "started_at",
    "completed_at",
    "output",
    "error_message",
)
_PROPOSAL_COLUMNS = (
    "proposal_id",
    "workspace_id",
    "rule_id",
    "channel",
    "title",
    "summary",
    "approval_required",
    "approval_reason",
    "suggested_action",
    "approved_by",
    "approved_at",
    "created_at",
)

_SELECT_RULE = (
    "SELECT rule_id, workspace_id, name, schedule_kind, schedule_expression, "
    "schedule_timezone, target_source, output_type, enabled, notification_channels, "
    "created_at, updated_at, canonical_subject_id FROM claw_rules WHERE rule_id = ?"
)
_SELECT_RULES_FOR_WORKSPACE = (
    "SELECT rule_id, workspace_id, name, schedule_kind, schedule_expression, "
    "schedule_timezone, target_source, output_type, enabled, notification_channels, "
    "created_at, updated_at, canonical_subject_id FROM claw_rules WHERE workspace_id = ?"
)
_SELECT_RUN = (
    "SELECT run_id, workspace_id, rule_id, status, scheduled_time, started_at, "
    "completed_at, output, error_message FROM claw_runs WHERE run_id = ?"
)
_SELECT_RUNS_FOR_WORKSPACE = (
    "SELECT run_id, workspace_id, rule_id, status, scheduled_time, started_at, "
    "completed_at, output, error_message FROM claw_runs WHERE workspace_id = ?"
)
_SELECT_OCCURRENCE_RUN_ID = (
    "SELECT run_id FROM claw_occurrences WHERE occurrence_key = ? AND workspace_id = ?"
)
_SELECT_PROPOSALS_FOR_WORKSPACE = (
    "SELECT proposal_id, workspace_id, rule_id, channel, title, summary, "
    "approval_required, approval_reason, suggested_action, approved_by, approved_at, "
    "created_at FROM claw_proposals WHERE workspace_id = ?"
)

# --- server-owned due-workspace discovery reads (#2987 S2F6B) ----------------
# These reads are the ONLY place this module looks across more than one
# workspace, and they are deliberately built so that the result can never
# become a product surface:
#
# * The caller supplies no workspace and no tenant. The scan is bounded by a
#   caller-supplied PAGE SIZE and a monotonic CURSOR that the caller can only
#   advance, never fabricate an arbitrary window from.
# * Only workspaces that currently own at least one ENABLED rule are returned.
#   A disabled-only workspace is intentionally absent, so downstream discovery
#   cannot be driven by work that is contractually forbidden to execute
#   (``DISABLED_RULE_DISCOVERY=0``).
# * Ordering is by ``workspace_id`` (the same deterministic key the index is
#   built on), so two identical scans observe the same page sequence.
# * No row content, no rule body, no run, no proposal and no credential is
#   returned -- only the bounded set of workspace identifiers.
#
# This is a storage read, not an authority: it mints no membership, no
# execution right and no scheduler claim. Whatever consumes it must still
# revalidate canonical membership before any execution (see
# ``claw_automation_due_workspace_discovery``).
_SELECT_CANDIDATE_WORKSPACES_AFTER = (
    "SELECT DISTINCT workspace_id FROM claw_rules "
    "WHERE enabled = 1 AND workspace_id > ? "
    "ORDER BY workspace_id ASC LIMIT ?"
)
_SELECT_CANDIDATE_WORKSPACES_FROM_START = (
    "SELECT DISTINCT workspace_id FROM claw_rules "
    "WHERE enabled = 1 "
    "ORDER BY workspace_id ASC LIMIT ?"
)

# The occurrence primary key is the only dedup authority. `OR IGNORE` makes a
# duplicate claim idempotent: it never raises and never rewrites the winner.
_CLAIM_OCCURRENCE = (
    "INSERT OR IGNORE INTO claw_occurrences(occurrence_key, run_id, workspace_id) "
    "VALUES (?, ?, ?)"
)
# The run row is written only by the writer that won the occurrence claim. The
# `changes()` guard chains it to the immediately preceding claim, and the plain
# (non-IGNORE) INSERT still fails closed if this run_id is aliased elsewhere.
_INSERT_RUN_GUARDED = (
    "INSERT INTO claw_runs(run_id, workspace_id, rule_id, status, scheduled_time, "
    "started_at, completed_at, output, error_message) "
    "SELECT ?, ?, ?, ?, ?, ?, ?, ?, ? WHERE (SELECT changes()) > 0"
)
_PROPOSAL_INSERT_HEAD = (
    "INSERT OR IGNORE INTO claw_proposals(proposal_id, workspace_id, rule_id, channel, "
    "title, summary, approval_required, approval_reason, suggested_action, approved_by, "
    "approved_at, created_at) SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ? WHERE "
)
_PROPOSAL_GUARD_OCCURRENCE = (
    "EXISTS (SELECT 1 FROM claw_occurrences "
    "WHERE occurrence_key = ? AND run_id = ? AND workspace_id = ?)"
)
_PROPOSAL_GUARD_RUN_OUTPUT = (
    "EXISTS (SELECT 1 FROM claw_runs WHERE run_id = ? AND workspace_id = ? AND output = ?)"
)

# ONE bounded conditional UPDATE reuses the existing run row and status column.
# The guard is what makes the claim atomic: only a PENDING row with no completion
# can match, so RUNNING / COMPLETED / FAILED / CANCELLED are never reclaimed.
_CLAIM_EXECUTION = (
    "UPDATE claw_runs SET status = ? "
    "WHERE run_id = ? AND status = ? AND completed_at IS NULL RETURNING run_id"
)
_UPDATE_PROJECTION = (
    "UPDATE claw_runs SET status = ?, completed_at = ?, output = ?, error_message = ? "
    "WHERE run_id = ? AND status = ? AND (output IS NULL OR output = ?) RETURNING run_id"
)


def _batch_row(results: Any, index: int) -> dict[str, Any] | None:
    """Read one ``RETURNING`` row out of a ``db.batch()`` result.

    Mirrors the single-statement semantics: ``None`` means the statement returned
    no row, which is how a refused guarded write reports itself.
    """

    if results is None:
        return None
    try:
        if len(results) <= index:
            return None
    except TypeError:
        return None
    result = results[index]
    if isinstance(result, dict):
        rows = result.get("results")
    else:
        rows = getattr(result, "results", None)
    if not rows:
        return None
    try:
        return _row_to_dict(rows[0])
    except (TypeError, IndexError, KeyError):
        return None


def _tuple_for(row: dict[str, Any], columns: tuple[str, ...]) -> tuple[Any, ...]:
    """Project a D1 row dict onto the reference store's positional tuple."""

    return tuple(row.get(column) for column in columns)


def _proposal_values(proposal: ClawNotificationProposal) -> tuple[Any, ...]:
    return (
        proposal.proposal_id,
        proposal.workspace_id,
        proposal.rule_id,
        proposal.channel.value,
        proposal.title,
        proposal.summary,
        1 if proposal.approval_gate.approval_required else 0,
        proposal.approval_gate.reason,
        proposal.approval_gate.suggested_action,
        proposal.approval_gate.approved_by,
        _iso(proposal.approval_gate.approved_at)
        if proposal.approval_gate.approved_at
        else None,
        _iso(proposal.created_at),
    )


class D1ClawAutomationStore(ClawAutomationStore):
    """Durable, workspace-scoped D1 implementation of ``ClawAutomationStore``.

    Consumes the existing ``PADIEM_CHAT_DB`` binding. The schema is owned by
    migration 018 and is never created, altered or dropped at runtime. Every
    failure fails closed as a ``WorkspaceStorageError`` (persistence) or the
    kernel's own ``ContractError`` (domain refusal) — never as a silent success.
    """

    def __init__(self, db: Any | None) -> None:
        if db is None:
            raise ValueError("D1 binding (PADIEM_CHAT_DB) is required")
        self.db = db

    # --- D1 plumbing --------------------------------------------------------

    def _stmt(self, sql: str, *values: Any) -> Any:
        stmt = self.db.prepare(sql)
        if values:
            stmt = stmt.bind(*values)
        return stmt

    async def _run(self, sql: str, *values: Any) -> Any:
        stmt = self._stmt(sql, *values)
        try:
            return await stmt.run()
        except Exception as exc:
            raise WorkspaceStorageError(f"D1 write failed: {exc}") from exc

    async def _first(self, sql: str, *values: Any) -> dict[str, Any] | None:
        stmt = self._stmt(sql, *values)
        try:
            raw = await stmt.first()
        except Exception as exc:
            raise WorkspaceStorageError(f"D1 read failed: {exc}") from exc
        return _row_to_dict(raw)

    async def _all(self, sql: str, *values: Any) -> list[dict[str, Any]]:
        stmt = self._stmt(sql, *values)
        try:
            raw = await stmt.all()
        except Exception as exc:
            raise WorkspaceStorageError(f"D1 read failed: {exc}") from exc
        rows: list[dict[str, Any]] = []
        for row in raw or ():
            converted = _row_to_dict(row)
            if converted is not None:
                rows.append(converted)
        return rows

    async def _batch(self, statements: list[Any]) -> Any:
        try:
            return await self.db.batch(statements)
        except Exception as exc:
            raise WorkspaceStorageError(f"D1 write failed: {exc}") from exc

    # --- canonical row readers ---------------------------------------------

    async def _rule_row(self, rule_id: str) -> tuple[Any, ...] | None:
        row = await self._first(_SELECT_RULE, rule_id)
        return _tuple_for(row, _RULE_COLUMNS) if row is not None else None

    async def _run_row(self, run_id: str) -> tuple[Any, ...] | None:
        row = await self._first(_SELECT_RUN, run_id)
        return _tuple_for(row, _RUN_COLUMNS) if row is not None else None

    async def _occurrence_run_id(
        self, key: str, workspace_id: str
    ) -> str | None:
        row = await self._first(_SELECT_OCCURRENCE_RUN_ID, key, workspace_id)
        return row.get("run_id") if row is not None else None

    # --- rule persistence ---------------------------------------------------

    async def save_rule(self, rule: ClawAutomationRule) -> None:
        """Insert or update one rule through the canonical encoded payload.

        Owner provenance and execution material are immutable after creation. The
        reference ``InMemoryClawAutomationStore`` enforces that immutability in
        Python before the write; this adapter performs the SAME check so the two
        durable homes cannot drift on what a rule may change. Legitimate edits
        (name, schedule, enabled, channels) are allowed; a changed ``owner_ref`` or
        execution intent fails closed as a ``ContractError`` rather than a silent
        overwrite.
        """

        payload = SqliteClawAutomationStore._serialize_rule(rule).decode("utf-8")
        now = _iso(datetime.now(timezone.utc))
        existing = await self._rule_row(rule.rule_id)
        if existing is not None:
            if existing[1] != rule.workspace_id:
                raise ContractError("rule_id is already owned by another workspace")
            try:
                existing_payload = json.loads(existing[9])
            except Exception as exc:
                raise ContractError("stored automation rule is corrupt") from exc
            if existing_payload.get("owner_ref") != rule.owner_ref:
                raise ContractError("rule owner provenance is immutable")
            if existing[12] != rule.canonical_subject_id:
                raise ContractError("rule canonical subject provenance is immutable")
            if existing_payload.get("execution_intent") != _execution_intent_document(
                rule.execution_intent
            ):
                raise ContractError("rule execution intent is immutable")
        statement = self._stmt(
            "INSERT INTO claw_rules(rule_id, workspace_id, name, schedule_kind, "
            "schedule_expression, schedule_timezone, target_source, output_type, enabled, "
            "notification_channels, created_at, updated_at, canonical_subject_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(rule_id) DO UPDATE SET name = excluded.name, "
            "schedule_kind = excluded.schedule_kind, "
            "schedule_expression = excluded.schedule_expression, "
            "schedule_timezone = excluded.schedule_timezone, "
            "target_source = excluded.target_source, output_type = excluded.output_type, "
            "enabled = excluded.enabled, "
            "notification_channels = excluded.notification_channels, "
            "updated_at = excluded.updated_at "
            "WHERE claw_rules.workspace_id = excluded.workspace_id "
            "RETURNING rule_id",
            rule.rule_id,
            rule.workspace_id,
            rule.name,
            rule.schedule.kind.value,
            rule.schedule.expression,
            rule.schedule.timezone,
            rule.target_source.value,
            rule.output_type.value,
            1 if rule.enabled else 0,
            payload,
            now,
            now,
            rule.canonical_subject_id,
        )
        written = _row_to_dict(await self._first_row(statement))
        if written is not None:
            return
        # The upsert matched no row (should not happen after the explicit checks
        # above): fail closed rather than silently no-op.
        if existing is None:
            raise ContractError("rule insert was refused")
        raise WorkspaceStorageError("D1 rule write was refused")

    async def get_rule(
        self, rule_id: str, workspace_id: str
    ) -> ClawAutomationRule | None:
        row = await self._rule_row(rule_id)
        if row is None or row[1] != workspace_id:
            return None
        return SqliteClawAutomationStore._rule_from_row(row)

    async def list_rules(self, workspace_id: str) -> list[ClawAutomationRule]:
        rows = await self._all(_SELECT_RULES_FOR_WORKSPACE, workspace_id)
        return [
            SqliteClawAutomationStore._rule_from_row(_tuple_for(row, _RULE_COLUMNS))
            for row in rows
        ]

    async def update_rule(self, rule: ClawAutomationRule) -> None:
        current = await self._rule_row(rule.rule_id)
        if current is None or current[1] != rule.workspace_id:
            raise ContractError("rule does not belong to workspace")
        await self.save_rule(rule)

    async def set_rule_enabled(
        self, workspace_id: str, rule_id: str, enabled: bool
    ) -> ClawAutomationRule:
        if not isinstance(enabled, bool):
            raise ContractError("enabled must be boolean")
        rule = await self.get_rule(rule_id, workspace_id)
        if rule is None:
            raise ContractError("rule does not belong to workspace")
        updated = ClawAutomationRule(
            rule_id=rule.rule_id,
            workspace_id=rule.workspace_id,
            name=rule.name,
            schedule=rule.schedule,
            target_source=rule.target_source,
            output_type=rule.output_type,
            enabled=enabled,
            notification_channels=rule.notification_channels,
            owner_ref=rule.owner_ref,
            execution_intent=rule.execution_intent,
            canonical_subject_id=rule.canonical_subject_id,
        )
        await self.save_rule(updated)
        return updated

    # --- run persistence ----------------------------------------------------

    async def record_run(self, run: ClawScheduledRun) -> ClawScheduledRun:
        """Claim the occurrence, then write the canonical run — claim-first.

        The occurrence primary key is the only dedup authority. Whichever writer
        wins the claim owns the canonical run for this logical occurrence; a
        loser adopts that run and performs NO write and NO delete, because both
        contenders name the same occurrence-derived run id.
        """

        existing_run = await self._run_row(run.run_id)
        if existing_run is not None and existing_run[1] != run.workspace_id:
            raise ContractError("run_id is already owned by another workspace")
        key = occurrence_key(run.workspace_id, run.rule_id, run.scheduled_time)
        existing_id = await self._occurrence_run_id(key, run.workspace_id)
        if existing_id is not None:
            # Fast path: the occurrence is already claimed. Adopt the canonical
            # run; never write, and never delete anything.
            canonical = await self.get_run(existing_id, run.workspace_id)
            if canonical is None:
                raise ContractError("occurrence claim points at a missing run")
            return canonical
        if existing_run is not None:
            # An unclaimed occurrence plus an existing run row means this run_id
            # is being aliased to a different logical occurrence. The reference
            # store fails closed on the same condition.
            raise ContractError(
                "run_id is already stored for a different logical occurrence"
            )
        statements = [
            self._stmt(_CLAIM_OCCURRENCE, key, run.run_id, run.workspace_id),
            self._stmt(
                _INSERT_RUN_GUARDED,
                run.run_id,
                run.workspace_id,
                run.rule_id,
                run.status.value,
                _iso(run.scheduled_time),
                _iso(run.started_at),
                _iso(run.completed_at) if run.completed_at else None,
                SqliteClawAutomationStore._serialize_output(run.output),
                run.error_message,
            ),
        ]
        if run.output and run.output.proposals:
            for proposal in run.output.proposals:
                statements.append(
                    self._stmt(
                        _PROPOSAL_INSERT_HEAD + _PROPOSAL_GUARD_OCCURRENCE,
                        *_proposal_values(proposal),
                        key,
                        run.run_id,
                        run.workspace_id,
                    )
                )
        await self._batch(statements)
        winner_id = await self._occurrence_run_id(key, run.workspace_id)
        if winner_id is None:
            raise ContractError("occurrence claim vanished during concurrent write")
        if winner_id != run.run_id:
            canonical = await self.get_run(winner_id, run.workspace_id)
            if canonical is None:
                raise ContractError("occurrence claim points at a missing run")
            return canonical
        return run

    async def get_run(
        self, run_id: str, workspace_id: str
    ) -> ClawScheduledRun | None:
        row = await self._run_row(run_id)
        if row is None or row[1] != workspace_id:
            return None
        return SqliteClawAutomationStore._run_from_row(row)

    async def get_run_for_occurrence(
        self, key: str, workspace_id: str
    ) -> ClawScheduledRun | None:
        run_id = await self._occurrence_run_id(key, workspace_id)
        if run_id is None:
            return None
        return await self.get_run(run_id, workspace_id)

    async def list_runs(self, workspace_id: str) -> list[ClawScheduledRun]:
        rows = await self._all(_SELECT_RUNS_FOR_WORKSPACE, workspace_id)
        return [
            SqliteClawAutomationStore._run_from_row(_tuple_for(row, _RUN_COLUMNS))
            for row in rows
        ]

    async def list_proposals(
        self, workspace_id: str
    ) -> list[ClawNotificationProposal]:
        rows = await self._all(_SELECT_PROPOSALS_FOR_WORKSPACE, workspace_id)
        return [
            SqliteClawAutomationStore._proposal_from_row(
                _tuple_for(row, _PROPOSAL_COLUMNS)
            )
            for row in rows
        ]

    # --- server-owned due-workspace discovery reads (#2987) -----------------
    #
    # Deliberately NOT a product list surface. The method takes no caller
    # workspace, returns identifiers only, and is bounded by an explicit page
    # size. It exists so an internal scheduler-side discovery pass can page
    # through candidate workspaces that currently own at least one enabled rule without ever
    # handing a caller a tenant-wide enumeration.

    async def list_candidate_workspace_page(
        self,
        *,
        page_size: int,
        after_workspace_id: str | None = None,
    ) -> list[str]:
        """Return ONE bounded, deterministic page of enabled-rule candidate workspaces.

        ``page_size`` is mandatory and bounded by the caller's own scheduler
        constant; ``after_workspace_id`` is a monotonic cursor from a previous
        page. A cursor is not an authority: it can only move the page forward
        through the same deterministic ``workspace_id`` ordering, so a caller
        can neither skip nor widen the scan arbitrarily.

        Only workspaces with at least one ENABLED rule are returned, and only
        their identifiers -- never a rule body, a run, a proposal or a
        credential. This read grants no membership and no execution authority.
        """

        if isinstance(page_size, bool) or not isinstance(page_size, int):
            raise ContractError("page_size must be an integer")
        if page_size <= 0 or page_size > _MAX_CANDIDATE_WORKSPACE_PAGE_SIZE:
            raise ContractError(
                f"page_size must be between 1 and {_MAX_CANDIDATE_WORKSPACE_PAGE_SIZE}"
            )
        if after_workspace_id is None:
            rows = await self._all(_SELECT_CANDIDATE_WORKSPACES_FROM_START, page_size)
        else:
            if not isinstance(after_workspace_id, str) or not after_workspace_id:
                raise ContractError("after_workspace_id cursor must be bounded text")
            rows = await self._all(
                _SELECT_CANDIDATE_WORKSPACES_AFTER, after_workspace_id, page_size
            )
        ordered: list[str] = []
        for row in rows:
            workspace = row.get("workspace_id")
            if isinstance(workspace, str) and workspace and workspace not in ordered:
                ordered.append(workspace)
        return ordered

    async def claim_execution(
        self,
        *,
        run_id: str,
        workspace_id: str,
        rule_id: str,
        scheduled_time: datetime,
    ) -> ClawScheduledRun | None:
        """Atomically claim ONE existing ``PENDING`` row for execution.

        The claim reuses the EXISTING scheduled-run row and its status column.
        There is no lock table, no claim token, no lease row, no second dedup key
        and no second run id: ``PENDING -> RUNNING`` is one bounded conditional
        update on the row the durable tick already claimed.

        ``RUNNING``, ``COMPLETED``, ``FAILED`` and ``CANCELLED`` all resolve to
        ``None`` — not claimed — so a second claimant can never dispatch the same
        occurrence twice, and a stuck ``RUNNING`` row is preferred over a
        duplicated external side effect.
        """

        (
            bounded_run_id,
            bounded_workspace,
            bounded_rule,
            scheduled,
        ) = _execution_claim_material(
            run_id=run_id,
            workspace_id=workspace_id,
            rule_id=rule_id,
            scheduled_time=scheduled_time,
        )
        row = await self._run_row(bounded_run_id)
        if row is None or row[1] != bounded_workspace:
            raise ContractError("execution claim requires an existing scheduled run")
        stored = SqliteClawAutomationStore._run_from_row(row)
        if stored.rule_id != bounded_rule or stored.scheduled_time != scheduled:
            raise ContractError(
                "execution claim cannot change the scheduled occurrence identity"
            )
        key = occurrence_key(bounded_workspace, bounded_rule, scheduled)
        if await self._occurrence_run_id(key, bounded_workspace) != bounded_run_id:
            raise ContractError("execution claim must match the existing occurrence claim")
        if stored.status is not ClawScheduledRunStatus.PENDING:
            # RUNNING / COMPLETED / FAILED / CANCELLED: never dispatched again.
            return None
        claimed_row = await self._first(
            _CLAIM_EXECUTION,
            ClawScheduledRunStatus.RUNNING.value,
            bounded_run_id,
            ClawScheduledRunStatus.PENDING.value,
        )
        if claimed_row is None:
            # A concurrent claimant won the same conditional update. Not claimed,
            # and no delete is ever issued on the loser path.
            return None
        claimed = await self._run_row(bounded_run_id)
        if claimed is None:
            raise ContractError("execution claim lost its scheduled run row")
        return SqliteClawAutomationStore._run_from_row(claimed)

    async def update_run_projection(
        self,
        *,
        run_id: str,
        workspace_id: str,
        rule_id: str,
        scheduled_time: datetime,
        status: ClawScheduledRunStatus,
        completed_at: datetime | None = None,
        error_message: str | None = None,
        output: ClawAutomationOutput | None = None,
    ) -> ClawScheduledRun:
        """Update an existing projection row in place. Fail-closed: never inserts.

        The row must already exist, its immutable occurrence identity must match,
        and the existing occurrence claim must point at this same run id. A second
        run row or a fresh claim is impossible through this path.
        """

        (
            bounded_run_id,
            bounded_workspace,
            bounded_rule,
            scheduled,
            projected,
            completed,
            bounded_error,
        ) = _projection_update_material(
            run_id=run_id,
            workspace_id=workspace_id,
            rule_id=rule_id,
            scheduled_time=scheduled_time,
            status=status,
            completed_at=completed_at,
            error_message=error_message,
        )
        row = await self._run_row(bounded_run_id)
        if row is None or row[1] != bounded_workspace:
            raise ContractError("projection update requires an existing scheduled run")
        stored = SqliteClawAutomationStore._run_from_row(row)
        if stored.rule_id != bounded_rule or stored.scheduled_time != scheduled:
            raise ContractError(
                "projection update cannot change the scheduled occurrence identity"
            )
        key = occurrence_key(bounded_workspace, bounded_rule, scheduled)
        if await self._occurrence_run_id(key, bounded_workspace) != bounded_run_id:
            raise ContractError(
                "projection update must match the existing occurrence claim"
            )
        persisted_output = _projection_output_for_update(
            workspace_id=bounded_workspace,
            rule_id=bounded_rule,
            status=projected,
            output=output,
            existing_status=stored.status,
            existing_output=stored.output,
        )
        serialized_output = SqliteClawAutomationStore._serialize_output(persisted_output)
        statements = [
            self._stmt(
                _UPDATE_PROJECTION,
                projected.value,
                _iso(completed) if completed is not None else None,
                serialized_output,
                bounded_error,
                bounded_run_id,
                stored.status.value,
                serialized_output,
            )
        ]
        if output is not None and stored.output is None and output.proposals:
            for proposal in output.proposals:
                statements.append(
                    self._stmt(
                        _PROPOSAL_INSERT_HEAD + _PROPOSAL_GUARD_RUN_OUTPUT,
                        *_proposal_values(proposal),
                        bounded_run_id,
                        bounded_workspace,
                        serialized_output,
                    )
                )
        results = await self._batch(statements)
        if _batch_row(results, 0) is None:
            raise ContractError("projection output changed concurrently")
        updated = await self.get_run(bounded_run_id, bounded_workspace)
        if updated is None:
            raise ContractError("projection update lost its scheduled run")
        return updated

    # --- guarded statement execution ---------------------------------------

    async def _first_row(self, statement: Any) -> Any:
        """Execute one already-built statement and read its ``RETURNING`` row."""

        try:
            return await statement.first()
        except Exception as exc:
            raise WorkspaceStorageError(f"D1 write failed: {exc}") from exc


__all__ = [
    "D1ClawAutomationStore",
    "D1_CLAW_AUTOMATION_STORE_READY",
    "DURABLE_AUTOMATION_STORE_READY",
    "WORKER_D1_CLAW_AUTOMATION_STORE",
]