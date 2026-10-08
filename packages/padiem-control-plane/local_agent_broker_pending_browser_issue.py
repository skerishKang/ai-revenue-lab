"""#3782 source-only first-party pending browser.control command issuance ledger.

A pending owner ticket is NOT a human P01 decision. The separate authenticated
ticket reader MUST validate current original Engine pause, first-party user,
workspace and device association. Product installs no such reader today.

Broker mints the command ID and canonical revision itself, then stores the
immutable ticket->command association in the SAME Durable Object transaction.
Public process.execute RPCs never call this issuer. No browser material, URL,
text, credentials, decision or approval evidence is written to this ledger.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from local_agent_broker_browser_control_take import BrowserControlCommandTakeCorrelation
from local_agent_broker_original_engine_async_source import (
    ServerOwnedBrokerOriginalRunAssociation,
)
from local_agent_broker_sql_state import (
    iso,
    parse_iso,
    row_value,
    rows,
    rows_written,
    safe_ref,
    utc,
)
from padiem_control_plane.local_agent_broker import (
    BrokerCommandCapability,
    BrokerCommandRecord,
    BrokerCommandState,
)

_SHA = re.compile(r"^[0-9a-f]{64}$")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS local_agent_browser_pending_owner_ticket (
  ticket_ref TEXT PRIMARY KEY,
  command_ref TEXT NOT NULL UNIQUE,
  binding_ref TEXT NOT NULL,
  workspace_ref TEXT NOT NULL,
  device_ref TEXT NOT NULL,
  owner_ref TEXT NOT NULL,
  broker_run_ref TEXT NOT NULL,
  broker_request_fingerprint TEXT NOT NULL,
  revision_ref TEXT NOT NULL,
  engine_app_id TEXT NOT NULL,
  engine_continuation_ref TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  retired_at TEXT NULL
)
"""
PENDING_BROWSER_TICKET_PRODUCT_ISSUER_WIRED = False


@dataclass(frozen=True, slots=True)
class AuthenticatedPendingBrowserWorkTicket:
    """Only a live first-party Engine/owner-ticket/session authority may supply.

    A dataclass object alone does NOT authenticate provenance; the producer
    must verify independently with Engine D1 and current Control Plane session.
    """

    ticket_ref: str
    binding_ref: str
    workspace_ref: str
    device_ref: str
    owner_ref: str
    broker_run_ref: str
    tool_request_ref: str
    browser_request_fingerprint: str
    engine_app_id: str
    engine_continuation_ref: str
    engine_run_ref: str
    original_request_fingerprint: str
    original_admission_decision_id: str
    browser_invocation_sha256: str
    expires_at: datetime

    def __post_init__(self) -> None:
        for key in (
            "ticket_ref", "binding_ref", "workspace_ref", "device_ref",
            "owner_ref", "broker_run_ref", "tool_request_ref", "engine_app_id",
            "engine_continuation_ref", "engine_run_ref",
            "original_admission_decision_id",
        ):
            safe_ref(getattr(self, key), key)
        if not self.engine_continuation_ref.startswith("cont_"):
            raise ValueError("original Engine continuation required")
        for key in (
            "browser_request_fingerprint",
            "original_request_fingerprint",
            "browser_invocation_sha256",
        ):
            value = getattr(self, key)
            if type(value) is not str or not _SHA.fullmatch(value):
                raise ValueError(f"{key} must be an exact lowercase sha256")
        utc(self.expires_at, "pending_ticket_expires_at")


