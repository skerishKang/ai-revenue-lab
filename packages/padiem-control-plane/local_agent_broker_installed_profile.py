"""#4139 — installed Windows executable profile over the existing authenticated Broker.

One small table in the EXISTING Broker DO SQLite storage. No separate identity,
credential, Worker, endpoint authority, or server-side executable discovery.
The enrolled Resident supplies the local trusted execution path after its normal
authenticated session; reads revalidate the current Broker binding generation.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable

from padiem_control_plane.local_agent_broker import BrokerBindingState
from local_agent_broker_sql_state import rows, row_value, safe_ref

PROFILE_REF = "profile.3140.python"
PROFILE_DEVICE_ROUTE = "/execution-profile"
PROFILE_CONTRACT_VERSION = "claw-local-installed-execution-profile.v1"
_WRITE_KEYS = frozenset({"contract_version", "session_id", "profile_ref", "executable_path"})
_READ_KEYS = frozenset({"account_ref", "workspace_ref", "device_id", "binding_ref", "profile_ref"})
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:\\")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS local_agent_installed_executable_profile (
 binding_ref TEXT PRIMARY KEY, account_ref TEXT NOT NULL,
 workspace_ref TEXT NOT NULL, device_id TEXT NOT NULL,
 credential_generation INTEGER NOT NULL, profile_ref TEXT NOT NULL,
 executable_path TEXT NOT NULL, session_id TEXT NOT NULL,
 supplied_at TEXT NOT NULL
);
"""


class InstalledProfileRefused(ValueError):
    pass


def valid_installed_executable_path(value: Any) -> str:
    """A bounded Windows absolute .exe, never a worker or browser-provided path."""
    if (type(value) is not str or not 8 <= len(value) <= 1024
            or not _WINDOWS_DRIVE.match(value) or not value.lower().endswith(".exe")
            or "/" in value or "%" in value or any(
                char in '<>"|?*' or ord(char) < 32 for char in value[3:]
            ) or ":" in value[3:] or value.endswith((" ", "."))):
        raise InstalledProfileRefused("installed Windows absolute executable required")
    parts = value[3:].split("\\")
    if not parts or any(
        not part or part in (".", "..") or part.endswith((" ", "."))
        for part in parts
    ):
        raise InstalledProfileRefused("noncanonical installed executable path")
    return value


