"""#5080 — Android SAF folder declaration over the EXISTING authenticated Broker.

An Android phone is one more device on the canonical Local Agent Broker. It
enrolls, holds a device credential and opens sessions exactly like the Windows
Resident; nothing about account, workspace, binding, credential or command
authority is re-created here.

What Android needs on top of that is one trusted fact the PC lane does not
have: *which SAF document trees the owner selected on this phone*. The phone
reports them after an owner gesture in the system picker, through the same
authenticated device HTTP surface the installed-executable profile already
uses. This module stores that declaration in one small table in the existing
Broker Durable Object SQLite:

```text
phone credential + live session  ->  /android-profile  ->  folders[binding]
```

The server never invents a folder, never accepts a `content://` URI or a
filesystem path, and never treats a declaration as an execution grant:

* the payload carries only an opaque ``root_ref`` and a display name, both
  bounded; owner/account/workspace/device come from the authenticated binding;
* reads revalidate the current canonical binding generation, so a rotated
  credential or a revoked binding cannot keep a stale folder grant alive;
* the declaration is owner-visible through one read-only Service Binding RPC
  used by the existing device directory. It reports ``platform: "android"``
  and the one capability this adapter implements; it never claims ONLINE and
  is not a second device authority.

An empty folder set is a truthful state: the owner withdrew SAF access on the
phone, and the server must refuse to mint a read command for a folder the phone
no longer exposes.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable

from padiem_control_plane.local_agent_broker import BrokerBindingState
from local_agent_broker_sql_state import rows, row_value, safe_ref

ANDROID_PLATFORM = "android"
ANDROID_PROFILE_REF = "profile.android.saf-txt.v1"
ANDROID_PROFILE_DEVICE_ROUTE = "/android-profile"
ANDROID_PROFILE_CONTRACT_VERSION = "claw-local-android-saf-profile.v1"
ANDROID_READ_SUFFIX = ".txt"
ANDROID_CAPABILITIES = ("local.filesystem.read",)
MAX_ANDROID_FOLDERS = 8
MAX_FOLDER_DISPLAY_NAME = 80

_WRITE_KEYS = frozenset({
    "contract_version", "session_id", "profile_ref", "folders",
})
_FOLDER_KEYS = frozenset({"root_ref", "display_name"})
_READ_KEYS = frozenset({
    "account_ref", "workspace_ref", "device_id", "binding_ref", "profile_ref",
})
_PROFILES_KEYS = frozenset({"account_ref", "workspace_ref"})
_ROOT_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,255}$")

_PROFILE_SCHEMA = """
CREATE TABLE IF NOT EXISTS local_agent_android_saf_profile (
 binding_ref TEXT PRIMARY KEY, account_ref TEXT NOT NULL,
 workspace_ref TEXT NOT NULL, device_id TEXT NOT NULL,
 credential_generation INTEGER NOT NULL, profile_ref TEXT NOT NULL,
 supplied_at TEXT NOT NULL
);
"""
_FOLDER_SCHEMA = """
CREATE TABLE IF NOT EXISTS local_agent_android_saf_folder (
 binding_ref TEXT NOT NULL, root_ref TEXT NOT NULL, display_name TEXT NOT NULL,
 PRIMARY KEY (binding_ref, root_ref)
);
"""


class AndroidProfileRefused(ValueError):
    """Caller-safe refusal; carries no path, URI or credential material."""


def valid_saf_root_ref(value: Any) -> str:
    """A bounded opaque handle minted by the phone, never a URI or path."""
    if (
        type(value) is not str
        or not _ROOT_REF.fullmatch(value)
        or value.lower().startswith("content:")
        or "/" in value
        or "\\" in value
        or value in (".", "..")
    ):
        raise AndroidProfileRefused("opaque bounded SAF root reference required")
    return value


def valid_saf_display_name(value: Any) -> str:
    """Presentation-only folder name; never parsed as a path."""
    if (
        type(value) is not str
        or not 1 <= len(value) <= MAX_FOLDER_DISPLAY_NAME
        or value.strip() != value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or "/" in value
        or "\\" in value
    ):
        raise AndroidProfileRefused("bounded SAF display name required")
    return value


def _folders(value: Any) -> list[tuple[str, str]]:
    if type(value) is not list or len(value) > MAX_ANDROID_FOLDERS:
        raise AndroidProfileRefused("bounded SAF folder list required")
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in value:
        if type(item) is not dict or frozenset(item) != _FOLDER_KEYS:
            raise AndroidProfileRefused("closed SAF folder shape required")
        root_ref = valid_saf_root_ref(item["root_ref"])
        if root_ref in seen:
            raise AndroidProfileRefused("duplicate SAF root reference")
        seen.add(root_ref)
        result.append((root_ref, valid_saf_display_name(item["display_name"])))
    return result


class BrokerAndroidSafProfileStore:
    """One owner-selected SAF folder set per canonical device binding."""

    def __init__(self, *, storage: Any, state_port: Any, authority_ref: str,
                 clock: Callable[[], datetime] | None = None) -> None:
        sql = getattr(storage, "sql", None)
        if sql is None or not callable(getattr(sql, "exec", None)):
            raise AndroidProfileRefused("Broker durable SQLite required")
        self._sql = sql
        self._state = state_port
        self._authority = safe_ref(authority_ref, "authority_ref")
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        for statement in (_PROFILE_SCHEMA + _FOLDER_SCHEMA).split(";"):
            if statement.strip():
                self._sql.exec(statement)

    def _now(self) -> datetime:
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise AndroidProfileRefused("trusted timezone-aware clock required")
        return now.astimezone(timezone.utc)

    def _binding(self, *, binding_ref: str, account_ref: str, workspace_ref: str,
                 device_id: str, generation: int):
        snapshot = self._state.load(authority_ref=self._authority).snapshot
        matches = [b for b in snapshot.bindings if
                   b.binding_ref == binding_ref and b.account_ref == account_ref
                   and b.workspace_ref == workspace_ref and b.device_id == device_id]
        if (len(matches) != 1 or matches[0].state is not BrokerBindingState.ACTIVE
                or matches[0].credential_expires_at <= self._now()
                or matches[0].credential_generation != generation):
            raise AndroidProfileRefused("canonical active binding generation required")
        return matches[0]

    def record(self, payload: dict, *, binding: Any, session: dict) -> dict:
        """Replace the folder set; called only after credential AND session auth."""
        if type(payload) is not dict or frozenset(payload) != _WRITE_KEYS:
            raise AndroidProfileRefused("closed Android profile payload required")
        if (payload["contract_version"] != ANDROID_PROFILE_CONTRACT_VERSION
                or payload["profile_ref"] != ANDROID_PROFILE_REF
                or type(session) is not dict or session.get("authenticated") is not True
                or session.get("session_id") != payload["session_id"]):
            raise AndroidProfileRefused("authenticated session profile required")
        for key in ("binding_ref", "device_id", "account_ref", "workspace_ref",
                    "credential_generation"):
            if session.get(key) != getattr(binding, key):
                raise AndroidProfileRefused("session/binding generation mismatch")
        generation = session.get("credential_generation")
        if type(generation) is not int or generation < 1:
            raise AndroidProfileRefused("canonical credential generation required")
        self._binding(binding_ref=binding.binding_ref, account_ref=binding.account_ref,
                      workspace_ref=binding.workspace_ref, device_id=binding.device_id,
                      generation=generation)
        folders = _folders(payload["folders"])
        session_id = safe_ref(session["session_id"], "session_id")
        now = self._now().isoformat()
        # The set is replaced atomically inside the device HTTP transaction:
        # a removed folder must stop being requestable, not linger beside it.
        self._sql.exec(
            "DELETE FROM local_agent_android_saf_folder WHERE binding_ref=?",
            binding.binding_ref,
        )
        for root_ref, display_name in folders:
            self._sql.exec(
                "INSERT INTO local_agent_android_saf_folder "
                "(binding_ref,root_ref,display_name) VALUES (?,?,?)",
                binding.binding_ref, root_ref, display_name,
            )
        self._sql.exec(
            "INSERT INTO local_agent_android_saf_profile "
            "(binding_ref,account_ref,workspace_ref,device_id,credential_generation,"
            "profile_ref,supplied_at) VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(binding_ref) DO UPDATE SET "
            "account_ref=excluded.account_ref,workspace_ref=excluded.workspace_ref,"
            "device_id=excluded.device_id,credential_generation=excluded.credential_generation,"
            "profile_ref=excluded.profile_ref,supplied_at=excluded.supplied_at",
            binding.binding_ref, binding.account_ref, binding.workspace_ref,
            binding.device_id, generation, ANDROID_PROFILE_REF, now,
        )
        return {
            "accepted": True,
            "profile_ref": ANDROID_PROFILE_REF,
            "platform": ANDROID_PLATFORM,
            "folder_count": len(folders),
            "credential_generation": generation,
            "raw_device_credential": False,
            "saf_uri_exposed": False,
        }

    def read(self, payload: dict) -> dict:
        """Private owner-scoped read; the stored row is never an authority."""
        if type(payload) is not dict or frozenset(payload) != _READ_KEYS:
            raise AndroidProfileRefused("closed trusted private profile lookup required")
        scope = {key: safe_ref(payload[key], key) for key in _READ_KEYS}
        if scope["profile_ref"] != ANDROID_PROFILE_REF:
            raise AndroidProfileRefused("unsupported Android execution profile")
        found = rows(self._sql.exec(
            "SELECT binding_ref,account_ref,workspace_ref,device_id,"
            "credential_generation,profile_ref FROM local_agent_android_saf_profile "
            "WHERE binding_ref=?",
            scope["binding_ref"],
        ))
        if len(found) != 1:
            raise AndroidProfileRefused("Android SAF profile not supplied")
        stored = found[0]
        if any(row_value(stored, key) != value for key, value in scope.items()):
            raise AndroidProfileRefused("Android SAF profile owner/binding mismatch")
        generation = row_value(stored, "credential_generation")
        if type(generation) is not int or generation < 1:
            raise AndroidProfileRefused("Android SAF profile generation invalid")
        self._binding(binding_ref=scope["binding_ref"],
                      account_ref=scope["account_ref"],
                      workspace_ref=scope["workspace_ref"],
                      device_id=scope["device_id"], generation=generation)
        folders = rows(self._sql.exec(
            "SELECT root_ref,display_name FROM local_agent_android_saf_folder "
            "WHERE binding_ref=? ORDER BY root_ref",
            scope["binding_ref"],
        ))
        if len(folders) > MAX_ANDROID_FOLDERS:
            raise AndroidProfileRefused("Android SAF folder set exceeds its bound")
        return {
            "ok": True,
            "profile": {
                **scope,
                "platform": ANDROID_PLATFORM,
                "capabilities": list(ANDROID_CAPABILITIES),
                "read_suffix": ANDROID_READ_SUFFIX,
                "folders": [
                    {
                        "root_ref": valid_saf_root_ref(row_value(item, "root_ref")),
                        "display_name": valid_saf_display_name(
                            row_value(item, "display_name")
                        ),
                    }
                    for item in folders
                ],
                "server_verified": True,
            },
        }

    def profiles(self, payload: dict) -> dict:
        """Read-only owner/workspace projection for the device directory.

        Returns presentation metadata only. It deliberately omits folder
        references and never claims ONLINE: the canonical directory facts stay
        the single source of device state, and this answer cannot create,
        recover or grant a binding.
        """
        if type(payload) is not dict or frozenset(payload) != _PROFILES_KEYS:
            raise AndroidProfileRefused("closed Android profile directory request required")
        account_ref = safe_ref(payload["account_ref"], "account_ref")
        workspace_ref = safe_ref(payload["workspace_ref"], "workspace_ref")
        found = rows(self._sql.exec(
            "SELECT profile.binding_ref,profile.device_id,profile.credential_generation,"
            "(SELECT COUNT(*) FROM local_agent_android_saf_folder AS folder "
            " WHERE folder.binding_ref=profile.binding_ref) AS folder_count "
            "FROM local_agent_android_saf_profile AS profile "
            "WHERE profile.account_ref=? AND profile.workspace_ref=? "
            "ORDER BY profile.binding_ref",
            account_ref, workspace_ref,
        ))
        snapshot = self._state.load(authority_ref=self._authority).snapshot
        now = self._now()
        profiles: list[dict[str, Any]] = []
        for item in found:
            binding_ref = safe_ref(row_value(item, "binding_ref"), "binding_ref")
            device_id = safe_ref(row_value(item, "device_id"), "device_id")
            generation = row_value(item, "credential_generation")
            folder_count = row_value(item, "folder_count")
            if (type(generation) is not int or generation < 1
                    or type(folder_count) is not int or not 0 <= folder_count <= MAX_ANDROID_FOLDERS):
                raise AndroidProfileRefused("stored Android profile is invalid")
            active = [
                b for b in snapshot.bindings
                if b.binding_ref == binding_ref and b.account_ref == account_ref
                and b.workspace_ref == workspace_ref and b.device_id == device_id
                and b.credential_generation == generation
            ]
            current = (
                len(active) == 1
                and active[0].state is BrokerBindingState.ACTIVE
                and active[0].credential_expires_at > now
            )
            profiles.append({
                "binding_ref": binding_ref,
                "device_id": device_id,
                "platform": ANDROID_PLATFORM,
                "capabilities": list(ANDROID_CAPABILITIES) if current else [],
                "read_suffix": ANDROID_READ_SUFFIX,
                "folder_count": folder_count,
            })
        return {"ok": True, "platform": ANDROID_PLATFORM, "profiles": profiles}

    def purge_binding(self, binding_ref: str) -> None:
        binding_ref = safe_ref(binding_ref, "binding_ref")
        self._sql.exec(
            "DELETE FROM local_agent_android_saf_folder WHERE binding_ref=?",
            binding_ref,
        )
        self._sql.exec(
            "DELETE FROM local_agent_android_saf_profile WHERE binding_ref=?",
            binding_ref,
        )


def android_saf_profile_rpc(store: BrokerAndroidSafProfileStore | None,
                            payload: dict) -> dict:
    """Private Service Binding read. Never exposed through a public GET."""
    if store is None:
        return {"ok": False, "error": {"code": "android_saf_profile_unavailable"}}
    try:
        return store.read(payload)
    except (AndroidProfileRefused, KeyError, TypeError, ValueError):
        return {"ok": False, "error": {"code": "android_saf_profile_unavailable"}}


def android_saf_profiles_rpc(store: BrokerAndroidSafProfileStore | None,
                             payload: dict) -> dict:
    """Private owner/workspace read used only by the device directory."""
    if store is None:
        return {"ok": False, "error": {"code": "android_saf_profiles_unavailable"}}
    try:
        return store.profiles(payload)
    except (AndroidProfileRefused, KeyError, TypeError, ValueError):
        return {"ok": False, "error": {"code": "android_saf_profiles_unavailable"}}


ANDROID_SAF_PROFILE_DEVICE_ROUTE = ANDROID_PROFILE_DEVICE_ROUTE
ANDROID_SAF_PROFILE_RPC = True
SECOND_DEVICE_AUTH = False
SECOND_BROKER = False
ONLINE_AUTHORITY = False
SAF_URI_STORED = False
EXECUTION_GRANT = False
