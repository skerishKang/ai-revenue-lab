"""Oracle Mesh ownership source and deployment configuration."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

from padiem_ai_core.pc_device_identity import is_pc_device_id
from .oracle_mesh_contract import (
    CONNECTOR_WATCH_READ_SECRET_ENV,
    EXECUTION_MODE_OFF,
    ORACLE_MESH_CHANNEL_SECRET_ENV,
    ORACLE_MESH_EXECUTION_MODE_ENV,
    ORACLE_MESH_LEGACY_MAP_LANE_ENV,
    ORACLE_MESH_OWNERSHIP_MAP_ENV,
    RETIRED_OWNERSHIP_MAP,
    _EXECUTION_MODES,
    _SAFE_REF_CHARS,
)
from .oracle_mesh_http import _text_value
from .oracle_mesh_pc_paths import _pc_files_approved_root


def legacy_map_lane_enabled(env: Any) -> bool:
    """``ORACLE_MESH_LEGACY_MAP_LANE=off`` retires the lane; anything else keeps it."""

    from .worker_config import binding_value

    return str(binding_value(env, ORACLE_MESH_LEGACY_MAP_LANE_ENV) or "").strip().lower() != "off"
class UnconfiguredOracleMeshReturnSource:
    """Fail-closed until the Worker root composes the deployment map+secret."""

    configured = False


class OracleMeshReturnSource:
    """Deployment-owned authorization for the Oracle return legs.

    Holds the (account, device, Mesh node, file) ownership map plus the
    channel secret. The map is supplied by the Worker root from deployment
    configuration, never from a request. The broker binding resolve (live,
    account-scoped) still gates every intent; this map only adds the
    Mesh-device ownership the broker never sees.
    """

    configured = True

    def __init__(
        self, mapping: Any, channel_secret: Any, mode: Any = EXECUTION_MODE_OFF,
        watch_secret: Any = None,
    ) -> None:
        if not isinstance(mapping, (list, tuple)) or not mapping:
            raise TypeError("oracle mesh ownership mapping is required")
        rows = []
        for entry in mapping:
            if not isinstance(entry, dict):
                raise TypeError("oracle mesh ownership row must be a mapping")
            row = {
                name: entry.get(name)
                for name in (
                    "account_ref", "device_id", "node_ref", "root_ref",
                    "path_relative", "file_path", "command_exec",
                )
            }
            # #4139 terminal lane: command execution is a SEPARATE deployment
            # grant. A row that authorizes a TXT read never authorizes running a
            # command unless the operator marked it explicitly.
            command_exec = row.pop("command_exec")
            if command_exec is None:
                command_exec = False
            if not isinstance(command_exec, bool):
                raise TypeError("oracle mesh ownership command_exec must be boolean")
            row["command_exec"] = command_exec
            for name, value in row.items():
                if name == "command_exec":
                    continue
                if name in ("path_relative", "file_path"):
                    # A path is not a reference: Korean names are valid input.
                    if _text_value(value) is None:
                        raise TypeError(
                            "oracle mesh ownership " + name + " must be bounded text"
                        )
                    continue
                if value is None:
                    # Only ``device_id`` is an optional pin: when it is absent
                    # the Mesh node itself is the canonical device identity.
                    # ``account_ref`` is mandatory — a row without the verified
                    # PADIEM account never authorizes anybody, and an omitted
                    # account is never treated as permission for all accounts.
                    if name != "device_id":
                        raise TypeError(f"oracle mesh ownership {name} invalid")
                    continue
                if (
                    not isinstance(value, str) or not value
                    or len(value) > 1024
                    or any(ch not in _SAFE_REF_CHARS and ch not in "\\/" for ch in value)
                ):
                    raise TypeError(f"oracle mesh ownership {name} invalid")
            if not row["path_relative"].lower().endswith(".txt"):
                raise TypeError("oracle mesh ownership path_relative must be .txt")
            rows.append(row)
        if (
            not isinstance(channel_secret, str)
            or not 16 <= len(channel_secret) <= 256
            or any(ord(ch) < 33 or ord(ch) > 126 for ch in channel_secret)
        ):
            raise TypeError("oracle mesh channel secret invalid")
        if watch_secret is not None:
            if (
                not isinstance(watch_secret, str)
                or not 16 <= len(watch_secret) <= 256
                or any(ord(ch) < 33 or ord(ch) > 126 for ch in watch_secret)
            ):
                raise TypeError("connector watch read secret invalid")
            if watch_secret == channel_secret:
                raise TypeError(
                    "connector watch read secret must differ from the channel secret"
                )
        self._rows = rows
        self._secret = channel_secret.encode("utf-8")
        self._watch_secret = (
            watch_secret.encode("utf-8") if watch_secret is not None else None
        )
        self._mode = mode if mode in _EXECUTION_MODES else EXECUTION_MODE_OFF

    @property
    def execution_mode(self) -> str:
        """``off`` | ``mesh`` | ``native`` — which lane a TXT request takes."""
        return self._mode

    def classify(self, *, account_ref: str, path_relative: str) -> str:
        """``none`` | ``owned`` | ``foreign`` for one authenticated account.

        ``none``  — the deployment maps no Mesh target for this file at all;
                    the caller keeps the native lane.
        ``owned`` — exactly one row pins this verified account for this file.
                    Only the exact correspondence of verified account and
                    real Mesh node authorizes execution.
        ``foreign`` — the file is mapped, but only to other pinned accounts:
                    a hard ownership refusal, never a fallback.
        """
        rows_for_path = [
            row for row in self._rows if row["path_relative"] == path_relative
        ]
        if not rows_for_path:
            return "none"
        for row in rows_for_path:
            if row["account_ref"] == account_ref:
                return "owned"
        return "foreign"

    def target_for(
        self, *, account_ref: str, path_relative: str,
        device_id: str | None = None,
    ) -> dict[str, Any] | None:
        """The single verified Mesh target for this account's requested file.

        Device and node are always server-derived from the ownership map, so
        an ordinary TXT request never names them. A browser-selected device
        only narrows the choice; it can never introduce one. A row without a
        device pin contributes its Mesh node as the canonical device identity.
        """
        matches = [
            row for row in self._rows
            if row["path_relative"] == path_relative
            and row["account_ref"] == account_ref
            and (device_id is None or row.get("device_id") == device_id or row.get("device_id") is None)
        ]
        return dict(matches[0]) if len(matches) == 1 else None

    def command_target_matches(
        self, *, account_ref: str, device_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Every command-capable row this account and optional pin select.

        command_target collapses this to the single-row verdict, so a
        refusal cannot say whether the grant row was missing or ambiguous.
        The count is exactly that difference, and a diagnostic code needs it.
        """
        return [
            row for row in self._rows
            if row["command_exec"] is True
            and row["account_ref"] == account_ref
            and (
                device_id is None
                or row.get("device_id") == device_id
                or row.get("device_id") is None
                or row["node_ref"] == device_id
            )
        ]

    def command_target(
        self, *, account_ref: str, device_id: str | None = None,
    ) -> dict[str, Any] | None:
        """The single command-capable Mesh target for this verified account.

        #4139 terminal lane. A command has no file, so the row is selected by
        the account (and the optional device pin) alone — and only when the
        operator explicitly marked that row ``command_exec``. A TXT read grant
        is therefore never a command grant, and two competing rows stay a
        refusal rather than an arbitrary pick.
        """
        matches = self.command_target_matches(account_ref=account_ref, device_id=device_id)
        return dict(matches[0]) if len(matches) == 1 else None

    def device_hint_for(
        self, *, account_ref: str, path_relative: str,
        selected_device_id: str | None = None,
    ) -> str:
        """The server-derived device identity for consent lookups.

        The canonical device for an unpinned row is its Mesh node; a pinned
        row keeps its pin. A browser selection never widens this.
        """
        target = self.target_for(
            account_ref=account_ref, path_relative=path_relative,
            device_id=selected_device_id,
        )
        if target is not None:
            return target.get("device_id") or target["node_ref"]
        rows_for_path = [
            row for row in self._rows if row["path_relative"] == path_relative
        ]
        if rows_for_path:
            return rows_for_path[0].get("device_id") or rows_for_path[0]["node_ref"]
        return selected_device_id or ""

    def command_device_ids(self, *, account_ref: str) -> list[str]:
        """Enumerate only this server-verified owner's unambiguous command targets."""
        candidates = {row.get("device_id") or row["node_ref"] for row in self._rows
                      if row["account_ref"] == account_ref and row["command_exec"] is True}
        return sorted(device for device in candidates if is_pc_device_id(device)
                      and self.command_target(account_ref=account_ref, device_id=device) is not None)

    def device_scope(self, *, device_id: str) -> dict[str, Any] | None:
        """Server-derived canonical identity for one reported Mesh device.

        A presence beat names a Mesh node. The canonical PC device id, the
        verified account and the ownership row all come from the deployment
        map — never from the request. An unmapped or ambiguous device yields
        ``None`` so nothing is written.
        """
        if not is_pc_device_id(device_id):
            return None
        matches = [
            row for row in self._rows
            if row.get("device_id") == device_id or row.get("node_ref") == device_id
        ]
        if not matches:
            return None
        accounts = {row["account_ref"] for row in matches}
        canonical = {row.get("device_id") or row["node_ref"] for row in matches}
        if len(accounts) != 1:
            return None
        if len(canonical) != 1 or not is_pc_device_id(next(iter(canonical))):
            return None
        return {
            "device_id": next(iter(canonical)),
            "account_ref": next(iter(accounts)),
        }

    def adopted_roots_for_device(self, *, device_id: Any) -> list[str]:
        """The folders this deployment's map already pins for one device.

        Administrator adoption (#5573 PR-4e) copies them onto the new link so an
        adopted PC can be used at once. An unknown device yields no roots, which
        the route reads as "not in the map" - it never invents a folder, and it
        never hands out another account's pin to somebody the map does not list.
        """
        if not is_pc_device_id(device_id):
            return []
        roots: list[str] = []
        for row in self._rows:
            if row.get("device_id") != device_id and row.get("node_ref") != device_id:
                continue
            root = _pc_files_approved_root(row.get("file_path"))
            if root is not None and root not in roots:
                roots.append(root)
        return roots

    def names_device(self, *, device_id: Any) -> bool:
        return bool(self.adopted_roots_for_device(device_id=device_id)) or any(
            row.get("device_id") == device_id or row.get("node_ref") == device_id
            for row in self._rows
        )

    def mesh_node_ref_for_device(self, *, device_id: Any) -> str | None:
        """The Mesh reference this deployment addresses one device identity by.

        A pairing link names its PC; it does not necessarily say what the Mesh
        client has to run against. A PC's own claim records the node the agent
        reported for itself, while an administrator adopts the identity the
        ownership map pins the device by, and those two are different strings.
        The row that names this device supplies the reference the lane already
        used before any link existed - never a second device's, and never a
        guess when the map names more than one.
        """
        if not is_pc_device_id(device_id):
            return None
        nodes = {
            row.get("node_ref") for row in self._rows
            if row.get("device_id") == device_id or row.get("node_ref") == device_id
        }
        if len(nodes) != 1:
            return None
        node_ref = next(iter(nodes))
        return node_ref if is_pc_device_id(node_ref) else None

    def check_channel_secret(self, presented: Any) -> bool:
        """Constant-time proof check for the Oracle executor channel."""
        if not isinstance(presented, str) or not presented:
            return False
        try:
            candidate = presented.encode("utf-8")
        except (UnicodeEncodeError, ValueError):
            return False
        return hmac.compare_digest(candidate, self._secret)

    def check_watch_secret(self, presented: Any) -> bool:
        """Constant-time check for the read-only watch secret, when one is set."""
        if self._watch_secret is None:
            return False
        if not isinstance(presented, str) or not presented:
            return False
        try:
            candidate = presented.encode("utf-8")
        except (UnicodeEncodeError, ValueError):
            return False
        return hmac.compare_digest(candidate, self._watch_secret)

    def check_read_secret(self, presented: Any) -> bool:
        """Either secret, for the read-only legs only.

        Both comparisons run on every call, so the work done does not depend on which
        secret was presented. No mutating leg calls this: an operator holding the
        watch secret can read the lane's counters and cannot claim, renew, cancel or
        submit anything.
        """
        channel_ok = self.check_channel_secret(presented)
        watch_ok = self.check_watch_secret(presented)
        return bool(channel_ok | watch_ok)

    def cancel_check_token(self, dispatch_id: str) -> str:
        """A per-dispatch capability the PC-side user-mode client carries (#7215).

        The client runs as SYSTEM on the PC and cannot carry the channel secret, so it
        carries this instead: an HMAC of the dispatch id under the channel secret with
        its own domain label, so it can never be replayed as channel-secret proof.
        Possessing it reveals nothing of the secret and authorizes exactly one read —
        whether THIS dispatch is cancelled — and only while the dispatch exists.
        """
        material = b"mesh-cancel-poll:v1:" + str(dispatch_id).encode("utf-8")
        return hmac.new(self._secret, material, hashlib.sha256).hexdigest()

    def cancel_check_token_matches(self, dispatch_id: str, presented: Any) -> bool:
        """Constant-time check of a presented per-dispatch cancel token."""
        if not isinstance(presented, str) or not presented:
            return False
        try:
            candidate = presented.encode("ascii")
        except (UnicodeEncodeError, ValueError):
            return False
        expected = self.cancel_check_token(dispatch_id).encode("ascii")
        return hmac.compare_digest(candidate, expected)


