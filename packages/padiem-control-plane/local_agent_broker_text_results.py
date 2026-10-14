"""#4139 — bounded, authenticated device→broker verified TXT results.

This is the *producer* half of the canonical Broker ``read_verified_file_text``
RPC whose consumer half #4687 merged (``claw_local_task_result_composition`` /
``verify_broker_file_text``). Until now no producer existed, so a Windows TXT
read could only ever reach the conversation as a terminal-only message.

Nothing new is minted here:

* the **same** canonical Broker Durable Object and the **same** SQLite database,
  with one additional bounded table;
* the **same** authenticated device HTTP surface — the route is added to
  ``local_agent_broker_device_http._DEVICE_HTTP_ROUTES``, so the canonical
  device credential is verified before any payload is treated as a result;* the **same** canonical command/binding/ACK correlation gate the Office
  staging path already applies (``local_agent_broker_office_chunks``) for the
  body, and a deliberately weaker admission-level gate for the intent marker;
* no new credential, session, approval, Worker, database or account system.

    NEW_TEXT_TABLE=1 · SECOND_BROKER=0 · SECOND_DEVICE_AUTH=0
    OFFICE_PATH_UNCHANGED=1 · TYPE_EXECUTION_SURFACE=0

Ordering (CENTRAL #4139 race review): the consumer can project a terminal fact
as soon as the successful ACK is readable, and it derives the message id from
(command_id, revision_ref). A bodyless terminal-only message written first would
therefore *consume* that id and the real text could never appear. So the device
publishes its file-read **intent** first and awaits broker success before it
ACKs:

```text
intent (state=pending) -> real READ -> successful ACK -> body (state=content)
```

* the intent is accepted while the command is canonically ADMITTED, i.e. **no
  ACK required** — otherwise the marker could never precede the ACK that makes
  the terminal fact projectable;
* the body keeps the strict Office-success gate: ACK, ``exited``, exit_code 0,
  admission and evidence refs, ACTIVE binding and matching credential
  generation, so a failed execution can never present verified content;
* the intent is bound to the device's own canonical command: ownership comes
  from the authenticated binding and every correlation ref is read back from
  the persisted command, so a device can neither forge an owner/workspace nor
  declare someone else's command;
* no row is a question, not an answer. ``read`` resolves the canonical command
  first: only a command that provably finished successfully with no intent
  registered stays on the existing terminal-only ``"other"`` path. Anything it
  cannot confirm is refused instead of being reported as ``"other"``.

Three bounded states, exactly the shapes the merged consumer validates:

* a command that provably finished without a file-read intent stays ``{"ok":
true,"available":false,"kind":"other"}``;
* a command with a registered intent answers ``{...,"kind":"file_read_text"}``
  with ``available:false``, so the terminal-only message is never appended under
  the same stable message id before the text arrives;* a staged result answers the closed 14-field receipt, whose correlation is
  taken from the stored canonical command rather than from the device.

The device never asserts its own account, workspace, binding or correlation
refs: ownership comes from the authenticated device binding, and the remaining
refs are read back from the persisted command. The device supplies only the
command it is reporting, that command's request fingerprint, and the bounded
UTF-8 body with its own digest and byte count.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from padiem_control_plane.local_agent_broker import BrokerBindingState, BrokerCommandState
from local_agent_broker_sql_state import rows, row_value, rows_written, safe_ref

#: The device route this store is reachable on. Added to the canonical route set
#: so the private service bridge derives end-to-end reachability from one place.
TEXT_RESULT_DEVICE_ROUTE = "/text-result"

TEXT_RESULT_WIRE_VERSION = "claw-local-agent-text-result.v1"

#: #4687's consumer bound: "First synthetic TXT only; never generic stdout".
MAX_TEXT_RESULT_BYTES = 768

#: Bounded retention in broker SQL, mirroring the Office staging lifetime.
TEXT_RESULT_RETENTION = timedelta(days=1)

#: The acknowledgement recency the *write* gate requires, mirroring Office.
MAX_ACK_AGE = timedelta(days=1)
MAX_CLOCK_SKEW = timedelta(minutes=5)

STATE_PENDING = "pending"
STATE_CONTENT = "content"

#: The command state in which a file-read intent may be declared. Admission is
#: the owner's approval; requiring the terminal ACK here would reintroduce the
#: lost-message window, because the ACK is exactly what makes the terminal fact
#: projectable before the marker could exist.
_INTENT_COMMAND_STATES = frozenset({
    BrokerCommandState.ADMITTED, BrokerCommandState.ACKNOWLEDGED,
})

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_SAFE_CONTROL = "\n\r\t"

_WIRE_COMMON = frozenset({
    "contract_version", "command_id", "run_id", "request_fingerprint", "state",
})
_WIRE_CONTENT = frozenset({
    "content_utf8", "content_sha256", "content_bytes",
})

_READ_KEYS = frozenset({"account_ref", "workspace_ref", "run_id", "command_id"})
_SCOPE_PROOF_KEYS = frozenset({"command_id", "run_id", "request_fingerprint"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS local_agent_text_result (
 command_id TEXT PRIMARY KEY, binding_ref TEXT NOT NULL, account_ref TEXT NOT NULL,
 workspace_ref TEXT NOT NULL, run_id TEXT NOT NULL, tool_request_ref TEXT NOT NULL,
 request_id TEXT NOT NULL, revision_ref TEXT NOT NULL, evidence_ref TEXT NOT NULL,
 request_fingerprint TEXT NOT NULL, state TEXT NOT NULL,
 content_utf8 TEXT, content_sha256 TEXT, content_bytes INTEGER,
 received_at TEXT NOT NULL, expires_at TEXT NOT NULL
);
"""


