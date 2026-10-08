"""#3782: server-side durable, one-shot browser.control command take.

This is a storage primitive, NOT an approval issuer or an exposed RPC.
An authenticated, P01-verified canonical producer must first register an exact
approved row in the *same* Broker Durable Object transaction. No such producer
or Service Binding is wired yet. In particular, process.execute material and
the #3140 pairing acceptance path cannot register browser.control rows.

Unlike a Desktop-local replay set, a successful CAS survives process restart.
Refusals never release action material; a lost take response is NOT retryable.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from local_agent_broker_sql_state import (
    iso,
    parse_iso,
    row_value,
    rows,
    rows_written,
    safe_ref,
    utc,
)

MAX_APPROVED_BROWSER_COMMAND_BYTES = 12_288
_TAKE_COLUMNS = (
    "command_ref", "session_ref", "binding_ref", "request_id",
    "run_ref", "workspace_ref", "owner_ref", "device_ref",
    "request_fingerprint", "admission_ref", "revision_ref",
)
_SHA256 = frozenset("0123456789abcdef")
_APPROVED_KEYS = frozenset({"commandRef", "hostLeaseRef", "capability", "context", "action"})
_CONTEXT_KEYS = frozenset({
    "requestFingerprint", "browserSessionRef", "deviceRef", "runRef",
    "workspaceRef", "ownerRef", "originScope", "allowedActionClasses",
    "ttlSeconds", "maxActions",
})
_SAFE_DESKTOP_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$")
_ELEMENT_REF = re.compile(r"^el-[0-9]{4}$")
_BARE_ORIGIN = re.compile(r"^https?://[a-z0-9.-]+(?::[0-9]{1,5})?$")
_ACTION_KEYS = {
    "scroll": frozenset({"action", "browserSessionRef", "originRef", "dx", "dy"}),
    "focus": frozenset({"action", "browserSessionRef", "originRef", "elementRef"}),
    "click": frozenset({"action", "browserSessionRef", "originRef", "elementRef"}),
    "type": frozenset({"action", "browserSessionRef", "originRef", "elementRef", "text"}),
    "select": frozenset({"action", "browserSessionRef", "originRef", "elementRef", "optionIndex"}),
}
_LEASE_ELIGIBLE = frozenset(_ACTION_KEYS)


def _safe_desktop_ref(value: Any) -> bool:
    return isinstance(value, str) and bool(_SAFE_DESKTOP_REF.fullmatch(value))


def _valid_action_and_context(context: dict, action: dict, material: dict) -> bool:
    """Minimum canonical browser-control input structure before burning a slot.

    Desktop and KAgent remain the execution and element-role authorities.
    This guard prevents malformed material or widened action objects from
    spending a durable command slot before reaching those validators.
    """
    if not (_safe_desktop_ref(material.get("hostLeaseRef"))
            and all(_safe_desktop_ref(context.get(k)) for k in (
                "browserSessionRef", "deviceRef", "runRef", "workspaceRef", "ownerRef"
            ))):
        return False
    origin = context.get("originScope")
    if not isinstance(origin, str) or len(origin) > 255 or not _BARE_ORIGIN.fullmatch(origin):
        return False
    actions = context.get("allowedActionClasses")
    if (type(actions) is not list or not 1 <= len(actions) <= 5
            or len({a for a in actions if isinstance(a, str)}) != len(actions)
            or any(type(a) is not str or a not in _LEASE_ELIGIBLE for a in actions)):
        return False
    for name, cap in (("ttlSeconds", 900), ("maxActions", 100)):
        value = context.get(name)
        if type(value) is not int or not 1 <= value <= cap:
            return False
    verb = action.get("action")
    if type(verb) is not str or verb not in _ACTION_KEYS:
        return False
    if (frozenset(action) != _ACTION_KEYS[verb]
            or action.get("originRef") != origin
            or action.get("browserSessionRef") != context["browserSessionRef"]):
        return False
    if verb == "scroll":
        if any(type(action[axis]) is not int or abs(action[axis]) > 10_000 for axis in ("dx", "dy")):
            return False
    else:
        if not isinstance(action.get("elementRef"), str) or not _ELEMENT_REF.fullmatch(action["elementRef"]):
            return False
        if verb == "type":
            value = action["text"]
            if (type(value) is not str or not 1 <= len(value) <= 256
                    or any(ord(c) < 32 or ord(c) == 127 for c in value)):
                return False
        if verb == "select" and (type(action["optionIndex"]) is not int
                                 or not 0 <= action["optionIndex"] <= 1023):
            return False
    return len(json.dumps(action, separators=(",", ":"), ensure_ascii=False).encode("utf-8")) <= 2048


_SCHEMA = """
CREATE TABLE IF NOT EXISTS local_agent_browser_control_command_take (
    command_ref TEXT PRIMARY KEY,
    session_ref TEXT NOT NULL,
    binding_ref TEXT NOT NULL,
    request_id TEXT NOT NULL,
    run_ref TEXT NOT NULL,
    workspace_ref TEXT NOT NULL,
    owner_ref TEXT NOT NULL,
    device_ref TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    admission_ref TEXT NOT NULL,
    revision_ref TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    material_text TEXT NOT NULL CHECK (length(material_text) BETWEEN 1 AND 12288),
    taken_at TEXT NULL
)
"""


@dataclass(frozen=True, slots=True)
class BrowserControlCommandTakeCorrelation:
    """Copies of authenticated broker session, command admission and P01 scope."""

    command_ref: str
    session_ref: str
    binding_ref: str
    request_id: str
    run_ref: str
    workspace_ref: str
    owner_ref: str
    device_ref: str
    request_fingerprint: str
    admission_ref: str
    revision_ref: str

    def __post_init__(self) -> None:
        for key in _TAKE_COLUMNS:
            value = getattr(self, key)
            if key == "request_fingerprint":
                if (not isinstance(value, str) or len(value) != 64
                        or any(c not in _SHA256 for c in value)):
                    raise ValueError("browser.control request fingerprint must be lowercase SHA256")
            else:
                safe_ref(value, key)


class CloudflareDurableObjectBrowserControlTakeStore:
    """Closed broker-owned CAS. Has NO registration or external transport method."""

    durable = True

    def __init__(self, storage: Any) -> None:
        sql = getattr(storage, "sql", None)
        transaction = getattr(storage, "transactionSync", None)
        if sql is None or not callable(getattr(sql, "exec", None)) or not callable(transaction):
            raise ValueError("canonical SQLite-backed Broker transactionSync is required")
        self._storage = storage
        self._sql = sql
        self._sql.exec(_SCHEMA)

    def _register_in_existing_transaction(
        self,
        scope: BrowserControlCommandTakeCorrelation,
        material: dict[str, Any],
        *,
        expires_at: datetime,
    ) -> None:
        """Persist already-approved browser work only under the Broker outer txn.

        This is a storage writer, NOT a grant or an exposed registration RPC.
        Caller must have rechecked the live admitted Broker command and a
        separate, authenticated P01 browser.control decision. The product P01
        issuer remains unconnected.
        """
        if not isinstance(scope, BrowserControlCommandTakeCorrelation):
            raise TypeError("typed browser.control registration scope required")
        expiry = iso(utc(expires_at, "browser_control_registration_expiry"))
        if type(material) is not dict:
            raise ValueError("browser.control registration material must be a mapping")
        try:
            material_text = json.dumps(
                material, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False, allow_nan=False,
            )
        except (ValueError, TypeError) as exc:
            raise ValueError("browser.control registration material invalid") from exc
        self._checked_material(material_text, scope)
        # Recompute the canonical #3669 session fingerprint rather than
        # trusting context.requestFingerprint copied from the material.
        # This binds the exact origin, owner, run, device, action classes,
        # TTL and budget to the already-admitted canonical command.
        context = material["context"]
        canonical = {
            "capability": "browser.control",
            "browser_session_ref": context["browserSessionRef"],
            "run_ref": context["runRef"],
            "workspace_ref": context["workspaceRef"],
            "owner_ref": context["ownerRef"],
            "device_id": context["deviceRef"],
            "origin_scope": context["originScope"],
            "allowed_action_classes": context["allowedActionClasses"],
            "ttl_seconds": context["ttlSeconds"],
            "max_actions": context["maxActions"],
        }
        if context["allowedActionClasses"] != sorted(context["allowedActionClasses"]):
            raise ValueError("browser.control session allowed actions are not canonical")
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if hashlib.sha256(encoded).hexdigest() != scope.request_fingerprint:
            raise ValueError("browser.control material session fingerprint mismatch")
        fields = tuple(getattr(scope, field) for field in _TAKE_COLUMNS)
        existing = rows(self._sql.exec(
            "SELECT session_ref,binding_ref,request_id,run_ref,workspace_ref,"
            "owner_ref,device_ref,request_fingerprint,admission_ref,revision_ref,"
            "expires_at,material_text,taken_at "
            "FROM local_agent_browser_control_command_take WHERE command_ref = ?",
            scope.command_ref,
        ))
        if existing:
            # A registration retry must never resurrect taken work, replace
            # pending bytes, adjust authority or prolong an expiry.
            raise ValueError("browser.control registration command already exists")
        written = rows_written(self._sql.exec(
            "INSERT INTO local_agent_browser_control_command_take "
            "(command_ref,session_ref,binding_ref,request_id,run_ref,"
            "workspace_ref,owner_ref,device_ref,request_fingerprint,"
            "admission_ref,revision_ref,expires_at,material_text,taken_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)",
            *fields, expiry, material_text,
        ))
        if written != 1:
            raise ValueError("browser.control approved command was not persisted")

    def purge_command(self, command_ref: str) -> int:
        """Purge terminal browser material/tombstone inside Broker DO txn.

        Only a canonical terminal Broker lifecycle may invoke this method.
        Used-command-id ledger still prohibits old command id reissuance.
        """
        command = safe_ref(command_ref, "command_ref")
        return rows_written(self._sql.exec(
            "DELETE FROM local_agent_browser_control_command_take WHERE command_ref=?",
            command,
        ))

    def purge_binding(self, binding_ref: str) -> int:
        """Destroy pending and taken command material on canonical revoke/rotate.

        Called inside the parent Broker DO transaction; no independent grant
        or new HTTP/Worker method is introduced. An old binding can never
        recover its action material after rotation or revocation.
        """
        binding = safe_ref(binding_ref, "binding_ref")
        return rows_written(self._sql.exec(
            "DELETE FROM local_agent_browser_control_command_take WHERE binding_ref = ?",
            binding,
        ))

    @staticmethod
    def _checked_material(material_text: Any, scope: BrowserControlCommandTakeCorrelation) -> dict:
        if not isinstance(material_text, str):
            raise TypeError("browser.control action material unavailable")
        encoded = material_text.encode("utf-8")
        if not encoded or len(encoded) > MAX_APPROVED_BROWSER_COMMAND_BYTES:
            raise ValueError("browser.control action material exceeds the bound")
        try:
            material = json.loads(material_text)
        except (ValueError, TypeError) as exc:
            raise ValueError("browser.control action material malformed") from exc
        if type(material) is not dict or frozenset(material) != _APPROVED_KEYS:
            raise ValueError("browser.control action material must have the closed five-key shape")
        context = material["context"]
        action = material["action"]
        if (type(context) is not dict or frozenset(context) != _CONTEXT_KEYS
                or type(action) is not dict):
            raise ValueError("browser.control context or action malformed")
        if (
            material["capability"] != "browser.control"
            or material["commandRef"] != scope.command_ref
            or context["requestFingerprint"] != scope.request_fingerprint
            or context["runRef"] != scope.run_ref
            or context["deviceRef"] != scope.device_ref
            or context["workspaceRef"] != scope.workspace_ref
            or context["ownerRef"] != scope.owner_ref
            or action.get("browserSessionRef") != context["browserSessionRef"]
            or action.get("originRef") != context["originScope"]
            or not _valid_action_and_context(context, action, material)
            or action.get("action") not in context["allowedActionClasses"]
        ):
            raise ValueError("browser.control action material does not match approved scope")
        # The Desktop's existing strict validator remains authoritative for
        # individual action parameters and fresh observed element roles.
        return material

    def take(
        self, scope: BrowserControlCommandTakeCorrelation, *, now: datetime
    ) -> dict[str, Any]:
        """Atomically burn a canonical approved command and return its material once.

        The caller MUST already have authenticated this session and checked
        Broker admission, live device binding, and P01. There is no public
        transport or caller-configured proof here; this is storage-only.
        """
        if not isinstance(scope, BrowserControlCommandTakeCorrelation):
            raise TypeError("canonical browser.control take correlation required")
        moment = iso(utc(now, "browser_control_take_now"))

        return self._storage.transactionSync(
            lambda: self._take_in_existing_transaction(scope, moment=moment)
        )

    def _inspect_approved_material(
        self, scope: BrowserControlCommandTakeCorrelation, *, moment: str
    ) -> tuple[dict[str, Any], str]:
        """Read-only scoped snapshot: never an external product interface."""
        if not isinstance(scope, BrowserControlCommandTakeCorrelation):
            raise TypeError("canonical browser.control take correlation required")
        parsed_moment = iso(parse_iso(moment, "browser_control_take_now"))
        found = rows(self._sql.exec(
            "SELECT session_ref,binding_ref,request_id,run_ref,workspace_ref,"
            "owner_ref,device_ref,request_fingerprint,admission_ref,revision_ref,"
            "expires_at,material_text,taken_at "
            "FROM local_agent_browser_control_command_take WHERE command_ref = ?",
            scope.command_ref,
        ))
        if len(found) != 1:
            raise ValueError("browser.control approved command unavailable")
        record = found[0]
        if row_value(record, "taken_at") is not None:
            raise ValueError("browser.control approved command already taken")
        if any(row_value(record, key) != getattr(scope, key) for key in _TAKE_COLUMNS if key != "command_ref"):
            raise ValueError("browser.control approved command correlation mismatch")
        expiry = row_value(record, "expires_at")
        if parsed_moment >= iso(parse_iso(expiry, "command_expiry")):
            raise ValueError("browser.control approved command expired")
        return self._checked_material(row_value(record, "material_text"), scope), expiry

    def _read_approved_material(
        self, scope: BrowserControlCommandTakeCorrelation, *, moment: str
    ) -> dict[str, Any]:
        """Broker-only P01 preflight. No take, no lock, no grant."""
        material, _ = self._inspect_approved_material(scope, moment=moment)
        return material

    def _take_in_existing_transaction(
        self, scope: BrowserControlCommandTakeCorrelation, *, moment: str
    ) -> dict[str, Any]:
        """Broker-owned atomic single-use CAS, after live P01 revalidation."""
        material, expiry = self._inspect_approved_material(scope, moment=moment)
        parsed_moment = iso(parse_iso(moment, "browser_control_take_now"))
        # The action (especially browser.type text) must not remain at rest
        # after an authorized one-shot take. Preserve a durable non-replayable
        # tombstone, but scrub the raw material IN THE SAME atomic CAS.
        # Schema intentionally requires a nonempty material_text, so use a
        # closed, non-executable marker and reject it on every future take.
        updated = rows_written(self._sql.exec(
            "UPDATE local_agent_browser_control_command_take "
            "SET taken_at = ?, material_text = ? "
            "WHERE command_ref = ? AND taken_at IS NULL AND expires_at = ?",
            parsed_moment, '{"consumed":true}', scope.command_ref, expiry,
        ))
        if updated != 1:
            raise ValueError("browser.control command already consumed or expired")
        return material


# No registration API, Service Binding, HTTP endpoint, resident command
# dispatch or renderer IPC. A real authenticated product issuer is still required.
BROKER_BROWSER_CONTROL_TAKE_SOURCE_WIRED = False
BROWSER_CONTROL_APPROVAL_ISSUER_WIRED = False