async def _resolve_oracle_store_text(raw: Any) -> Any:
    """Plain strings pass through; Secrets Store bindings resolve via async .get()."""
    if isinstance(raw, str):
        return raw
    getter = getattr(raw, "get", None)
    if not callable(getter):
        return None
    resolved = getter()
    if hasattr(resolved, "__await__"):
        resolved = await resolved
    return resolved


def build_oracle_mesh_return_source(
    mapping: Any, channel_secret: Any = None, mode: Any = EXECUTION_MODE_OFF,
    watch_secret: Any = None,
) -> OracleMeshReturnSource | None:
    """Worker-root composition only; missing/invalid material is unconfigured."""
    try:
        return OracleMeshReturnSource(mapping, channel_secret, mode, watch_secret)
    except Exception:
        return None


def _mesh_source_unconfigured(reason: str) -> None:
    """Record one fixed startup reason, never a secret, mapping or account."""
    logging.getLogger(__name__).warning("oracle_mesh_source_unconfigured=%s", reason)
    return None


async def _resolve_optional_secret(raw: Any) -> Any:
    """Resolve an optional secret binding; absent is None, never an error.

    The watch secret is optional by design: a deployment that has not created one
    keeps the channel-secret-only behaviour for the read-only leg, and the watch
    workflow then reports UNKNOWN instead of authenticating with the channel secret.
    """
    if raw is None or isinstance(raw, str):
        return raw
    getter = getattr(raw, "get", None)
    if not callable(getter):
        return None
    try:
        resolved = getter()
        if hasattr(resolved, "__await__"):
            resolved = await resolved
    except Exception:
        return None
    return resolved if isinstance(resolved, str) else None


