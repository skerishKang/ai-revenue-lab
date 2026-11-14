"""The after-admin-check adoption, shared by the route and the ops tool.

The route keeps the platform-admin guard and the HTTP projection. Everything
after that guard - resolve the target account, require an executor receipt,
reuse the drives an existing link already reports, and write the one
``(account, node)`` link - lives here so a server-side operator tool can do the
same adoption without a browser session. The store remains the only writer.
"""
from __future__ import annotations

from datetime import datetime, timezone
import inspect
from typing import Any


class AdoptError(RuntimeError):
    """A bounded adoption refusal the route can project and the CLI can print."""

    def __init__(self, code: str, status: int):
        super().__init__(code)
        self.code = code
        self.status = status


async def adopt_pc_link(
    store: Any,
    presence: Any,
    *,
    target: str | None,
    device_id: str,
    drives: list[str] | None = None,
    caller_user_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Adopt ``device_id`` onto the target account (or the caller's).

    The caller has already passed the platform-admin guard. This function does
    not authenticate; it only performs the bounded adoption and returns the
    stored link. ``drives`` is the already-validated whole-drive list from the
    HTTP body; the executor's own report fills in the rest.
    """
    if not isinstance(device_id, str) or not device_id:
        raise AdoptError("pc_pairing_body_invalid", 400)
    if target is not None and (not isinstance(target, str) or not target.strip()):
        raise AdoptError("pc_pairing_body_invalid", 400)
    account_id = caller_user_id
    if target is not None:
        resolved = await store.resolve_account_ref(target=target)
        if not resolved:
            raise AdoptError("pc_pairing_target_unknown", 404)
        account_id = resolved
    if not account_id:
        raise AdoptError("unauthorized", 401)
    if presence is None or not callable(getattr(presence, "load", None)):
        raise AdoptError("pc_pairing_unavailable", 503)
    try:
        record = presence.load(device_id=device_id)
        if inspect.isawaitable(record):
            record = await record
    except Exception:
        raise AdoptError("pc_pairing_unavailable", 503)
    if not isinstance(record, dict) or not record.get("device_id"):
        raise AdoptError("pc_pairing_device_unseen", 404)
    known = await store.drive_roots_for_node(mesh_node_id=device_id)
    merged = list(drives or [])
    for single in known or []:
        if single not in merged:
            merged.append(single)
    if not merged:
        raise AdoptError("pc_pairing_device_unscoped", 404)
    return await store.adopt_link(
        user_id=account_id,
        mesh_node_id=device_id,
        root_paths=[],
        now=now or datetime.now(timezone.utc),
        drives=merged,
    )