class TextResultRefused(ValueError):
    """Caller-safe refusal; never renders document data or credential material."""


def _digest(value: Any) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise TextResultRefused("lowercase SHA-256 required")
    return value


def _bounded_bytes(value: Any) -> int:
    if type(value) is not int or not 0 <= value <= MAX_TEXT_RESULT_BYTES:
        raise TextResultRefused("bounded UTF-8 byte count required")
    return value


def validate_text_body(value: Any, *, digest: Any, byte_count: Any) -> tuple[str, str]:
    """Validate the one bounded body shape the consumer accepts.

    Mirrors ``claw_local_task_result_projection.verify_broker_file_text`` so a
    stored body can never be a body the merged consumer must refuse: UTF-8
    encodable, at most ``MAX_TEXT_RESULT_BYTES`` bytes, no control characters
    other than newline, carriage return and tab, and a digest that matches the
    bytes actually staged.
    """

    if type(value) is not str:
        raise TextResultRefused("verified file text must be text")
    try:
        raw = value.encode("utf-8")
    except UnicodeEncodeError:
        raise TextResultRefused("verified file text is not UTF-8 encodable") from None
    if len(raw) > MAX_TEXT_RESULT_BYTES:
        raise TextResultRefused("verified file text exceeds the bounded size")
    if any(ord(ch) < 32 and ch not in _MAX_SAFE_CONTROL for ch in value):
        raise TextResultRefused("verified file text carries a control character")
    if _digest(digest) != hashlib.sha256(raw).hexdigest():
        raise TextResultRefused("verified file text digest mismatch")
    if _bounded_bytes(byte_count) != len(raw):
        raise TextResultRefused("verified file text byte count mismatch")
    return value, hashlib.sha256(raw).hexdigest()


