"""#3782 Broker-owned original Engine admission association, NOT P01 authority.

An immutable server-derived command->original-Engine association survives Broker
Durable Object restarts. Registration is ONLY from trusted composition with a
separate original-admission association owner, after canonical live Broker
device/command checks. No public issuer, RPC, caller-supplied join or grant.
The Engine still independently proves original admission and live P01 receipt.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from typing import Any

from local_agent_broker_browser_control_take import BrowserControlCommandTakeCorrelation
from local_agent_broker_engine_p01_bridge import BrokerEngineP01Join
from local_agent_broker_sql_state import (
    iso,
    parse_iso,
    row_value,
    rows,
    rows_written,
    utc,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS local_agent_browser_engine_original_join (
    command_ref TEXT PRIMARY KEY,
    binding_ref TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    admission_ref TEXT NOT NULL,
    revision_ref TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    join_json TEXT NOT NULL CHECK(length(join_json) BETWEEN 1 AND 4096)
)
"""


class DurableBrokerOriginalEngineJoinStore:
    """Immutable, exact-correlation DO SQLite join lookup; no P01 issuance."""

    def __init__(self, storage: Any):
        if (
            not callable(getattr(getattr(storage, "sql", None), "exec", None))
            or not callable(getattr(storage, "transactionSync", None))
        ):
            raise TypeError("canonical durable Broker SQLite authority required")
        self._storage = storage
        self._sql = storage.sql
        self._sql.exec(_SCHEMA)

    def _register_in_existing_transaction(
        self, *, scope: BrowserControlCommandTakeCorrelation,
        original: BrokerEngineP01Join, expires_at: datetime, now: datetime,
    ) -> None:
        """Caller must already have checked live admitted Broker and original.

        This API is strictly internal to the durable runtime's atomic owner.
        A constructed typed join is NOT itself independently authenticated.
        """
        if type(original) is not BrokerEngineP01Join:
            raise ValueError("independently resolved original Engine join required")
        original.assert_matches(scope)
        current = utc(now, "now")
        expiry = utc(expires_at, "join_expiry")
        if expiry <= current:
            raise ValueError("original Engine join expired")
        raw = json.dumps(asdict(original), sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(raw.encode("utf-8")) > 4096:
            raise ValueError("original Engine join exceeds durable bound")
        if rows(self._sql.exec(
            "SELECT command_ref FROM local_agent_browser_engine_original_join WHERE command_ref=?",
            scope.command_ref,
        )):
            raise ValueError("original Engine command join already bound")
        count = rows_written(self._sql.exec(
            "INSERT INTO local_agent_browser_engine_original_join "
            "(command_ref,binding_ref,request_fingerprint,admission_ref,revision_ref,expires_at,join_json) "
            "VALUES(?,?,?,?,?,?,?)",
            scope.command_ref, scope.binding_ref, scope.request_fingerprint,
            scope.admission_ref, scope.revision_ref, iso(expiry), raw,
        ))
        if count != 1:
            raise ValueError("original Engine join could not be committed")

    def resolve_for_admitted_command(
        self, *, scope: BrowserControlCommandTakeCorrelation, now: datetime,
    ) -> BrokerEngineP01Join:
        """Read-only exact original association, NOT a permission decision."""
        if type(scope) is not BrowserControlCommandTakeCorrelation:
            raise ValueError("canonical Broker command scope required")
        current = utc(now, "now")
        found = rows(self._sql.exec(
            "SELECT binding_ref,request_fingerprint,admission_ref,revision_ref,"
            "expires_at,join_json FROM local_agent_browser_engine_original_join "
            "WHERE command_ref=?",
            scope.command_ref,
        ))
        if len(found) != 1:
            raise ValueError("original Engine association not registered")
        record = found[0]
        if (
            row_value(record, "binding_ref") != scope.binding_ref
            or row_value(record, "request_fingerprint") != scope.request_fingerprint
            or row_value(record, "admission_ref") != scope.admission_ref
            or row_value(record, "revision_ref") != scope.revision_ref
            or parse_iso(row_value(record, "expires_at"), "join_expiry") <= current
        ):
            raise ValueError("original Engine association changed, expired or revoked")
        try:
            source = json.loads(row_value(record, "join_json"))
            if type(source) is not dict or set(source) != set(BrokerEngineP01Join.__dataclass_fields__):
                raise ValueError("invalid original join keys")
            join = BrokerEngineP01Join(**source)
            join.assert_matches(scope)
            return join
        except (ValueError, TypeError, KeyError):
            raise ValueError("original Engine association corrupted") from None

    def purge_command(self, command_ref: str) -> int:
        """Delete terminal command's original association inside Broker DO CAS.

        The canonical one-shot command id is permanently non-reusable under
        Broker's existing used-command-id ledger. Terminal cleanup removes
        linkability and prevents stale Engine approval metadata retention.
        """
        from local_agent_broker_sql_state import safe_ref

        return rows_written(self._sql.exec(
            "DELETE FROM local_agent_browser_engine_original_join WHERE command_ref=?",
            safe_ref(command_ref, "command_ref"),
        ))

    def purge_binding(self, binding_ref: str) -> int:
        """Rotation/revocation must permanently destroy the old join."""
        from local_agent_broker_sql_state import safe_ref

        return rows_written(self._sql.exec(
            "DELETE FROM local_agent_browser_engine_original_join WHERE binding_ref=?",
            safe_ref(binding_ref, "binding_ref"),
        ))


BROKER_ORIGINAL_ENGINE_JOIN_PRODUCT_ISSUER_WIRED = False