class DurableBrokerPendingBrowserTicketStore:
    """Append-only ticket reference ledger; revoked/used tickets never remint."""

    def __init__(self, storage: Any) -> None:
        if not callable(getattr(getattr(storage, "sql", None), "exec", None)) or not callable(
            getattr(storage, "transactionSync", None)
        ):
            raise TypeError("canonical broker Durable Object SQL transaction required")
        self._sql = storage.sql
        self._sql.exec(_SCHEMA)

    def _register_in_existing_transaction(
        self, *, ticket: AuthenticatedPendingBrowserWorkTicket,
        command: BrokerCommandRecord, now: datetime,
    ) -> None:
        if type(ticket) is not AuthenticatedPendingBrowserWorkTicket or type(
            command
        ) is not BrokerCommandRecord:
            raise ValueError("verified first-party pending ticket and canonical command required")
        current = utc(now, "now")
        if (
            command.capability is not BrokerCommandCapability.BROWSER_CONTROL
            or command.state is not BrokerCommandState.QUEUED
            or ticket.expires_at <= current
            or not command.issued_at <= current < command.expires_at <= ticket.expires_at
            or command.binding_ref != ticket.binding_ref
            or command.run_id != ticket.broker_run_ref
            or command.tool_request_ref != ticket.tool_request_ref
            or command.request_fingerprint != ticket.browser_request_fingerprint
        ):
            raise ValueError("browser command does not match current issued ticket")
        if rows(self._sql.exec(
            "SELECT ticket_ref FROM local_agent_browser_pending_owner_ticket "
            "WHERE ticket_ref=? OR command_ref=?",
            ticket.ticket_ref, command.command_id,
        )):
            raise ValueError("owner ticket or broker command already issued")
        count = rows_written(self._sql.exec(
            "INSERT INTO local_agent_browser_pending_owner_ticket "
            "(ticket_ref,command_ref,binding_ref,workspace_ref,device_ref,owner_ref,"
            "broker_run_ref,broker_request_fingerprint,revision_ref,engine_app_id,"
            "engine_continuation_ref,expires_at,retired_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,NULL)",
            ticket.ticket_ref, command.command_id, ticket.binding_ref,
            ticket.workspace_ref, ticket.device_ref, ticket.owner_ref,
            ticket.broker_run_ref, ticket.browser_request_fingerprint,
            command.revision_ref, ticket.engine_app_id,
            ticket.engine_continuation_ref, iso(ticket.expires_at),
        ))
        if count != 1:
            raise ValueError("original pending owner ticket association was not committed")

    def resolve_for_admitted_command(
        self, *, scope: BrowserControlCommandTakeCorrelation, now: datetime,
    ) -> ServerOwnedBrokerOriginalRunAssociation:
        if type(scope) is not BrowserControlCommandTakeCorrelation:
            raise ValueError("canonical admitted Broker command scope required")
        now = utc(now, "now")
        matches = rows(self._sql.exec(
            "SELECT binding_ref,workspace_ref,device_ref,owner_ref,broker_run_ref,"
            "broker_request_fingerprint,revision_ref,engine_app_id,"
            "engine_continuation_ref,expires_at,retired_at "
            "FROM local_agent_browser_pending_owner_ticket WHERE command_ref=?",
            scope.command_ref,
        ))
        if len(matches) != 1:
            raise ValueError("server-issued pending original Engine ticket not found")
        data = matches[0]
        for name, value in (
            ("binding_ref", scope.binding_ref),
            ("workspace_ref", scope.workspace_ref),
            ("device_ref", scope.device_ref),
            ("owner_ref", scope.owner_ref),
            ("broker_run_ref", scope.run_ref),
            ("broker_request_fingerprint", scope.request_fingerprint),
            ("revision_ref", scope.revision_ref),
        ):
            if row_value(data, name) != value:
                raise ValueError("pending original Engine ticket scope changed")
        if (
            row_value(data, "retired_at") is not None
            or parse_iso(row_value(data, "expires_at"), "ticket_expiry") <= now
        ):
            raise ValueError("pending original Engine ticket expired or revoked")
        return ServerOwnedBrokerOriginalRunAssociation(
            command_ref=scope.command_ref,
            binding_ref=scope.binding_ref,
            request_id=scope.request_id,
            run_ref=scope.run_ref,
            broker_request_fingerprint=scope.request_fingerprint,
            admission_ref=scope.admission_ref,
            revision_ref=scope.revision_ref,
            engine_app_id=row_value(data, "engine_app_id"),
            engine_continuation_ref=row_value(data, "engine_continuation_ref"),
        )

    def retire_command(self, command_ref: str, *, now: datetime) -> int:
        """Retain immutable ticket tombstone; reject future ticket replay."""
        return rows_written(self._sql.exec(
            "UPDATE local_agent_browser_pending_owner_ticket "
            "SET retired_at=? WHERE command_ref=? AND retired_at IS NULL",
            iso(now), safe_ref(command_ref, "command_ref"),
        ))

    def retire_binding(self, binding_ref: str, *, now: datetime) -> int:
        return rows_written(self._sql.exec(
            "UPDATE local_agent_browser_pending_owner_ticket "
            "SET retired_at=? WHERE binding_ref=? AND retired_at IS NULL",
            iso(now), safe_ref(binding_ref, "binding_ref"),
        ))