class BrokerTextResultStore:
    """Durable Object store: one bounded text result per canonical command.

    Exact replay is inert; a conflicting replay is refused and never overwrites
    a stored row.
    """

    def __init__(self, *, storage: Any, state_port: Any, authority_ref: str,
                 clock: Callable[[], datetime] | None = None):
        sql = getattr(storage, "sql", None)
        if sql is None or not callable(getattr(sql, "exec", None)):
            raise TextResultRefused("durable SQLite storage required")
        self._sql = sql
        self._state = state_port
        self._authority = safe_ref(authority_ref, "authority_ref")
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        # Durable Object SQL.exec is statement-scoped, not executescript.
        for statement in _SCHEMA.split(";"):
            if statement.strip():
                self._sql.exec(statement)

    def _now(self) -> datetime:
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise TextResultRefused("trusted timezone-aware clock required")
        return now.astimezone(timezone.utc)

    def _expire(self, now: datetime) -> None:
        self._sql.exec(
            "DELETE FROM local_agent_text_result WHERE expires_at<=?", now.isoformat(),
        )

    def _canonical_command(self, *, command_id: str, run_id: str, binding_ref: str,
                           owner: str, workspace: str):
        """The one canonical (binding, command) pair for this device scope."""

        snapshot = self._state.load(authority_ref=self._authority).snapshot
        bindings = [b for b in snapshot.bindings
                    if b.binding_ref == binding_ref and b.account_ref == owner
                    and b.workspace_ref == workspace]
        commands = [c for c in snapshot.commands
                    if c.command_id == command_id and c.run_id == run_id
                    and c.binding_ref == binding_ref]
        if len(bindings) != 1 or len(commands) != 1:
            raise TextResultRefused("canonical command/binding unavailable")
        return bindings[0], commands[0]

    def _canonical_command_by_scope(self, *, command_id: str, run_id: str,
                                    owner: str, workspace: str):
        """The same pair, resolved from owner/workspace instead of a binding ref.

        Used when no row exists yet: the answer must still be derived from the
        canonical command that belongs to this exact device scope, never from
        the mere absence of a local row.
        """

        snapshot = self._state.load(authority_ref=self._authority).snapshot
        commands = [c for c in snapshot.commands
                    if c.command_id == command_id and c.run_id == run_id]
        if len(commands) != 1:
            raise TextResultRefused("canonical command unavailable")
        binding_ref = commands[0].binding_ref
        bindings = [b for b in snapshot.bindings
                    if b.binding_ref == binding_ref and b.account_ref == owner
                    and b.workspace_ref == workspace]
        if len(bindings) != 1:
            raise TextResultRefused("canonical command/binding unavailable")
        return bindings[0], commands[0]

    def _intent_gate(self, *, command_id: str, run_id: str, binding_ref: str,
                     owner: str, workspace: str) -> None:
        """The admission-level gate for the *intent* marker only.

        Owner approval plus an ACTIVE binding plus a live credential generation
        plus the admitted command and its request fingerprint. The ACK is
        deliberately not required: the marker has to be readable before the ACK
        makes the terminal fact projectable. This grants nothing — the body
        still passes the strict success gate below.
        """

        binding, command = self._canonical_command(
            command_id=command_id, run_id=run_id, binding_ref=binding_ref,
            owner=owner, workspace=workspace,
        )
        now = self._now()
        if (binding.credential_expires_at <= now
                or binding.state is not BrokerBindingState.ACTIVE
                or command.credential_generation != binding.credential_generation
                or command.state not in _INTENT_COMMAND_STATES
                or not command.admission_ref or command.admitted_at is None):
            raise TextResultRefused("admitted local file read required")

    def _write_gate(self, *, command_id: str, run_id: str, binding_ref: str,
                    owner: str, workspace: str) -> None:
        """The Office staging gate, unchanged: only a successful admitted
        execution of this exact device scope may stage a result."""

        binding, command = self._canonical_command(
            command_id=command_id, run_id=run_id, binding_ref=binding_ref,
            owner=owner, workspace=workspace,
        )
        now = self._now()
        ack = command.acknowledged_at
        if (ack is None or ack < now - MAX_ACK_AGE
                or ack > now + MAX_CLOCK_SKEW
                or binding.credential_expires_at <= now
                or binding.state is not BrokerBindingState.ACTIVE
                or command.credential_generation != binding.credential_generation
                or command.state is not BrokerCommandState.ACKNOWLEDGED
                or command.termination != "exited" or command.exit_code != 0
                or not command.admission_ref or not command.evidence_ref):
            raise TextResultRefused("successful admitted local execution required")

    def _read_gate(self, *, command_id: str, run_id: str, binding_ref: str,
                   owner: str, workspace: str):
        """The read-time half of the body gate: current authority only.

        Revocation, rotation and compaction must fail closed, so the read
        re-derives the command from current canonical state and re-checks the
        binding lifecycle, generation, acknowledgement outcome and evidence
        presence. Retention is bounded by the row's own expiry rather than by
        re-testing the write-time acknowledgement recency.
        """

        binding, command = self._canonical_command(
            command_id=command_id, run_id=run_id, binding_ref=binding_ref,
            owner=owner, workspace=workspace,
        )
        now = self._now()
        if (binding.credential_expires_at <= now
                or binding.state is not BrokerBindingState.ACTIVE
                or command.credential_generation != binding.credential_generation
                or command.state is not BrokerCommandState.ACKNOWLEDGED
                or command.termination != "exited" or command.exit_code != 0
                or not command.admission_ref or not command.evidence_ref
                or not command.tool_request_ref or not command.request_id
                or not command.revision_ref or not command.request_fingerprint):
            raise TextResultRefused("verified file text authority is no longer current")
        return command

    def _unregistered_answer(self, *, command_id: str, run_id: str,
                             owner: str, workspace: str) -> dict:
        """What an *absent* row means, decided from canonical task state.

        Absence alone is not evidence that a task was ordinary, so the generic
        answer is only served when the canonical command **has a terminal fact**
        for this exact device scope: an acknowledged execution whose final state
        is already durable, with no registered file-read intent.

        Anything else — a command that never reached a terminal fact, a foreign
        scope, a revoked or rotated binding, or canonical state this reader
        cannot resolve — is refused. Answering ``other`` there would assert a
        finality the broker never proved, and the consumer derives the message id
        from the command, so a wrong negative answer consumes the very id the
        verified text needs.
        """

        binding, command = self._canonical_command_by_scope(
            command_id=command_id, run_id=run_id, owner=owner, workspace=workspace,
        )
        now = self._now()
        if (binding.credential_expires_at <= now
                or binding.state is not BrokerBindingState.ACTIVE
                or command.credential_generation != binding.credential_generation
                or command.state is not BrokerCommandState.ACKNOWLEDGED
                or not command.admission_ref or not command.evidence_ref):
            raise TextResultRefused("task type cannot be confirmed from current authority")
        return {"ok": True, "available": False, "kind": "other"}

    def record(self, payload: dict, *, binding_ref: str, owner: str,
               workspace: str) -> dict:
        """Stage one device-reported text read for an already-successful command."""

        if type(payload) is not dict:
            raise TextResultRefused("text result wire must be a mapping")
        state = payload.get("state")
        if state == STATE_PENDING:
            expected = _WIRE_COMMON
        elif state == STATE_CONTENT:
            expected = _WIRE_COMMON | _WIRE_CONTENT
        else:
            raise TextResultRefused("text result state is not a canonical state")
        if frozenset(payload) != expected:
            raise TextResultRefused("text result wire schema mismatch")
        if payload["contract_version"] != TEXT_RESULT_WIRE_VERSION:
            raise TextResultRefused("text result wire version mismatch")

        command_id = safe_ref(payload["command_id"], "command_id")
        run_id = safe_ref(payload["run_id"], "run_id")
        binding_ref = safe_ref(binding_ref, "binding_ref")
        owner = safe_ref(owner, "owner")
        workspace = safe_ref(workspace, "workspace")
        fingerprint = _digest(payload["request_fingerprint"])

        content: str | None = None
        digest: str | None = None
        byte_count: int | None = None
        if state == STATE_CONTENT:
            content, digest = validate_text_body(
                payload["content_utf8"], digest=payload["content_sha256"],
                byte_count=payload["content_bytes"],
            )
            byte_count = len(content.encode("utf-8"))

        now = self._now()
        self._expire(now)
        if state == STATE_PENDING:
            # The intent marker may legally precede the ACK (#4139 race fix).
            self._intent_gate(
                command_id=command_id, run_id=run_id, binding_ref=binding_ref,
                owner=owner, workspace=workspace,
            )
        else:
            self._write_gate(
                command_id=command_id, run_id=run_id, binding_ref=binding_ref,
                owner=owner, workspace=workspace,
            )
        # The device asserts only the command it is reporting and that command's
        # exact admitted request fingerprint; every other correlation ref is read
        # back from the persisted canonical command, so a device cannot name
        # someone else's run, tool request or revision.
        _, command = self._canonical_command(
            command_id=command_id, run_id=run_id, binding_ref=binding_ref,
            owner=owner, workspace=workspace,
        )
        if command.request_fingerprint != fingerprint:
            raise TextResultRefused("text result does not match the admitted request")

        inserted = self._sql.exec(
            "INSERT OR IGNORE INTO local_agent_text_result "
            "(command_id,binding_ref,account_ref,workspace_ref,run_id,tool_request_ref,"
            "request_id,revision_ref,evidence_ref,request_fingerprint,state,"
            "content_utf8,content_sha256,content_bytes,received_at,expires_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            command_id, binding_ref, owner, workspace, run_id, command.tool_request_ref,
            command.request_id, command.revision_ref, command.evidence_ref,
            fingerprint, state, content, digest, byte_count, now.isoformat(),
            (now + TEXT_RESULT_RETENTION).isoformat(),
        )
        rows_written(inserted)
        existing = rows(self._sql.exec(
            "SELECT state,content_sha256,content_bytes FROM local_agent_text_result "
            "WHERE command_id=? AND account_ref=? AND workspace_ref=? AND run_id=?",
            command_id, owner, workspace, run_id,
        ))
        if len(existing) != 1:
            raise TextResultRefused("staged text result is unavailable")
        current_state = row_value(existing[0], "state")
        if current_state == STATE_PENDING and state == STATE_CONTENT:
            # pending -> content is the only progression; it happens once.
            self._sql.exec(
                "UPDATE local_agent_text_result SET state=?,content_utf8=?,"
                "content_sha256=?,content_bytes=? WHERE command_id=? AND state=?",
                STATE_CONTENT, content, digest, byte_count, command_id, STATE_PENDING,
            )
            existing = rows(self._sql.exec(
                "SELECT state,content_sha256,content_bytes FROM local_agent_text_result "
                "WHERE command_id=?", command_id,
            ))
        stored_state = row_value(existing[0], "state")
        if (stored_state != state
                or (state == STATE_CONTENT
                    and (row_value(existing[0], "content_sha256") != digest
                         or row_value(existing[0], "content_bytes") != byte_count))):
            raise TextResultRefused("text result replay conflict")
        return {
            "stored": True,
            "reused": stored_state == state and rows_written(inserted) == 0,
            "state": stored_state,
            "content_present": stored_state == STATE_CONTENT,
        }

    def read(self, *, owner: str | None = None, workspace: str | None = None,
             run_id: str | None = None, command_id: str | None = None,
             scope_proof: dict | None = None) -> dict:
        """PRIVATE RPC only. Never reachable from a public device route."""

        if scope_proof is not None:
            # #4139: alternative scope for realms where the caller's product
            # user id differs from the canonical account_ref. The proof bundle
            # (command correlation the caller proved owning server-side via
            # history) locates exactly one staged row; the scope is derived
            # from that row's own account, never from caller naming. Both
            # modes at once are ambiguous and refused.
            if owner is not None:
                raise TextResultRefused("text result scope modes are exclusive")
            if not isinstance(scope_proof, dict) or set(scope_proof) != _SCOPE_PROOF_KEYS:
                raise TextResultRefused("text result scope proof schema mismatch")
            proof_command = safe_ref(scope_proof.get("command_id"), "scope_proof.command_id")
            proof_run = safe_ref(scope_proof.get("run_id"), "scope_proof.run_id")
            proof_fingerprint = scope_proof.get("request_fingerprint")
            if not isinstance(proof_fingerprint, str) or not _SHA256.fullmatch(proof_fingerprint):
                raise TextResultRefused("text result scope proof fingerprint mismatch")
            if run_id is not None and run_id != proof_run:
                raise TextResultRefused("text result scope proof run mismatch")
            if command_id is not None and command_id != proof_command:
                raise TextResultRefused("text result scope proof command mismatch")
            expected_workspace = None
            if workspace is not None:
                if not isinstance(workspace, str):
                    raise TextResultRefused("text result scope workspace mismatch")
                expected_workspace = workspace
            found = rows(self._sql.exec(
                "SELECT binding_ref,account_ref,workspace_ref,run_id,state FROM "
                "local_agent_text_result WHERE command_id=? AND run_id=? AND request_fingerprint=?",
                proof_command, proof_run, proof_fingerprint,
            ))
            if len(found) != 1:
                # Nothing staged (or ambiguous, which cannot happen under the
                # PRIMARY KEY): retryable unavailability, never a generic
                # "other" that would consume the conversation's message id.
                raise TextResultRefused("staged text result is unavailable")
            owner = row_value(found[0], "account_ref")
            workspace = row_value(found[0], "workspace_ref")
            if expected_workspace is not None and workspace != expected_workspace:
                raise TextResultRefused("text result scope workspace mismatch")
            run_id = proof_run
            command_id = proof_command
        else:
            if owner is None:
                raise TextResultRefused("text result owner scope is required")
            owner = safe_ref(owner, "owner")
            workspace = safe_ref(workspace, "workspace")
            run_id = safe_ref(run_id, "run_id")
            command_id = safe_ref(command_id, "command_id")
        self._expire(self._now())
        result = rows(self._sql.exec(
            "SELECT binding_ref,state,content_utf8,content_sha256,tool_request_ref,"
            "request_id,revision_ref,evidence_ref,request_fingerprint "
            "FROM local_agent_text_result WHERE command_id=? AND account_ref=? "
            "AND workspace_ref=? AND run_id=?",
            command_id, owner, workspace, run_id,
        ))
        if len(result) == 0:
            # Absence is a question, not an answer: the canonical task decides
            # whether this is a generic command or an unconfirmable task type.
            return self._unregistered_answer(
                command_id=command_id, run_id=run_id, owner=owner, workspace=workspace,
            )
        if len(result) != 1:
            raise TextResultRefused("ambiguous text result")
        item = result[0]
        if row_value(item, "state") == STATE_PENDING:
            # Declared, body not yet transported: the conversation must wait.
            # The hold re-checks current admission-level authority only; the
            # strict successful-terminal gate guards the body below.
            self._intent_gate(
                command_id=command_id, run_id=run_id,
                binding_ref=row_value(item, "binding_ref"), owner=owner, workspace=workspace,
            )
            return {"ok": True, "available": False, "kind": "file_read_text"}
        command = self._read_gate(
            command_id=command_id, run_id=run_id,
            binding_ref=row_value(item, "binding_ref"), owner=owner, workspace=workspace,
        )
        value = row_value(item, "content_utf8")
        digest = row_value(item, "content_sha256")
        content, digest = validate_text_body(
            value, digest=digest, byte_count=len(value.encode("utf-8")),
        )
        # Correlation is served from the canonical command, so the receipt can
        # only ever describe the command the run is actually bound to.
        correlation = {
            "command_id": command_id,
            "run_id": run_id,
            "tool_request_ref": command.tool_request_ref,
            "request_id": command.request_id,
            "revision_ref": command.revision_ref,
            "evidence_ref": command.evidence_ref,
            "request_fingerprint": command.request_fingerprint,
        }
        if any(row_value(item, key) != correlation[key] for key in (
            "tool_request_ref", "request_id", "revision_ref", "evidence_ref",
            "request_fingerprint",
        )):
            raise TextResultRefused("stored text result correlation changed")
        return {
            "ok": True, "available": True, "kind": "file_read_text",
            "account_ref": owner, "workspace_ref": workspace,
            **correlation, "content_utf8": content, "content_sha256": digest,
        }

    def purge_binding(self, binding_ref: str) -> None:
        binding_ref = safe_ref(binding_ref, "binding_ref")
        self._sql.exec(
            "DELETE FROM local_agent_text_result WHERE binding_ref=?", binding_ref,
        )


