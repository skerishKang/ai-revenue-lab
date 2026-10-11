"""#3580 private, durable, one-shot relay of FIRST-PARTY Engine Office READ evidence.

This is a server-injected sink, NOT a new approval issuer, HTTP API, Broker
dispatcher, device grant or Resident plan source. A trusted authenticated host
must resolve the pre-existing exact owner/session/Broker command binding.
Nothing here opens files, uploads data, or changes the default Engine wiring.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import inspect
import json
from pathlib import Path
import re
import sqlite3
from typing import Callable

from padiem_ai_core.agent_approval import (
    ApprovalOutcome, ApprovalPause, ApprovalRequirement, VerifiedApprovalDecision,
)

from .hark_office_p01_receipt import ApprovedOfficeReadReceipt

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,127}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_MAX_TTL = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class TrustedOfficeReadCommandBinding:
    """Exact, ALREADY authenticated server-side owner and Broker command identity.

    Callers cannot make a binding authoritative by merely instantiating this
    dataclass. Only a host-owned binding resolver may supply one.
    """
    owner_id: str
    workspace_id: str
    session_id: str
    run_id: str
    device_id: str
    root_ref: str
    request_fingerprint: str
    binding_ref: str
    command_id: str
    tool_request_ref: str
    request_id: str
    revision_ref: str
    command_fingerprint: str
    sequence: int

    def __post_init__(self) -> None:
        for name in (
            "owner_id", "workspace_id", "session_id", "run_id", "device_id",
            "root_ref", "binding_ref", "command_id", "tool_request_ref",
            "request_id", "revision_ref",
        ):
            value = getattr(self, name)
            if type(value) is not str or not _ID.fullmatch(value):
                raise ValueError(f"invalid trusted command {name}")
        for name in ("request_fingerprint", "command_fingerprint"):
            if type(getattr(self, name)) is not str or not _SHA.fullmatch(getattr(self, name)):
                raise ValueError(f"invalid trusted command {name}")
        if type(self.sequence) is not int or self.sequence <= 0:
            raise ValueError("invalid trusted command sequence")

    def matches_receipt(self, receipt: ApprovedOfficeReadReceipt) -> bool:
        if not isinstance(receipt, ApprovedOfficeReadReceipt):
            return False
        args = dict(receipt.exact_tool_arguments)
        return (
            receipt.pause.run_id == self.run_id
            and args["run_id"] == self.run_id
            and args["device_id"] == self.device_id
            and args["root_ref"] == self.root_ref
            and receipt.request_fingerprint == self.request_fingerprint
        )


@dataclass(frozen=True, slots=True)
class RedeemedOfficeReadEvidence:
    """Private evidence only; never equivalent to Windows local file authority."""
    binding: TrustedOfficeReadCommandBinding
    receipt: ApprovedOfficeReadReceipt


def _encode_receipt(receipt: ApprovedOfficeReadReceipt) -> str:
    payload = {
        "app_id": receipt.app_id,
        "continuation_ref": receipt.continuation_ref,
        "pause": asdict(receipt.pause),
        "decision": asdict(receipt.verified_decision),
        "exact_tool_arguments": list(receipt.exact_tool_arguments),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=lambda v: (
        v.isoformat() if isinstance(v, datetime) else v.value
    ))


def _decode_receipt(encoded: str) -> ApprovedOfficeReadReceipt:
    payload = json.loads(encoded)
    p = payload["pause"]
    d = payload["decision"]
    p["created_at"] = datetime.fromisoformat(p["created_at"])
    p["expires_at"] = datetime.fromisoformat(p["expires_at"])
    p["requirement"] = ApprovalRequirement(p["requirement"])
    p["approval_scope"] = tuple(p["approval_scope"])
    d["decided_at"] = datetime.fromisoformat(d["decided_at"])
    d["outcome"] = ApprovalOutcome(d["outcome"])
    return ApprovedOfficeReadReceipt(
        app_id=payload["app_id"], continuation_ref=payload["continuation_ref"],
        pause=ApprovalPause(**p), verified_decision=VerifiedApprovalDecision(**d),
        exact_tool_arguments=tuple(tuple(pair) for pair in payload["exact_tool_arguments"]),
    )


class PrivateDurableOfficeReadLedger:
    """Server-side SQLite transaction store with one-time, exact-command redemption.

    Storage must be on host-private persistent media with appropriate OS ACLs.
    This has no public routes, no environment-driven fallback and no untrusted
    client minting interface. Not enabled until an authenticated host injects it.
    """

    def __init__(
        self, *, database_path: str | Path,
        trusted_binding_resolver: Callable[[ApprovedOfficeReadReceipt], object],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not callable(trusted_binding_resolver):
            raise ValueError("trusted command binding resolver required")
        self._path = Path(database_path)
        if not self._path.parent.is_dir() or self._path.is_symlink():
            raise ValueError("secure existing private database directory required")
        self._resolve_binding = trusted_binding_resolver
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        with self._open() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS office_read_receipt_v1 (
                request_fingerprint TEXT PRIMARY KEY,
                decision_id TEXT NOT NULL UNIQUE,
                command_binding_json TEXT NOT NULL,
                receipt_json TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                consumed_at TEXT
            )""")

    def _open(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self._path), timeout=5, isolation_level=None)
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _now(self) -> datetime:
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("aware server clock required")
        return now.astimezone(timezone.utc)

    async def record_verified_office_read(self, receipt: ApprovedOfficeReadReceipt) -> bool:
        if not isinstance(receipt, ApprovedOfficeReadReceipt):
            raise ValueError("canonical Engine verified READ receipt required")
        binding = self._resolve_binding(receipt)
        if inspect.isawaitable(binding):
            binding = await binding
        if not isinstance(binding, TrustedOfficeReadCommandBinding):
            raise ValueError("no authenticated owner/Broker binding for receipt")
        if not binding.matches_receipt(receipt):
            raise ValueError("Engine receipt does not match authenticated Broker request")
        now = self._now()
        expires = min(receipt.pause.expires_at.astimezone(timezone.utc), now + _MAX_TTL)
        if receipt.verified_decision.decided_at > now + timedelta(seconds=30) or expires <= now:
            raise ValueError("Office receipt expired or future dated")
        with self._open() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute(
                    "INSERT INTO office_read_receipt_v1 "
                    "(request_fingerprint, decision_id, command_binding_json, receipt_json, expires_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (receipt.request_fingerprint, receipt.verified_decision.decision_id,
                     json.dumps(asdict(binding), sort_keys=True, separators=(",", ":")),
                     _encode_receipt(receipt), expires.isoformat()),
                )
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
        return True

    def redeem_for_trusted_command(
        self, binding: TrustedOfficeReadCommandBinding,
    ) -> RedeemedOfficeReadEvidence | None:
        """Caller MUST have authenticated this exact owner/session/device/command.

        Atomic consume happens before yielding evidence; a lost response must
        not be retried as a new permission. Wrong-scope lookup is nondisclosing.
        """
        if not isinstance(binding, TrustedOfficeReadCommandBinding):
            raise ValueError("authenticated command binding required")
        now = self._now()
        with self._open() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    "SELECT command_binding_json, receipt_json, expires_at "
                    "FROM office_read_receipt_v1 "
                    "WHERE request_fingerprint=? AND consumed_at IS NULL",
                    (binding.request_fingerprint,),
                ).fetchone()
                if row is None or row[0] != json.dumps(
                    asdict(binding), sort_keys=True, separators=(",", ":")
                ) or datetime.fromisoformat(row[2]) <= now:
                    db.execute("COMMIT")
                    return None
                receipt = _decode_receipt(row[1])
                if not binding.matches_receipt(receipt):
                    raise ValueError("stored Office evidence integrity mismatch")
                updated = db.execute(
                    "UPDATE office_read_receipt_v1 SET consumed_at=? "
                    "WHERE request_fingerprint=? AND consumed_at IS NULL",
                    (now.isoformat(), binding.request_fingerprint),
                )
                if updated.rowcount != 1:
                    raise ValueError("Office evidence already consumed")
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
        return RedeemedOfficeReadEvidence(binding=binding, receipt=receipt)


PRIVATE_LEDGER_MINTS_DEVICE_GRANT = False
PRIVATE_LEDGER_HAS_PUBLIC_HTTP_ROUTE = False
