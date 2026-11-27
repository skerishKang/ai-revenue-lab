"""Oracle Mesh presence observations and pairing claims."""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable

from starlette.requests import Request
from padiem_ai_core.pc_device_identity import is_pc_device_id
from .pc_device_pairing_store import PcPairingError
from .oracle_mesh_contract import (
    _MAX_PRESENCE_BODY_BYTES, _PRESENCE_BODY_KEYS,
    _PRESENCE_ENTRY_KEYS, _PRESENCE_ENTRY_OPTIONAL_KEYS,
)


async def _read_presence(request: Request) -> list[dict[str, Any]] | None:
    """The optional presence beat, or ``None`` when absent or malformed.

    Never raises and never refuses the poll: a body that is not this exact
    shape is reported as no evidence, which leaves the poll response and the
    executor contract byte-for-byte unchanged.
    """
    media = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media != "application/json":
        return None
    try:
        declared = request.headers.get("content-length")
        if declared is not None and (
            not declared.isdecimal() or int(declared) > _MAX_PRESENCE_BODY_BYTES
        ):
            logging.getLogger(__name__).warning("oracle_mesh_presence=ignored_body_bound")
            return None
        raw = await request.body()
    except Exception:
        logging.getLogger(__name__).warning("oracle_mesh_presence=ignored_body_read")
        return None
    if not raw or len(raw) > _MAX_PRESENCE_BODY_BYTES:
        return None
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
        logging.getLogger(__name__).warning("oracle_mesh_presence=ignored_json")
        return None
    if type(value) is not dict:
        logging.getLogger(__name__).warning("oracle_mesh_presence=ignored_shape")
        return None
    if not value:
        # The historical executor body (or any empty JSON object) is simply
        # "no beat", not malformed.
        return None
    if set(value) != _PRESENCE_BODY_KEYS:
        logging.getLogger(__name__).warning("oracle_mesh_presence=ignored_shape")
        return None
    entries = value.get("presence")
    if not isinstance(entries, list) or len(entries) < 1:
        # No PADIEM presence count cap (Owner decision 2026-10-28);
        # only an empty beat is ignored.
        logging.getLogger(__name__).warning("oracle_mesh_presence=ignored_entries")
        return None
    parsed: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict) or not _PRESENCE_ENTRY_KEYS.issubset(entry) or (
            set(entry) - _PRESENCE_ENTRY_KEYS - _PRESENCE_ENTRY_OPTIONAL_KEYS
        ):
            logging.getLogger(__name__).warning("oracle_mesh_presence=ignored_entry_shape")
            return None
        device_id = entry.get("device_id")
        connected = entry.get("connected")
        if not is_pc_device_id(device_id) or type(connected) is not bool:
            logging.getLogger(__name__).warning("oracle_mesh_presence=ignored_entry_value")
            return None
        row: dict[str, Any] = {"device_id": device_id, "connected": connected}
        agent_name = entry.get("agent_name")
        if agent_name is not None:
            if (
                not isinstance(agent_name, str)
                or not 1 <= len(agent_name) <= 256
                or any(ord(ch) < 32 or ord(ch) == 127 for ch in agent_name)
            ):
                logging.getLogger(__name__).warning("oracle_mesh_presence=ignored_entry_value")
                return None
            row["agent_name"] = agent_name
        parsed.append(row)
    return parsed


class _PairingRefusalLog:
    """One warning per (node, reason) per hour; the window's repeats counted.

    A paired PC keeps the pairing tag its install stamped into the agent name,
    so an ordinary fleet re-reports a spent tag once per presence beat and the
    refusal line would repeat thousands of times an hour for links that are
    perfectly fine. The first refusal in a window is warned with the refusal
    reason and the node's last six characters; the repeats are only counted,
    and the next window opens by summarizing what was swallowed.
    """

    _WINDOW_SECONDS = 3600

    def __init__(self, now_func: Callable[[], float] | None = None) -> None:
        self._now = time.monotonic if now_func is None else now_func
        self._windows: dict[tuple[str, str], tuple[float, int]] = {}

    def record(self, logger: logging.Logger, node_last6: str, reason: str) -> None:
        key = (node_last6, reason)
        moment = self._now()
        window = self._windows.get(key)
        if window is not None and moment - window[0] < self._WINDOW_SECONDS:
            self._windows[key] = (window[0], window[1] + 1)
            return
        if window is not None and window[1] > 0:
            logger.info(
                "oracle_mesh_pairing_claim=refused_suppressed node=%s count=%d",
                node_last6, window[1],
            )
        logger.warning(
            "oracle_mesh_pairing_claim=refused reason=%s node=%s",
            reason, node_last6,
        )
        self._windows[key] = (moment, 0)


def _refusal_reason(exc: Exception) -> str:
    """The bounded refusal text a log line may carry.

    ``PcPairingError`` messages are fixed refusal phrases by design - the class
    never carries a code, node or path value - so its message is the reason.
    Any other exception type says only its own name: its message could quote
    request material the log must not keep.
    """
    if isinstance(exc, PcPairingError):
        return str(exc) or type(exc).__name__
    return type(exc).__name__