def compose_broker_text_results(*, storage: Any, state_port: Any,
                               authority_ref: str) -> BrokerTextResultStore:
    """The one composition the Broker Durable Object uses.

    Deliberately ungated: this stores a bounded *read result* for a command that
    already executed successfully, and it grants nothing. The Office staging lane
    stays feature-off because it stages binary document bytes; this path adds no
    execution, approval or write authority, so a deployment flag here would only
    make the merged consumer's own hold contract unreachable.
    """

    return BrokerTextResultStore(
        storage=storage, state_port=state_port, authority_ref=authority_ref,
    )


def read_verified_file_text_rpc(store: BrokerTextResultStore | None,
                                payload: dict) -> dict:
    """PRIVATE Service Binding only, never a public device HTTP route.

    Returns exactly the shapes #4687's ``verify_broker_file_text`` accepts: the
    two three-key "no content" answers, or the closed fourteen-field receipt. A
    receipt it cannot prove is an ``ok:false`` refusal, which the consumer turns
    into a retryable ``file_text_unverified`` rather than a false completion.
    """

    if store is None or type(payload) is not dict:
        return {"ok": False, "error": {"code": "verified_file_text_unavailable"}}
    try:
        if "scope_proof" in payload:
            if frozenset(payload) - {"scope_proof", "workspace_ref", "run_id", "command_id"}:
                raise TextResultRefused("closed private reader contract required")
            if "account_ref" in payload:
                raise TextResultRefused("closed private reader contract required")
            return store.read(
                scope_proof=payload["scope_proof"],
                workspace=payload.get("workspace_ref"),
                run_id=payload.get("run_id"),
                command_id=payload.get("command_id"),
            )
        if frozenset(payload) != _READ_KEYS:
            raise TextResultRefused("closed private reader contract required")
        return store.read(
            owner=payload["account_ref"], workspace=payload["workspace_ref"],
            run_id=payload["run_id"], command_id=payload["command_id"],
        )
    except Exception:
        return {"ok": False, "error": {"code": "verified_file_text_unavailable"}}


VERIFIED_FILE_TEXT_PRODUCER = "canonical_broker_file_text_v1"
NEW_TEXT_TABLE = True
SECOND_BROKER = False
SECOND_DEVICE_AUTH = False
OFFICE_PATH_UNCHANGED = True
GENERIC_STDOUT_TRUSTED = False
PRODUCTION_MUTATION = False