class BrokerInstalledExecutionProfileStore:
    def __init__(self, *, storage: Any, state_port: Any, authority_ref: str,
                 clock=None) -> None:
        sql = getattr(storage, "sql", None)
        if not callable(getattr(sql, "exec", None)):
            raise InstalledProfileRefused("Broker durable SQLite required")
        self._sql = sql
        self._state = state_port
        self._authority = safe_ref(authority_ref, "authority_ref")
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        for statement in _SCHEMA.split(";"):
            if statement.strip():
                self._sql.exec(statement)

    def _binding(self, *, binding_ref: str, account_ref: str, workspace_ref: str,
                 device_id: str, generation: int):
        snapshot = self._state.load(authority_ref=self._authority).snapshot
        matches = [b for b in snapshot.bindings if
                   b.binding_ref == binding_ref and b.account_ref == account_ref
                   and b.workspace_ref == workspace_ref and b.device_id == device_id]
        if (len(matches) != 1 or matches[0].state is not BrokerBindingState.ACTIVE
                or matches[0].credential_expires_at <= self._clock()
                or matches[0].credential_generation != generation):
            raise InstalledProfileRefused("canonical active binding generation required")
        return matches[0]

    def record(self, payload: dict, *, binding: Any, session: dict) -> dict:
        """Called ONLY inside Broker transaction after credential AND session auth."""
        if type(payload) is not dict or frozenset(payload) != _WRITE_KEYS:
            raise InstalledProfileRefused("closed device profile payload required")
        if (payload["contract_version"] != PROFILE_CONTRACT_VERSION
                or payload["profile_ref"] != PROFILE_REF
                or type(session) is not dict or session.get("authenticated") is not True
                or session.get("session_id") != payload["session_id"]):
            raise InstalledProfileRefused("authenticated session profile required")
        for key in ("binding_ref", "device_id", "account_ref", "workspace_ref",
                    "credential_generation"):
            if session.get(key) != getattr(binding, key):
                raise InstalledProfileRefused("session/binding generation mismatch")
        generation = session.get("credential_generation")
        if type(generation) is not int or generation < 1:
            raise InstalledProfileRefused("canonical credential generation required")
        self._binding(binding_ref=binding.binding_ref, account_ref=binding.account_ref,
                      workspace_ref=binding.workspace_ref, device_id=binding.device_id,
                      generation=generation)
        path = valid_installed_executable_path(payload["executable_path"])
        session_id = safe_ref(session["session_id"], "session_id")
        scope = (binding.binding_ref, binding.account_ref, binding.workspace_ref,
                 binding.device_id, generation, PROFILE_REF, path, session_id)
        # The authenticated active session may refresh the installation path.
        # A rotated/revoked generation cannot submit because authentication and
        # the current canonical binding check above must both pass.
        self._sql.exec(
            "INSERT INTO local_agent_installed_executable_profile "
            "(binding_ref,account_ref,workspace_ref,device_id,credential_generation,"
            "profile_ref,executable_path,session_id,supplied_at) "
            "VALUES (?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(binding_ref) DO UPDATE SET "
            "account_ref=excluded.account_ref,workspace_ref=excluded.workspace_ref,"
            "device_id=excluded.device_id,credential_generation=excluded.credential_generation,"
            "profile_ref=excluded.profile_ref,executable_path=excluded.executable_path,"
            "session_id=excluded.session_id,supplied_at=excluded.supplied_at",
            *scope, self._clock().isoformat(),
        )
        return {"accepted": True, "profile_ref": PROFILE_REF,
                "credential_generation": generation, "raw_device_credential": False}

    def read(self, payload: dict) -> dict:
        """Private read; broker state — never a saved boolean — verifies scope."""
        if type(payload) is not dict or frozenset(payload) != _READ_KEYS:
            raise InstalledProfileRefused("closed trusted private profile lookup required")
        scope = {key: safe_ref(payload[key], key) for key in _READ_KEYS}
        if scope["profile_ref"] != PROFILE_REF:
            raise InstalledProfileRefused("unsupported installed execution profile")
        found = rows(self._sql.exec(
            "SELECT binding_ref,account_ref,workspace_ref,device_id,"
            "credential_generation,profile_ref,executable_path FROM "
            "local_agent_installed_executable_profile WHERE binding_ref=?",
            scope["binding_ref"],
        ))
        if len(found) != 1:
            raise InstalledProfileRefused("installed profile not supplied")
        stored = found[0]
        if any(row_value(stored, key) != value for key, value in scope.items()):
            raise InstalledProfileRefused("installed profile owner/binding mismatch")
        generation = row_value(stored, "credential_generation")
        if type(generation) is not int or generation < 1:
            raise InstalledProfileRefused("installed profile generation invalid")
        self._binding(binding_ref=scope["binding_ref"],
                      account_ref=scope["account_ref"],
                      workspace_ref=scope["workspace_ref"],
                      device_id=scope["device_id"], generation=generation)
        path = valid_installed_executable_path(row_value(stored, "executable_path"))
        return {"ok": True, "profile": {**scope, "executable_path": path,
                                       "server_verified": True}}

    def purge_binding(self, binding_ref: str) -> None:
        self._sql.exec(
            "DELETE FROM local_agent_installed_executable_profile WHERE binding_ref=?",
            safe_ref(binding_ref, "binding_ref"),
        )


def installed_execution_profile_rpc(store: BrokerInstalledExecutionProfileStore | None,
                                    payload: dict) -> dict:
    """Private Service Binding read. Never expose through device/public GET."""
    if store is None:
        return {"ok": False, "error": {"code": "installed_execution_profile_unavailable"}}
    try:
        return store.read(payload)
    except (InstalledProfileRefused, KeyError, TypeError, ValueError):
        return {"ok": False, "error": {"code": "installed_execution_profile_unavailable"}}
