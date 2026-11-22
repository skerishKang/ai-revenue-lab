"""Server-side admission and atomic attempt claims for #8359 maintenance.

No HTTP entry, transport, PC command execution or switch mutation lives here.
The host dispatcher must resolve authority facts, then repeat admission at
the point where it creates a SYSTEM dispatch row.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import hashlib
import hmac
import re
import secrets
from typing import Any

from padiem_ai_core.pc_device_identity import is_pc_device_id

from .d1_rows import rows_from_result
from .pc_helper_auto_update import auto_update_enabled, command_for_plan, stage_allows
from .pc_helper_install import release_pinned
from .pc_helper_registration import SOURCE_SHA256, plan_registration
from .pc_helper_update_policy import version_parts

MAX_ACTIVE = 3
MAX_PRECONTACT_RETRIES = 2
_DIGEST = re.compile(r"[0-9a-f]{64}")
_CLAIM = re.compile(r"reserved:[0-9a-f]{32}")

def verified_mesh_slot(value):
    """Both Mesh node spellings, never an unverified installer GUID or tag."""
    return (is_pc_device_id(value) and not re.fullmatch(
        r"[0-9a-fA-F]{32}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}|pd-[0-9a-f]{8}", value))


@dataclass(frozen=True)
class MaintenanceIntent:
    device_id: str = field(repr=False)
    user_id: str = field(repr=False)
    link_id: str = field(repr=False)
    action: str
    source_sha256: str
    registration_sha256: str
    release_sha256: str
    command: str = field(repr=False)


def admit_maintenance(*, env, device_id, managed_links, admin_now, online,
                      owner_session, owner_consent, observation, manifest, rollout,
                      now: datetime, target_device_id, target_link_id,
                      command=None, source_sha256=None):
    """Return a fixed intent or a bounded denial reason.

    All arguments except the expected command/digest are server-resolved
    authority facts, not request claims. The optional expected bytes/digest
    are for the dispatcher to recheck the previously selected intent.
    """
    if not auto_update_enabled(env):
        return None, "switch_off"
    if not verified_mesh_slot(device_id):
        return None, "device_unverified"
    if not isinstance(managed_links, (tuple, list)) or len(managed_links) != 1:
        return None, "not_managed" if not managed_links else "owner_ambiguous"
    link = managed_links[0]
    if (not isinstance(link, dict) or link.get("mesh_node_id") != device_id
            or link.get("state") != "active" or link.get("paused_at") is not None
            or not link.get("managed_at") or not link.get("managed_by")
            or not isinstance(link.get("user_id"), str) or not link["user_id"]
            or not isinstance(link.get("link_id"), str) or not link["link_id"]):
        return None, "not_managed"
    if admin_now is not True:
        return None, "manager_not_admin"
    if online is not True:
        return None, "offline"
    if owner_session is not True:
        return None, "owner_unresolved"
    if owner_consent is not True:
        return None, "owner_consent_missing"
    if target_device_id != device_id or target_link_id != link["link_id"]:
        return None, "target_mismatch"
    fixed, reason = maintenance_candidate(env=env, device_id=device_id, observation=observation,
                                          manifest=manifest, rollout=rollout, now=now)
    if fixed is None:
        return None, reason
    action, expected = fixed
    digest = hashlib.sha256(expected.encode("utf-8")).hexdigest()
    if command is not None and (not isinstance(command, str)
                               or not hmac.compare_digest(command.encode(), expected.encode())):
        return None, "command_mismatch"
    if source_sha256 is not None and (not isinstance(source_sha256, str)
                                     or not hmac.compare_digest(source_sha256.encode(), digest.encode())):
        return None, "source_mismatch"
    # Refresh shares the existing #8240 reservation key with the human
    # operator. Attempts also pin ALL command bytes, including the watcher.
    registration = SOURCE_SHA256 if action == "refresh" else digest
    return MaintenanceIntent(device_id, link["user_id"], link["link_id"], action,
                             digest, registration, manifest["sha256"], expected), None


def maintenance_candidate(*, env, device_id, observation, manifest, rollout, now):
    """Pure plan/digest for deferred notices; it grants no execution."""
    if not auto_update_enabled(env):
        return None, "switch_off"
    if not verified_mesh_slot(device_id):
        return None, "device_unverified"
    if not release_pinned(manifest):
        return None, "release_unpinned"
    if (not isinstance(rollout, dict) or rollout.get("initialized") is not True
            or rollout.get("stage") not in ("internal", "percentage", "all")):
        return None, "stage_closed"
    # An updater's install GUID is not a verified cohort slot. Only the
    # active link's canonical Mesh node may reach stage selection.
    try:
        target = rollout["target"]
        if (any(target.get(k) != manifest.get(k) for k in
                ("version", "sha256", "download_url", "min_supported_version"))
                or not stage_allows(rollout, device_id=device_id,
                                    helper_sha256=manifest["sha256"])):
            return None, "stage_closed"
    except (KeyError, TypeError, ValueError, AttributeError):
        return None, "stage_closed"
    if not isinstance(observation, dict) or observation.get("device_id") != device_id:
        return None, "observation_unverified"
    plan = plan_registration(observation, system_allowed=True, now=now)
    state = observation.get("state") or {}
    # A missing digest is not evidence that an installed helper is absent.
    # Only the authenticated explicit missing status permits fresh install.
    if plan["action"] == "install" and state.get("helper_status_present") is not False:
        return None, "digest_unverified"
    # A fresh authenticated helper-status file proves installation even when
    # the console cannot observe the updater file/task. Its missing updater
    # evidence is not a mismatch of the pinned command or release manifest.
    # The fixed SYSTEM refresh checks the actual updater hash/task on the PC,
    # verifies the installed EXE against its install record before registering,
    # and refuses on error. Never turn unknown installation into an install.
    # The receipt's independent post-dispatch observation remains mandatory.
    if (plan["action"] == "failed" and plan["reason"] == "digest_unverified"
            and state.get("helper_status_present") is True
            and isinstance(state.get("helper_sha256"), str)
            and _DIGEST.fullmatch(state["helper_sha256"]) is not None
            and version_parts(state.get("helper_version") or observation.get("helper_version")) is not None):
        plan = {"action": "refresh", "reason": "updater_probe_unverified"}
    if plan["action"] == "skipped":
        current = version_parts(state.get("helper_version") or observation.get("helper_version"))
        minimum = version_parts(manifest.get("min_supported_version"))
        if current is not None and minimum is not None and current < minimum:
            plan = {"action": "refresh"}
    fixed = command_for_plan(plan, manifest=manifest, env=env)
    if fixed is None:
        return None, "install_switch_off" if plan["action"] == "install" else plan["reason"]
    return fixed, None


class PrecontactProof(Enum):
    """Only queue-proven states; a timeout or lost response is NOT proof."""
    NO_DISPATCH_ROW = "no_dispatch_row"
    CANCELLED_UNCLAIMED = "cancelled_unclaimed"


@dataclass(frozen=True)
class AttemptClaim:
    device_id: str = field(repr=False)
    source_sha256: str
    token: str = field(repr=False)


class MaintenanceAttemptStore:
    """Use migration 137's single row and atomic SQL, not read/then-write.

    A reserved claim is exclusive and counts against the shared in-flight
    limit until settled. An uncertain outcome stays reserved or terminal,
    never retryable. A stale callback cannot modify a newer reservation.
    """
    def __init__(self, db: Any):
        self._db = db

    async def _rows(self, sql, *args):
        result = await self._db.prepare(sql).bind(*args).run()
        return rows_from_result(result)

    @staticmethod
    def _valid(device_id, source_sha256):
        return (verified_mesh_slot(device_id) and isinstance(source_sha256, str)
                and _DIGEST.fullmatch(source_sha256) is not None)

    async def defer_no_owner(self, *, device_id, source_sha256, now):
        """Insert once for a missing owner; caller alerts only on True."""
        if not self._valid(device_id, source_sha256):
            return False
        rows = await self._rows(
            "INSERT INTO pc_helper_auto_attempts "
            "(device_id,source_sha256,attempts,stopped,last_reason,updated_at) "
            "VALUES (?,?,0,0,'owner_unresolved',?) "
            "ON CONFLICT(device_id,source_sha256) DO NOTHING RETURNING device_id",
            device_id, source_sha256, now)
        return bool(rows)

    async def reserve(self, *, device_id, source_sha256, now):
        if not self._valid(device_id, source_sha256):
            return None
        token = "reserved:" + secrets.token_hex(16)
        # The count and conflict predicate run inside the same SQL statement.
        # Any other historical state (including old phase-1 rows) is closed.
        rows = await self._rows(
            "INSERT INTO pc_helper_auto_attempts "
            "(device_id,source_sha256,attempts,stopped,last_reason,updated_at) "
            "SELECT ?,?,0,0,?,? WHERE (SELECT count(*) FROM pc_helper_auto_attempts "
            "WHERE stopped=0 AND last_reason LIKE 'reserved:%') < ? "
            "AND NOT EXISTS (SELECT 1 FROM pc_helper_auto_attempts WHERE device_id=? "
            "AND stopped=0 AND last_reason LIKE 'reserved:%') "
            "ON CONFLICT(device_id,source_sha256) DO UPDATE SET "
            "last_reason=excluded.last_reason,updated_at=excluded.updated_at "
            "WHERE pc_helper_auto_attempts.stopped=0 "
            "AND pc_helper_auto_attempts.last_reason IN ('owner_unresolved','retryable_precontact') "
            "AND pc_helper_auto_attempts.attempts<=? RETURNING device_id",
            device_id, source_sha256, token, now, MAX_ACTIVE, device_id, MAX_PRECONTACT_RETRIES)
        return AttemptClaim(device_id, source_sha256, token) if rows else None

    async def settle(self, claim, *, now, verified=False, proof=None):
        """Terminal by default; reopen only on explicit non-contact proof.

        A True result is the unique transition owner and may emit one audit
        and (if failure) one operator alert. Retrying the callback emits none.
        """
        if (not isinstance(claim, AttemptClaim)
                or not self._valid(claim.device_id, claim.source_sha256)
                or not _CLAIM.fullmatch(claim.token)
                or (verified is True and proof is not None)):
            return False
        if verified is True:
            reason, failed = "verified", 0
        elif isinstance(proof, PrecontactProof):
            reason, failed = "retryable_precontact", 1
        else:
            reason, failed = "stopped_contact_or_unknown", 1
        rows = await self._rows(
            "UPDATE pc_helper_auto_attempts SET attempts=attempts+?, "
            "stopped=CASE WHEN ?='retryable_precontact' AND attempts<? THEN 0 ELSE 1 END, "
            "last_reason=CASE WHEN ?='retryable_precontact' AND attempts>=? "
            "THEN 'stopped_precontact_limit' ELSE ? END, updated_at=? "
            "WHERE device_id=? AND source_sha256=? AND stopped=0 AND last_reason=? "
            "RETURNING device_id",
            failed, reason, MAX_PRECONTACT_RETRIES, reason, MAX_PRECONTACT_RETRIES,
            reason, now, claim.device_id, claim.source_sha256, claim.token)
        return bool(rows)