def _pairing_refusal_log(request: Request) -> _PairingRefusalLog:
    tracker = getattr(request.app.state, "pairing_refusal_log", None)
    if not isinstance(tracker, _PairingRefusalLog):
        tracker = _PairingRefusalLog()
        request.app.state.pairing_refusal_log = tracker
    return tracker


async def _record_mesh_presence(
    request: Request, source: "OracleMeshReturnSource", entries: list[dict[str, Any]],
) -> None:
    """UPSERT the server-stamped receipt; every failure is log-only."""
    store = getattr(request.app.state, "mesh_device_presence_store", None)
    if not callable(getattr(store, "upsert", None)):
        return
    resolver = getattr(request.app.state, "mesh_presence_generation_resolver", None)
    pairing = getattr(request.app.state, "pc_device_pairing_store", None)
    received_at = datetime.now(timezone.utc)
    for entry in entries:
        reported = entry["device_id"]
        # A name carrying this deployment's pairing tag is a claim attempt, and
        # it is settled before anything else: an unlinked node is exactly what
        # the directory and map lookups below would refuse, so the claim has to
        # resolve first. Most tagged beats come from PCs that are already
        # paired - the install name keeps its tag after the claim - and the
        # store ends those idempotent repeats quietly; a genuinely failed
        # attempt raises and its refusal lines are summarized by
        # _PairingRefusalLog.
        agent_name = entry.get("agent_name")
        if isinstance(agent_name, str) and callable(
            getattr(pairing, "complete_claim_from_observation", None)
        ):
            try:
                completed = await pairing.complete_claim_from_observation(
                    agent_name=agent_name, mesh_node_id=reported, now=received_at,
                )
            except Exception as exc:
                _pairing_refusal_log(request).record(
                    logging.getLogger(__name__),
                    str(reported)[-6:],
                    _refusal_reason(exc),
                )
            else:
                if completed is not None:
                    from .auth_validation_cache import drop_cached_owner_scope_of

                    drop_cached_owner_scope_of(request, completed.get("user_id"))
                    from .claw_pc_device_selection_store import sync_superseded_device_selections

                    selection_store = getattr(
                        request.app.state, "claw_pc_device_selection_store", None,
                    )
                    try:
                        selection_synced = await sync_superseded_device_selections(
                            selection_store, link=completed, now=received_at,
                        )
                    except Exception as selection_exc:
                        selection_synced = False
                        logging.getLogger(__name__).warning(
                            "oracle_mesh_pairing_selection=failed reason=%s",
                            type(selection_exc).__name__,
                        )
                    logging.getLogger(__name__).info(
                        "oracle_mesh_pairing_claim=completed link_id=%s selection_synced=%s",
                        completed.get("link_id"), selection_synced,
                    )
        # R4: the link directory answers first. A beat naming a PC somebody has
        # paired is recorded under the server's own composed node identity, so
        # the receipt key never depends on what the executor called it. The
        # ownership map still answers for a deployment with no directory to ask,
        # exactly as it did before PR-2.
        directory = None
        if callable(getattr(pairing, "device_scope", None)):
            try:
                directory = await pairing.device_scope(device_id=reported)
            except Exception:
                directory = None
        if directory is not None:
            canonical = directory["device_id"]
            accounts = list(directory["account_refs"])
        else:
            scope = source.device_scope(device_id=reported)
            if scope is None:
                logging.getLogger(__name__).warning("oracle_mesh_presence=device_unmapped")
                continue
            canonical = scope["device_id"]
            accounts = [scope["account_ref"]]
        generation = None
        # One account behind the node resolves a Broker credential generation;
        # a PC shared by several has no single generation to record, and the
        # receipt stays Mesh-only (#5553 requirement 6) rather than borrowing
        # another account's credential state.
        if callable(resolver) and len(accounts) == 1:
            try:
                generation = resolver(
                    account_ref=accounts[0],
                    device_id=canonical,
                )
                if hasattr(generation, "__await__"):
                    generation = await generation
            except Exception:
                generation = None
        if type(generation) is not int or not 1 <= generation <= 1_000_000:
            # Requirement 6: Broker is not a prerequisite for Mesh presence.
            logging.getLogger(__name__).info("oracle_mesh_presence=generation_unresolved")
            generation = None
        try:
            await store.upsert(
                device_id=canonical,
                connected=entry["connected"],
                received_at=received_at,
                credential_generation=generation,
                source="mesh" if generation is None else "broker",
                # #6695 PR-2: the receipt binds the accounts the directory
                # answered with (the map's single ref on a legacy row) at
                # record time, so the row itself is owner-attributed and a
                # later reader never has to trust read-time discipline alone.
                account_refs=accounts,
            )
        except Exception:
            logging.getLogger(__name__).warning("oracle_mesh_presence=store_failed")
