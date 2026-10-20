"""Durable, bounded PC device diagnostic hints inside the existing Broker DO.

The Connector observes three local facts the server cannot see: the Agent
source files, the Windows autostart entry and the supervised Resident. They
ride the heartbeat the device already sends, and this store keeps them next
to the canonical Broker state so the device directory can project them.

This is **not** a device-identity, ONLINE or permission authority. A hint is
a display label plus the fix the user can apply:

* it is never consulted by the online/executable/selectable decisions;
* it never carries a path, a credential, a token or a log line;
* it never invents a confirmed negative. A device that never reported, whose
  report stopped advancing, or whose read failed is ``unknown`` - the
  surface says "확인 불가" rather than "not installed" or "stopped".

Freshness is decided by the server's own clock and by a monotonic revision
the device advances on every observation, so a client can neither make a
stale report look fresh nor roll the observation back.

The table is created on first use, exactly like the existing owner-usage
store, so no migration or apply procedure is needed.
"""
from __future__ import annotations

from typing import Any, Mapping

from local_agent_broker_sql_state import row_value, rows, safe_ref

_SCHEMA = """
CREATE TABLE IF NOT EXISTS local_agent_broker_device_diagnostics (
  authority_ref TEXT NOT NULL,
  device_id TEXT NOT NULL,
  account_ref TEXT NOT NULL,
  workspace_ref TEXT NOT NULL,
  revision INTEGER NOT NULL CHECK (revision >= 0),
  agent_source TEXT NOT NULL,
  autostart TEXT NOT NULL,
  resident TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  PRIMARY KEY (authority_ref, device_id)
)
"""

#: The three closed labels. The same shape in every package that carries
#: this contract, and a parity test proves the copies match.
DIAGNOSTIC_KEYS = ("agent_source", "autostart", "resident")

#: The closed label vocabulary. ``unknown`` is the only value that means
#: "not observed", and it is never shown as a confirmed negative.
AGENT_SOURCE_STATES = ("ready", "not_installed", "invalid", "unknown")
AUTOSTART_STATES = ("enabled", "disabled", "unknown")
RESIDENT_STATES = ("running", "stopped", "unknown")
UNKNOWN = "unknown"

_STATE_VOCABULARY: Mapping[str, tuple[str, ...]] = {
    "agent_source": AGENT_SOURCE_STATES,
    "autostart": AUTOSTART_STATES,
    "resident": RESIDENT_STATES,
}

#: The hint shape the heartbeat carries.
_HINT_KEYS = frozenset({"version", "revision", "checks"})
_CHECK_KEYS = frozenset(DIAGNOSTIC_KEYS)
_VERSION = "padiem-pc-device-diagnostics.v1"

#: The maximum age of a hint whose revision has not advanced. After this,
#: the observation is treated as stale and the surface says "확인 불가".
MAX_HINT_AGE_SECONDS = 300

#: The maximum number of devices kept in the store.
MAX_DEVICES = 512


def _error(code: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": "PC diagnostic state cannot be stored."}}


def normalize_hint(raw: Any) -> dict[str, Any] | None:
    """Normalize one reported hint, or ``None`` when it is unusable.

    A partial hint, an unknown label or a hint with extra keys is refused
    rather than guessed. A refused hint leaves the previous observation
    untouched, so a malformed report can never replace a good one.
    """
    if not isinstance(raw, Mapping) or set(raw) != _HINT_KEYS:
        return None
    if raw.get("version") != _VERSION:
        return None
    revision = raw.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int):
        return None
    if revision < 0 or revision > 2**31 - 1:
        return None
    checks = raw.get("checks")
    if not isinstance(checks, Mapping) or set(checks) != _CHECK_KEYS:
        return None
    normalized: dict[str, str] = {}
    for key in _CHECK_KEYS:
        value = checks.get(key)
        if not isinstance(value, str) or value not in _STATE_VOCABULARY[key]:
            return None
        normalized[key] = value
    return {"version": _VERSION, "revision": revision, "checks": normalized}


