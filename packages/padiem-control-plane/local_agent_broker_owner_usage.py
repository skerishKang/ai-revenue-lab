"""Durable, reversible owner PC use preference within the existing Broker DO.

This is a dispatch gate, not a new device-identity or ONLINE authority.
The canonical binding snapshot determines owner/workspace scope. The same
transactionSync boundary serializes pause with enqueue and admission.
"""
from __future__ import annotations

from typing import Any

from padiem_control_plane.local_agent_broker import BrokerBindingState
from local_agent_broker_sql_state import row_value, rows, safe_ref

_SCHEMA = """
CREATE TABLE IF NOT EXISTS local_agent_broker_owner_usage (
  authority_ref TEXT NOT NULL,
  account_ref TEXT NOT NULL,
  workspace_ref TEXT NOT NULL,
  paused INTEGER NOT NULL CHECK (paused IN (0,1)),
  PRIMARY KEY (authority_ref, account_ref, workspace_ref)
)
"""
_KEYS = frozenset({"account_ref","workspace_ref","paused"})


def _error(code: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": "PC use state cannot be changed."}}


class BrokerOwnerUsageStore:
    """Owner-scoped usage choice co-located with canonical Broker state."""

    def __init__(self, storage: Any, authority_ref: str) -> None:
        self._sql = storage.sql
        self._authority = safe_ref(authority_ref, "authority_ref")
        self._sql.exec(_SCHEMA)

    def paused(self, account_ref: str, workspace_ref: str) -> bool:
        account = safe_ref(account_ref, "account_ref")
        workspace = safe_ref(workspace_ref, "workspace_ref")
        result = rows(self._sql.exec(
            "SELECT paused FROM local_agent_broker_owner_usage "
            "WHERE authority_ref=? AND account_ref=? AND workspace_ref=?",
            self._authority, account, workspace))
        if not result:
            return False
        if len(result) != 1 or row_value(result[0], "paused") not in (0, 1):
            raise RuntimeError("invalid owner usage state")
        return row_value(result[0], "paused") == 1

    def set(self, payload: Any, snapshot: Any) -> dict:
        if not isinstance(payload, dict) or set(payload) != _KEYS:
            return _error("invalid_owner_usage_request")
        try:
            account = safe_ref(payload["account_ref"], "account_ref")
            workspace = safe_ref(payload["workspace_ref"], "workspace_ref")
        except (TypeError, ValueError):
            return _error("invalid_owner_usage_request")
        if type(payload["paused"]) is not bool:
            return _error("invalid_owner_usage_request")
        if not any(
            binding.account_ref == account and binding.workspace_ref == workspace
            and binding.state is BrokerBindingState.ACTIVE
            for binding in snapshot.bindings
        ):
            return _error("owner_usage_no_active_device")
        paused = payload["paused"]
        self._sql.exec(
            "INSERT INTO local_agent_broker_owner_usage "
            "(authority_ref,account_ref,workspace_ref,paused) VALUES(?,?,?,?) "
            "ON CONFLICT(authority_ref,account_ref,workspace_ref) "
            "DO UPDATE SET paused=excluded.paused",
            self._authority, account, workspace, int(paused))
        return {"ok": True, "paused": paused, "dispatch_authorized": not paused}

    def paused_binding(self, snapshot: Any, binding_ref: Any) -> bool:
        if not isinstance(binding_ref, str):
            return False  # Canonical Broker rejects malformed binding refs.
        for binding in snapshot.bindings:
            if binding.binding_ref == binding_ref:
                return self.paused(binding.account_ref, binding.workspace_ref)
        return False

    def paused_command(self, snapshot: Any, command_id: Any) -> bool:
        if not isinstance(command_id, str):
            return False
        for command in snapshot.commands:
            if command.command_id == command_id:
                return self.paused_binding(snapshot, command.binding_ref)
        return False