async def build_oracle_mesh_return_source_from_env(env: Any) -> OracleMeshReturnSource | None:
    """Read existing deployment bindings, logging only fixed failure classes.

    The product's fail-closed configuration and client-visible behavior do
    not change. No resolved value, account, source URL or exception is logged.
    """
    from .worker_config import binding_value

    try:
        raw_map = await _resolve_oracle_store_text(binding_value(env, ORACLE_MESH_OWNERSHIP_MAP_ENV))
        raw_secret = binding_value(env, ORACLE_MESH_CHANNEL_SECRET_ENV)
        raw_mode = binding_value(env, ORACLE_MESH_EXECUTION_MODE_ENV)
        raw_watch = binding_value(env, CONNECTOR_WATCH_READ_SECRET_ENV)
    except Exception:
        return _mesh_source_unconfigured("binding_read_failed")
    if legacy_map_lane_enabled(env):
        if not isinstance(raw_map, str) or not raw_map.strip():
            return _mesh_source_unconfigured("ownership_map_unavailable")
        try:
            mapping = json.loads(raw_map)
        except (ValueError, TypeError):
            return _mesh_source_unconfigured("ownership_map_malformed")
    else:
        # The retired lane authorizes nobody, so the map is neither read nor required.
        mapping = list(RETIRED_OWNERSHIP_MAP)
    if not isinstance(raw_secret, str):
        getter = getattr(raw_secret, "get", None)
        if not callable(getter):
            return _mesh_source_unconfigured("channel_secret_binding_unavailable")
        try:
            resolved = getter()
            if hasattr(resolved, "__await__"):
                resolved = await resolved
        except Exception:
            return _mesh_source_unconfigured("channel_secret_fetch_failed")
        raw_secret = resolved
    mode = raw_mode.strip().lower() if isinstance(raw_mode, str) else EXECUTION_MODE_OFF
    watch_secret = await _resolve_optional_secret(raw_watch)
    source = build_oracle_mesh_return_source(mapping, raw_secret, mode, watch_secret)
    if source is None:
        return _mesh_source_unconfigured("source_validation_failed")
    return source

def valid_claw_engine_desktop_secret(value: Any) -> str | None:
    """The one rule every Engine desktop gate shares: a 32+ character string.

    The Worker resolves the binding, the CPython host reads a plain env value;
    both hand their result here so the length rule exists exactly once, and a
    value that does not meet it is always the same fail-closed ``None``.
    """
    return value if isinstance(value, str) and len(value) >= 32 else None


def host_engine_lane_mount_marker(env: Any) -> UnconfiguredOracleMeshReturnSource | None:
    """The CPython host's mount-time answer for the Engine lanes.

    ``create_app`` mounts the Engine lanes only when the deployment hands it a
    return source, and the host cannot await the async builder inside uvicorn's
    running factory loop. This marker says "this deployment names the mesh lane,
    compose it at startup": the routes exist, every handler still reads
    ``app.state`` per request, and the startup hook swaps in the composed source
    before the first request is served. A host that does not name the lane gets
    ``None`` and the routes stay unmounted, exactly like the default app.
    """
    from .worker_config import binding_value

    secret = binding_value(env, ORACLE_MESH_CHANNEL_SECRET_ENV)
    if isinstance(secret, str) and secret.strip():
        return UnconfiguredOracleMeshReturnSource()
    return None