class BrokerDeviceDiagnosticsStore:
    """Device-scoped display hints, co-located with canonical Broker state."""

    def __init__(self, storage: Any, authority_ref: str) -> None:
        self._sql = storage.sql
        self._authority = safe_ref(authority_ref, "authority_ref")
        self._sql.exec(_SCHEMA)

    def record(
        self,
        *,
        device_id: Any,
        account_ref: Any,
        workspace_ref: Any,
        hint: Any,
        observed_at: str,
    ) -> dict:
        """Store one hint for one device, or refuse it.

        A hint whose revision did not advance keeps the previous observation
        and only refreshes the moment it was seen, so a device that stopped
        observing becomes stale instead of pretending to be current.
        """
        normalized = normalize_hint(hint)
        if normalized is None:
            return _error("invalid_device_diagnostics")
        try:
            device = safe_ref(device_id, "device_id")
            account = safe_ref(account_ref, "account_ref")
            workspace = safe_ref(workspace_ref, "workspace_ref")
        except (TypeError, ValueError):
            return _error("invalid_device_diagnostics")
        if not isinstance(observed_at, str) or not observed_at:
            return _error("invalid_device_diagnostics")
        existing = self._row(device)
        revision = normalized["revision"]
        if existing is not None:
            stored_revision = int(existing["revision"])
            if revision < stored_revision:
                # A rolled-back observation is refused; the stored one stays.
                return _error("device_diagnostics_revision_rollback")
            if revision == stored_revision:
                # The same observation, seen again: keep the labels and only
                # refresh the moment, so the age still grows.
                self._sql.exec(
                    "UPDATE local_agent_broker_device_diagnostics "
                    "SET observed_at=? WHERE authority_ref=? AND device_id=?",
                    observed_at, self._authority, device,
                )
                return {"ok": True, "accepted": True, "advanced": False}
        self._sql.exec(
            "INSERT INTO local_agent_broker_device_diagnostics "
            "(authority_ref,device_id,account_ref,workspace_ref,revision,"
            "agent_source,autostart,resident,observed_at) VALUES(?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(authority_ref,device_id) DO UPDATE SET "
            "account_ref=excluded.account_ref, workspace_ref=excluded.workspace_ref, "
            "revision=excluded.revision, agent_source=excluded.agent_source, "
            "autostart=excluded.autostart, resident=excluded.resident, "
            "observed_at=excluded.observed_at",
            self._authority, device, account, workspace, revision,
            normalized["checks"]["agent_source"], normalized["checks"]["autostart"],
            normalized["checks"]["resident"], observed_at,
        )
        self._prune()
        return {"ok": True, "accepted": True, "advanced": True}

    def _row(self, device_id: str) -> dict | None:
        result = rows(self._sql.exec(
            "SELECT revision, agent_source, autostart, resident, observed_at "
            "FROM local_agent_broker_device_diagnostics "
            "WHERE authority_ref=? AND device_id=?",
            self._authority, device_id,
        ))
        if not result:
            return None
        if len(result) != 1:
            raise RuntimeError("invalid device diagnostics row")
        return {
            "revision": int(row_value(result[0], "revision")),
            "agent_source": row_value(result[0], "agent_source"),
            "autostart": row_value(result[0], "autostart"),
            "resident": row_value(result[0], "resident"),
            "observed_at": row_value(result[0], "observed_at"),
        }

    def _prune(self) -> None:
        """Keep the store bounded: the oldest observation goes first."""
        result = rows(self._sql.exec(
            "SELECT device_id FROM local_agent_broker_device_diagnostics "
            "WHERE authority_ref=? ORDER BY observed_at ASC",
            self._authority,
        ))
        if len(result) <= MAX_DEVICES:
            return
        for row in result[: len(result) - MAX_DEVICES]:
            self._sql.exec(
                "DELETE FROM local_agent_broker_device_diagnostics "
                "WHERE authority_ref=? AND device_id=?",
                self._authority, row_value(row, "device_id"),
            )

    def hint_for(self, device_id: Any) -> dict[str, Any] | None:
        """The stored hint for one device, with its freshness decided here.

        The returned mapping always carries a ``status``:

        * ``reported`` - the observation is current;
        * ``stale`` - the observation stopped advancing;
        * ``unavailable`` - nothing was ever reported for this device.

        It also carries the device id it was stored under, so the consumer
        can refuse a hint that was mixed into another device's row.
        """
        try:
            device = safe_ref(device_id, "device_id")
        except (TypeError, ValueError):
            return {"status": "unavailable", "checks": {}, "age_seconds": None}
        row = self._row(device)
        if row is None:
            return {
                "status": "unavailable", "device_id": device,
                "checks": {}, "age_seconds": None,
            }
        observed_at = row["observed_at"]
        age = _age_seconds(observed_at)
        if age is None or age > MAX_HINT_AGE_SECONDS:
            return {
                "status": "stale",
                "device_id": device,
                "checks": {
                    "agent_source": row["agent_source"],
                    "autostart": row["autostart"],
                    "resident": row["resident"],
                },
                "age_seconds": age,
            }
        return {
            "status": "reported",
            "device_id": device,
            "checks": {
                "agent_source": row["agent_source"],
                "autostart": row["autostart"],
                "resident": row["resident"],
            },
            "age_seconds": age,
        }


def _age_seconds(observed_at: str) -> float | None:
    """The age of an observation, measured by the server's own clock."""
    from datetime import datetime, timezone

    try:
        parsed = datetime.fromisoformat(observed_at.replace("Z", "++00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    now = datetime.now(timezone.utc)
    return (now - parsed.astimezone(timezone.utc)).total_seconds()


__all__ = [
    "AGENT_SOURCE_STATES",
    "DIAGNOSTIC_KEYS",
    "AUTOSTART_STATES",
    "MAX_DEVICES",
    "MAX_HINT_AGE_SECONDS",
    "RESIDENT_STATES",
    "UNKNOWN",
    "BrokerDeviceDiagnosticsStore",
    "normalize_hint",
]
