"""Desktop durable Local Runner run record — issue #3082, slice 1 (record contract).

This module is the Desktop-side durable record contract for one admitted local
command. It is deliberately **pure**: no SQLite, no clock reads, no process
handling, no network. It fixes the record shape, the state machine and the
fail-closed invariants so that the durable store
(`kagent.local_agent_durable_run_store`) and its restart recovery have one
canonical vocabulary to build on.

What this module is NOT (P0 guardrails, unchanged):

* it is not an identity authority — `device_id` / `binding_ref` / `account_ref` /
  `workspace_ref` are copied correlation facts, minted nowhere here;
* it is not an admission authority — the canonical broker/admission decision
  stays in #3080 and `kagent.local_agent_command_admission`;
* it is not an approval, retry, scheduler, process, evidence-creation, model
  routing or sandbox authority;
* it never recomputes a request fingerprint and never decides that a command may
  execute.

CENTRAL decisions encoded here (issue #3082):

* **R3** — the canonical #3080 revision is the **opaque `revision_ref`**, and it
  is a *required* correlation field copied from
  `BrokerCommandRecord.revision_ref` / `BrokerCommandResult.revision_ref`. The
  store never mints one, never parses one, never increments one and never
  derives ordering from it: it is correlation only. `sequence` remains the
  broker ordering/replay authority and is a *different* dimension — the two are
  never mixed, compared or substituted for one another, and neither is a second
  revision authority. An earlier revision of this module wrongly claimed "#3080
  has no revision field"; the final merged #3080 contract
  (`REVISION_FIELD=revision_ref`, `REVISION_AUTHORITY=SERVER_ONLY`,
  `LOCAL_MINT_REVISION=NO`) is the authority and this module now matches it.
* **R4** — `request_fingerprint` is stored verbatim and compared. It is never
  recomputed and never generated. The local command path's fingerprint authority
  remains `command_request_fingerprint(LocalCommandRequest)`
  (`kagent.windows_local_executor`), and the broker field remains
  `BrokerCommandRecord.request_fingerprint`. This module adds no second
  fingerprint authority and no `fingerprint_algorithm` field.
* **R12** — the bounded result metadata is the canonical #3080 return contract:
  `command_id`, `run_id`, `tool_request_ref`, `request_id`, `revision_ref`,
  `request_fingerprint`, `admission_ref`, `evidence_ref`, `termination`,
  `exit_code`. `exit_code` is a bounded `int | None` using the same
  `MIN_BOUNDED_EXIT_CODE`/`MAX_BOUNDED_EXIT_CODE` range the broker applies, and
  it is a *result* fact: only a locally terminal `EXITED` run may carry one.
  Raw stdout, stderr, argv, file content and credentials remain unrepresentable.
* **R6** — `command_expires_at` is a **hard deadline**. There is no renewal,
  extension or lease method anywhere in this module, and a record whose deadline
  has passed can only ever be reconciled to `TERMINAL/EXPIRED`, never back to a
  non-terminal state. Session expiry stays a separate contract
  (`DeviceSession.expires_at`) and can never widen a command deadline.
* **R8** — local execution terminality and server acknowledgement are two
  orthogonal durable facts. `state=TERMINAL` plus `termination` records the local
  observed fact; `server_acknowledged_at` records a separate server fact. A
  terminal record with no server acknowledgement is still terminal, is never
  replayable, and is never garbage collected. There is deliberately no single
  `ACKED` state that would erase the local `termination` subtype.
* **#3081 correction** — nothing here scans PIDs, reattaches unknown processes or
  replays side effects. The recovery rationale is side-effect duplication, PID
  reuse and state uncertainty — *not* an assumption that #3081 leaves descendants
  alive on runner crash (it does not: `KILL_ON_JOB_CLOSE` reaps the tree).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any

from .contracts import ContractError

# Bounds follow the canonical local-agent ref rules (`kagent.local_agent_pairing`
# and `kagent.local_agent_command_admission`) rather than inventing new ones.
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")

#: Terminal evidence must stay small. The store keeps counts and refs, never
#: unbounded output. This mirrors the bounded-receipt posture of
#: `LocalCommandResult` without carrying its stdout/stderr text.
MAX_EVIDENCE_ITEMS = 64
MAX_EVIDENCE_REF_CHARS = 256
MAX_EVIDENCE_SUMMARY_CHARS = 1024


def _ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    return value.strip()


def _digest(value: Any, field_name: str) -> str:
    normalized = value.strip().lower() if isinstance(value, str) else ""
    if not _SHA256_RE.fullmatch(normalized):
        raise ContractError(f"{field_name} must be a lowercase SHA-256 digest")
    return normalized


def _aware(value: Any, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _sequence(value: Any, field_name: str = "sequence") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ContractError(f"{field_name} must be a positive integer")
    return value


def _generation(value: Any, field_name: str = "credential_generation") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ContractError(f"{field_name} must be a positive integer")
    return value


def _iso(value: datetime) -> str:
    return _aware(value, "timestamp").isoformat().replace("+00:00", "Z")


#: Same bounds the canonical #3080 `BrokerCommandRecord`/`BrokerCommandResult`
#: apply (`MIN_BOUNDED_EXIT_CODE`/`MAX_BOUNDED_EXIT_CODE`). The store re-checks
#: the canonical bound and never widens it; it does not define a second range.
MAX_BOUNDED_EXIT_CODE = 2_147_483_647
MIN_BOUNDED_EXIT_CODE = -2_147_483_647


def _bounded_exit_code(value: Any) -> int | None:
    """Accept only a bounded process exit status, or the explicit null result."""

    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractError("exit_code must be an integer or null")
    if not MIN_BOUNDED_EXIT_CODE <= value <= MAX_BOUNDED_EXIT_CODE:
        raise ContractError("exit_code must be a bounded process exit status")
    return value


class DurableRunState(str, Enum):
    """Local durable lifecycle of one admitted Desktop local command.

    ``RECONCILIATION_REQUIRED`` is a **local durable fact only**. The merged
    #3080 broker wire vocabulary is exactly ``QUEUED`` / ``ADMITTED`` /
    ``ACKNOWLEDGED`` (`BrokerCommandState` in
    ``padiem_control_plane.local_agent_broker``) and contains no reconciliation
    state, so this value is never projected onto the wire and never claims broker
    support.
    """

    ADMITTED = "admitted"
    EXECUTING = "executing"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    TERMINAL = "terminal"


#: A durable row is never replay authority, in any lifecycle state.
#:
#: ADMITTED/EXECUTING describe local facts about an already-admitted command;
#: they do not authorize a second execution after restart. Initial execution
#: authority stays exclusively in the canonical admission + P01 path, while
#: recovery only reports/reconciles. Keeping every durable state non-replayable
#: prevents this record contract from becoming a competing replay authority.
NON_REPLAYABLE_STATES = frozenset(DurableRunState)


class DurableRunTermination(str, Enum):
    """Why local execution stopped (R8 — the local observed fact).

    ``EXPIRED`` is reachable only once the R6 hard deadline has passed.
    ``ABORTED`` records a local abort whose terminal result was durably written
    before the Desktop or runner went away. Both remain non-replayable.
    """

    EXITED = "exited"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    EXPIRED = "expired"
    ABORTED = "aborted"


class DurableRunOfflineState(str, Enum):
    """Offline queue metadata (issue #3082 scope).

    This is *metadata about* a pending request, never permission to run it. The
    server-side device truth is owned by #3080/#3083: a redeemed device is
    ``PAIRED_OFFLINE`` and only a server-owned session plus heartbeat may
    project ``ONLINE``. ``OFFLINE`` here therefore describes a local durable
    observation, and none of these values grants execution authority.
    """

    #: No session is currently usable; nothing is queued locally.
    IDLE = "idle"
    #: A locally persisted request awaits an admissible session. Metadata only.
    QUEUED = "queued"
    #: The local credential/deadline can no longer be used; the queued record is
    #: retained for inspection but can never be admitted again.
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class BoundedEvidenceProjection:
    """Bounded, secret-free evidence *metadata* for one durable run.

    The store persists this so a recovery report can describe what happened
    without ever holding an approval payload, raw argv, stdout/stderr text or
    file contents. Only counts, bounded refs and a bounded summary are allowed.
    """

    diff_ref: str | None = None
    test_ref: str | None = None
    artifact_ref: str | None = None
    evidence_ref: str | None = None
    item_count: int = 0
    summary: str = ""

    def __post_init__(self) -> None:
        for name in ("diff_ref", "test_ref", "artifact_ref", "evidence_ref"):
            value = getattr(self, name)
            if value is None:
                continue
            object.__setattr__(
                self,
                name,
                _bounded_ref(value, f"{name}"),
            )
        if isinstance(self.item_count, bool) or not isinstance(self.item_count, int):
            raise ContractError("item_count must be an integer")
        if not 0 <= self.item_count <= MAX_EVIDENCE_ITEMS:
            raise ContractError(f"item_count must be between 0 and {MAX_EVIDENCE_ITEMS}")
        if not isinstance(self.summary, str):
            raise ContractError("summary must be a string")
        if len(self.summary) > MAX_EVIDENCE_SUMMARY_CHARS:
            raise ContractError(
                f"summary must be at most {MAX_EVIDENCE_SUMMARY_CHARS} characters"
            )
        if _looks_like_raw_output(self.summary):
            raise ContractError("evidence summary must not carry raw process output")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "diff_ref": self.diff_ref,
            "test_ref": self.test_ref,
            "artifact_ref": self.artifact_ref,
            "evidence_ref": self.evidence_ref,
            "item_count": self.item_count,
            "summary": self.summary,
            "raw_argv": False,
            "raw_stdout": False,
            "raw_stderr": False,
            "p01_approval_payload": False,
            "raw_file_content": False,
        }


_RAW_OUTPUT_MARKERS = (
    "p01_approval_payload=",
    "argv=",
    "stdout=",
    "stderr=",
    "credential=",
    "device_credential=",
    "broker_token=",
)


def _bounded_ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field_name} must be a non-empty bounded reference")
    normalized = value.strip()
    if len(normalized) > MAX_EVIDENCE_REF_CHARS:
        raise ContractError(f"{field_name} must be at most {MAX_EVIDENCE_REF_CHARS} characters")
    if _looks_like_raw_output(normalized):
        raise ContractError(f"{field_name} must not carry raw process output")
    return normalized


def _looks_like_raw_output(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in _RAW_OUTPUT_MARKERS)


@dataclass(frozen=True, slots=True)
class DurableRunRecord:
    """One durable Desktop local-command run record (#3082 slice 1).

    Every field is either a bounded reference, a bounded digest, a bounded
    timestamp, or bounded evidence metadata. No raw credential, approval
    payload, argv, stdout/stderr or file content is representable.
    """

    # --- correlation (R1/R2/R3): copied from the canonical #3080 contracts ---
    command_id: str
    run_id: str
    tool_request_ref: str
    request_id: str
    #: R3 — the server-owned opaque revision correlation. Required, copied
    #: verbatim, never minted/parsed/incremented here and never used for
    #: ordering. `sequence` below is the broker ordering/replay authority and is
    #: deliberately a different dimension from this field.
    revision_ref: str
    device_id: str
    binding_ref: str
    session_id: str
    account_ref: str
    workspace_ref: str
    #: R3 — broker ordering/replay authority (copied from
    #: `BrokerCommandRecord.sequence`). This is NOT a revision and must never be
    #: used as one.
    sequence: int
    #: R9 — must correlate with the device binding's credential generation.
    credential_generation: int
    #: R4 — stored verbatim from `BrokerCommandRecord.request_fingerprint`.
    #: Never recomputed here, never generated here.
    request_fingerprint: str
    #: Opaque provenance label only. Deliberately *not* an algorithm field: this
    #: module must not describe or choose how a fingerprint is produced.
    fingerprint_source: str

    # --- R6 hard deadline ---
    command_issued_at: datetime
    command_expires_at: datetime

    admitted_at: datetime
    started_at: datetime | None = None
    terminated_at: datetime | None = None

    state: DurableRunState = DurableRunState.ADMITTED
    termination: DurableRunTermination | None = None
    #: R8 — the orthogonal server fact. ``None`` means "not acknowledged (yet)",
    #: which never reopens a terminal record and never enables a replay.
    server_acknowledged_at: datetime | None = None
    #: R5 — the server-issued admission reference for this run. Copied from
    #: `BrokerCommandRecord.admission_ref` / `BrokerCommandAdmission.admission_ref`
    #: and never minted here. ``None`` before admission is durably recorded.
    admission_ref: str | None = None
    #: Bounded result metadata, matching `BrokerCommandResult.exit_code`. This is
    #: the whole of the exit-status fact: no stdout, stderr, argv or file content
    #: is representable anywhere in this record.
    exit_code: int | None = None

    offline_state: DurableRunOfflineState = DurableRunOfflineState.IDLE
    evidence: BoundedEvidenceProjection = BoundedEvidenceProjection()

    def __post_init__(self) -> None:
        for name in (
            "command_id",
            "run_id",
            "tool_request_ref",
            "request_id",
            "revision_ref",
            "device_id",
            "binding_ref",
            "session_id",
            "account_ref",
            "workspace_ref",
        ):
            object.__setattr__(self, name, _ref(getattr(self, name), name))
        if self.admission_ref is not None:
            object.__setattr__(self, "admission_ref", _ref(self.admission_ref, "admission_ref"))
        object.__setattr__(self, "exit_code", _bounded_exit_code(self.exit_code))
        object.__setattr__(self, "sequence", _sequence(self.sequence))
        object.__setattr__(self, "credential_generation", _generation(self.credential_generation))
        object.__setattr__(self, "request_fingerprint", _digest(self.request_fingerprint, "request_fingerprint"))
        object.__setattr__(self, "fingerprint_source", _ref(self.fingerprint_source, "fingerprint_source"))

        issued_at = _aware(self.command_issued_at, "command_issued_at")
        expires_at = _aware(self.command_expires_at, "command_expires_at")
        # R6: a positive, bounded window is a precondition of the *broker*
        # record. The store re-checks it but never widens it.
        if expires_at <= issued_at:
            raise ContractError("command_expires_at must be after command_issued_at")
        object.__setattr__(self, "command_issued_at", issued_at)
        object.__setattr__(self, "command_expires_at", expires_at)

        admitted_at = _aware(self.admitted_at, "admitted_at")
        # R6: admission can never be recorded after the hard deadline, and the
        # deadline can never be moved to accommodate a late admission.
        if admitted_at < issued_at:
            raise ContractError("admitted_at cannot predate the canonical command issuance")
        if admitted_at >= expires_at:
            raise ContractError("admitted_at cannot be at or after the command hard deadline")
        object.__setattr__(self, "admitted_at", admitted_at)

        for name in ("started_at", "terminated_at", "server_acknowledged_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _aware(value, name))

        if not isinstance(self.state, DurableRunState):
            raise ContractError("state must be DurableRunState")
        if self.termination is not None and not isinstance(self.termination, DurableRunTermination):
            raise ContractError("termination must be DurableRunTermination")
        if not isinstance(self.offline_state, DurableRunOfflineState):
            raise ContractError("offline_state must be DurableRunOfflineState")
        if not isinstance(self.evidence, BoundedEvidenceProjection):
            raise ContractError("evidence must be BoundedEvidenceProjection")

        if self.started_at is not None:
            if self.started_at < self.admitted_at:
                raise ContractError("started_at cannot predate admitted_at")
            if self.started_at >= self.command_expires_at:
                raise ContractError("started_at cannot be at or after the command hard deadline")
            if self.state is DurableRunState.ADMITTED:
                raise ContractError("an ADMITTED record cannot already have started_at")

        if self.terminated_at is not None:
            if self.started_at is None:
                raise ContractError("a terminated record requires started_at")
            if self.terminated_at < self.started_at:
                raise ContractError("terminated_at cannot predate started_at")

        # R8 invariant: `termination` is meaningful exactly when the state is
        # TERMINAL, and TERMINAL always carries a local observed reason.
        if self.state is DurableRunState.TERMINAL:
            if self.termination is None:
                raise ContractError("a TERMINAL record requires a local termination reason")
            if self.terminated_at is None:
                raise ContractError("a TERMINAL record requires terminated_at")
            if self.termination is DurableRunTermination.EXPIRED and self.terminated_at < self.command_expires_at:
                # EXPIRED is a claim about the R6 hard deadline; recording it
                # earlier would be a fabricated local fact.
                raise ContractError("EXPIRED termination cannot be recorded before the command hard deadline")
        else:
            if self.termination is not None:
                raise ContractError("a non-terminal record cannot carry a termination reason")
            if self.terminated_at is not None:
                raise ContractError("a non-terminal record cannot carry terminated_at")

        if self.server_acknowledged_at is not None:
            if self.state is not DurableRunState.TERMINAL:
                raise ContractError("server acknowledgement requires a locally terminal record")
            if self.server_acknowledged_at < self.admitted_at:
                raise ContractError("server acknowledgement cannot predate admitted_at")
            if self.server_acknowledged_at >= self.command_expires_at:
                # The canonical broker rejects an ack at or after the hard
                # deadline. Accepting equality here would locally widen R6 by
                # one boundary instant and disagree with broker authority.
                raise ContractError("server acknowledgement cannot be at or after the command hard deadline")

        # `exit_code` is a *result* fact, so it may only appear once the run is
        # locally terminal. Recording an exit status on a still-running record
        # would be a fabricated local observation.
        if self.exit_code is not None and self.state is not DurableRunState.TERMINAL:
            raise ContractError("a non-terminal record cannot carry exit_code")
        if self.termination is not DurableRunTermination.EXITED and self.exit_code is not None:
            # Only a process that actually ran to its own exit status carries one.
            raise ContractError("only an EXITED termination can carry an exit_code")

    # --- derived facts -------------------------------------------------------

    @property
    def terminal(self) -> bool:
        return self.state is DurableRunState.TERMINAL

    @property
    def replayable(self) -> bool:
        """R8: recovery may never auto-replay from a non-replayable state."""

        return self.state not in NON_REPLAYABLE_STATES

    @property
    def acknowledged(self) -> bool:
        return self.server_acknowledged_at is not None

    def hard_deadline_passed(self, *, now: datetime) -> bool:
        """R6: the hard deadline is a fact, never a renewable lease."""

        return _aware(now, "now") >= self.command_expires_at

    def retention_hold(self) -> bool:
        """Whether GC must keep this record regardless of age.

        A terminal record whose server acknowledgement is still missing is
        exactly the crash window R8 calls out, so it is never collected
        automatically.
        """

        return self.terminal and not self.acknowledged

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": DURABLE_RUN_CONTRACT_VERSION,
            "command_id": self.command_id,
            "run_id": self.run_id,
            "tool_request_ref": self.tool_request_ref,
            "request_id": self.request_id,
            "revision_ref": self.revision_ref,
            "device_id": self.device_id,
            "binding_ref": self.binding_ref,
            "session_id": self.session_id,
            "account_ref": self.account_ref,
            "workspace_ref": self.workspace_ref,
            "sequence": self.sequence,
            "credential_generation": self.credential_generation,
            "request_fingerprint": self.request_fingerprint,
            "fingerprint_source": self.fingerprint_source,
            "command_issued_at": _iso(self.command_issued_at),
            "command_expires_at": _iso(self.command_expires_at),
            "admitted_at": _iso(self.admitted_at),
            "started_at": _iso(self.started_at) if self.started_at else None,
            "terminated_at": _iso(self.terminated_at) if self.terminated_at else None,
            "state": self.state.value,
            "termination": self.termination.value if self.termination else None,
            "server_acknowledged_at": (
                _iso(self.server_acknowledged_at) if self.server_acknowledged_at else None
            ),
            "admission_ref": self.admission_ref,
            "exit_code": self.exit_code,
            "offline_state": self.offline_state.value,
            "evidence": self.evidence.safe_dict(),
            "replayable": self.replayable,
            "retention_hold": self.retention_hold(),
            "raw_device_credential": False,
            "raw_approval_payload": False,
            "raw_argv": False,
            "raw_stdout": False,
            "raw_stderr": False,
            "process_pid_persisted": False,
        }


DURABLE_RUN_CONTRACT_VERSION = "claw-desktop-durable-run.v1"

#: R3 — the revision is the server-owned opaque `revision_ref` correlation, and
#: `sequence` remains the separate broker ordering/replay authority. The store
#: mints, parses, increments and orders on neither.
REVISION_FIELD = "revision_ref"
REVISION_AUTHORITY = "server_only"
REVISION_SEMANTICS = "opaque_correlation_only"
LOCAL_MINT_REVISION = False
LOCAL_PARSE_REVISION = False
LOCAL_REVISION_INCREMENT = False
LOCAL_REVISION_ORDERING = False
SECOND_REVISION_AUTHORITY = 0
#: R3 — `sequence` keeps its canonical broker ordering/replay meaning; it is not
#: a revision and must never be substituted for one.
SEQUENCE_IS_BROKER_ORDERING_AUTHORITY = True
SEQUENCE_USED_AS_REVISION = False

#: R4 — reuse of the canonical fingerprint, never a second authority.
FINGERPRINT_SOURCE_BROKER = "broker"
FINGERPRINT_SOURCE_LOCAL_COMMAND = "local_command"
FINGERPRINT_ALGORITHM_OWNED_HERE = False
REQUEST_FINGERPRINT_RECOMPUTED = False
SECOND_FINGERPRINT_AUTHORITY = 0

#: R6 — hard deadline, no renewal.
COMMAND_EXPIRES_AT_SEMANTICS = "hard_deadline"
LOCAL_LEASE_EXTENSION = False
SESSION_EXPIRY_SEPARATE_CONTRACT = True
EXPIRED_COMMAND_REPLAY_ALLOWED = False

#: R8 — orthogonal dimensions, no single ACKED state.
LOCAL_EXECUTION_TERMINALITY = "local_observed_fact"
SERVER_ACK_IS_ORTHOGONAL_DIMENSION = True
AUTO_REPLAY_AFTER_LOCAL_TERMINAL = False
TERMINAL_WITHOUT_ACK_IS_RETAINED = True

#: R11 — reconciliation is local-only; the #3080 wire has no such state.
RECONCILIATION_REQUIRED_IS_LOCAL_ONLY = True
BROKER_WIRE_RECONCILIATION_STATE = False
RECONCILIATION_PROJECTED_ONTO_WIRE = False

#: R9/R10 — the generation is recorded, never re-issued.
CREDENTIAL_REISSUE_AUTHORITY = False
STORE_REISSUES_CREDENTIAL = False

#: #3081 correction — recovery is fail-closed on record uncertainty, never on
#: process discovery.
PROCESS_PID_AUTHORITY = False
PID_SCANNING_SUPPORTED = False
UNKNOWN_PROCESS_REATTACHMENT_SUPPORTED = False
SIDE_EFFECT_REPLAY_SUPPORTED = False
#: Rationale (corrected): side-effect duplication, PID reuse, state uncertainty.
RECOVERY_FAIL_CLOSED_RATIONALE = (
    "side_effect_duplication",
    "pid_reuse",
    "state_uncertainty",
)
#: #3081 `KILL_ON_JOB_CLOSE` reaps the tree on runner death; #3082 must not
#: justify its separation by claiming descendants survive.
JOB_OBJECT_TREE_REAPED_ON_RUNNER_DEATH = True

#: P01 remains the lifecycle/evidence authority.
P01_LIFECYCLE_AUTHORITY_DUPLICATED = False
P01_EVIDENCE_AUTHORITY_DUPLICATED = False
SECOND_IDENTITY_AUTHORITY = 0
SECOND_ADMISSION_AUTHORITY = 0
SECOND_APPROVAL_AUTHORITY = 0
SECOND_TASK_ADMISSION_AUTHORITY = 0
SECOND_FILESYSTEM_AUTHORITY = 0
SECOND_PROCESS_AUTHORITY = 0
SECOND_EVIDENCE_AUTHORITY = 0
SECOND_MODEL_ROUTING_AUTHORITY = 0
SECOND_SANDBOX_AUTHORITY = 0
SECOND_SCHEDULER_AUTHORITY = 0
SECOND_RETRY_AUTHORITY = 0

DESKTOP_DURABLE_RUN_STORE = True
OFFLINE_STATE_EXPLICIT = True
RAW_SECRET_PERSISTENCE = False
BOUNDED_EVIDENCE_PROJECTION = True
DURABLE_STORE_IO_CONFIGURED = False
PRODUCTION_MUTATION = False
PRODUCTION_READY = False
