"""#8359 Chat-host-only maintenance polling; no route or queue write authority.

The queue is read through its existing authenticated proxy. Only Chat stages
the owner's run and calls the existing Mesh command dispatcher. A lost write
response is terminal, not evidence that the PC was never contacted.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone

from starlette.requests import Request

from .d1_rows import rows_from_result
from .lifespan_hooks import lifespan_hooks
from .pc_helper_maintenance import (
    AttemptClaim, MaintenanceAttemptStore, PrecontactProof, admit_maintenance, maintenance_candidate,
)
from .pc_helper_auto_update import auto_update_enabled
from .pc_helper_registration import MAX_AGE, SOURCE_SHA256, parse_receipt
from .pc_helper_install import parse_install_receipt
from .pc_helper_rollout import load_plan
from .pc_helper_version_routes import helper_manifest
from .pc_device_pairing_routes import _presence_view
from .platform_admin_authority import platform_authority_for
from .connector_account_subject import maintenance_owner_context
from .connector_account_shadow import mode_connector_read

_CLOSED_CODE = re.compile(r"[a-z0-9_]{1,64}")
logger = logging.getLogger(__name__)
INTERVAL = 60
TTL = 300
VERIFY_SECONDS = 600
ACTOR = "system:pc_maintenance"


def _now():
    return datetime.now(timezone.utc)


def _stamp(now):
    return now.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _time(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return None


def _key(*parts):
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


class HostMaintenanceStore(MaintenanceAttemptStore):
    """The 137 attempt lock plus a Chat-local per-claim receipt journal."""

    async def rows(self, sql, *args):
        raw = await self._db.prepare(sql).bind(*args).run()
        return [dict(r.to_py() if callable(getattr(r, "to_py", None)) else r)
                for r in rows_from_result(raw)]

    async def begin(self, claim, intent, now):
        await self.rows(
            "INSERT INTO pc_helper_maintenance_jobs "
            "(claim_token,device_id,source_sha256,registration_sha256,release_sha256,"
            "owner_id,action,created_at,deadline,status) VALUES (?,?,?,?,?,?,?,?,?,'reserved')",
            claim.token, intent.device_id, intent.source_sha256, intent.registration_sha256,
            intent.release_sha256, intent.user_id, intent.action, _stamp(now),
            _stamp(now + timedelta(seconds=VERIFY_SECONDS)))

    async def pin_run(self, claim, run):
        rows = await self.rows(
            "UPDATE pc_helper_maintenance_jobs SET run_id=? WHERE claim_token=? "
            "AND status='reserved' AND run_id IS NULL RETURNING claim_token", run, claim.token)
        if not rows:
            raise ValueError("maintenance claim lost")

    async def pin_dispatch(self, claim, dispatch):
        rows = await self.rows(
            "UPDATE pc_helper_maintenance_jobs SET dispatch_id=?,status='queued' WHERE claim_token=? "
            "AND status='reserved' AND run_id IS NOT NULL RETURNING claim_token",
            dispatch, claim.token)
        if not rows:
            raise ValueError("maintenance claim lost")

    async def finish(self, claim, result, *, now, proof=None):
        # Write the durable terminal notice first. Replay can finish the 137
        # CAS or deliver a deduplicated notification after a host crash.
        rows = await self.rows(
            "UPDATE pc_helper_maintenance_jobs SET status='terminal',outcome=?,proof=? "
            "WHERE claim_token=? AND status IN ('reserved','queued') RETURNING claim_token",
            result, proof.value if isinstance(proof, PrecontactProof) else None, claim.token)
        if rows:
            await self.settle(claim, now=_stamp(now), verified=result == "verified", proof=proof)

    async def active(self):
        return await self.rows(
            "SELECT * FROM pc_helper_maintenance_jobs WHERE status!='terminal' OR notified=0 "
            "ORDER BY created_at LIMIT 100")

    async def mark_notified(self, token):
        await self.rows("UPDATE pc_helper_maintenance_jobs SET notified=1 WHERE claim_token=?",
                        token)

    async def mark_receipt(self, token, now):
        await self.rows(
            "UPDATE pc_helper_maintenance_jobs SET receipt_at=? WHERE claim_token=? "
            "AND receipt_at IS NULL AND status='queued'", _stamp(now), token)

    async def deferred(self, device, digest):
        return bool(await self.rows(
            "SELECT device_id FROM pc_helper_auto_attempts WHERE device_id=? "
            "AND source_sha256=? AND last_reason='owner_unresolved' AND stopped=0",
            device, digest))

    async def orphan_claims(self, state, now):
        # A crash between the atomic reservation and journal insert cannot be
        # presumed to have reached a PC. Stop it rather than reclaim blindly.
        rows = await self.rows(
            "SELECT a.device_id,a.source_sha256,a.last_reason FROM pc_helper_auto_attempts a "
            "LEFT JOIN pc_helper_maintenance_jobs j ON j.claim_token=a.last_reason "
            "WHERE a.stopped=0 AND a.last_reason LIKE 'reserved:%' AND j.claim_token IS NULL "
            "AND a.updated_at<?", _stamp(now - timedelta(seconds=VERIFY_SECONDS)))
        for row in rows:
            if await _notice(state, row["device_id"], row["last_reason"], "reservation_uncertain"):
                await self.settle(AttemptClaim(row["device_id"], row["source_sha256"],
                                               row["last_reason"]), now=_stamp(now))


async def _notice(state, device, token, outcome, *, failure=True):
    """Idempotent audit and existing #8105 outbox. No raw PC/user id or output."""
    target = device[-6:] if len(device) > 6 else _key(device)[-6:]
    identity = _key(token, outcome)
    audit = await state.ops_audit_store.append(
        actor_user_id=ACTOR, action="helper_auto_" + outcome,
        target_type="pc_maintenance", target_id=target,
        detail={"outcome": outcome}, dedupe_key=identity)
    if not audit:
        return False
    if failure:
        alert = await state.ops_alert_store.enqueue_event({
            "site": "pc", "kind": "pc_maintenance", "audience": "real",
            "title": "PC " + target + ": " + outcome, "source_id": identity,
        })
        if alert:
            from .ops_alert_delivery import schedule_event_delivery
            schedule_event_delivery(state, alert_id=alert)
    return True


def _diagnostic():
    # Only bounded labels, no device/account/session IDs, hashes or exception
    # text. The ordinal is local to the round, not a durable identifier.
    return dict.fromkeys(("managed", "owner_link", "manager_admin", "online",
                          "observation", "helper_status", "helper_digest",
                          "updater_source", "updater_digest", "updater_task", "watcher_task", "rollout",
                          "maintenance_candidate", "owner_session", "outcome"),
                         "not_checked")


def _known_flag(value):
    return "yes" if value is True else "no" if value is False else "unknown"


def _observation_diagnostic(report, observation, device, now):
    if not isinstance(observation, dict):
        report["observation"] = "missing"
        return
    if observation.get("device_id") != device:
        report["observation"] = "mismatch"
        return
    seen = _time(observation.get("received_at"))
    report["observation"] = (
        "fresh" if seen is not None and seen.tzinfo is not None
        and timedelta(0) <= now - seen <= MAX_AGE else "stale_or_invalid")
    state = observation.get("state")
    if not isinstance(state, dict):
        return
    report["helper_status"] = _known_flag(state.get("helper_status_present"))
    report["helper_digest"] = "present" if state.get("helper_sha256") else "missing"
    report["updater_source"] = _known_flag(state.get("updater_source_present"))
    digest = state.get("updater_source_sha256")
    report["updater_digest"] = (
        "matches" if digest == SOURCE_SHA256 else "different" if digest else "missing")
    report["updater_task"] = _known_flag(state.get("updater_task_present"))
    report["watcher_task"] = _known_flag(state.get("self_heal_task_present"))


async def _facts(request, device, now, report=None):
    """Only the queue's verified slot and owner link may name the target."""
    state = request.app.state
    pairing = state.pc_device_pairing_store
    report = report if report is not None else _diagnostic()
    report["outcome"] = "resolve_device"
    resolved = await pairing.resolve_helper_rollout_device(device_id=device, install_id=False)
    if not isinstance(resolved, dict) or resolved.get("managed") is not True:
        report.update(managed="no_or_unverified", outcome="not_managed")
        return None
    if resolved.get("device_id") != device:
        report.update(managed="unverified", outcome="device_mismatch")
        return None
    report.update(managed="yes", outcome="load_owner_link")
    links = await pairing.managed_owner_for_device(device_id=device)
    if not isinstance(links, list) or len(links) != 1:
        report.update(owner_link="ambiguous" if isinstance(links, list) and len(links) > 1
                      else "missing_or_invalid", outcome="owner_link_denied")
        if isinstance(links, list) and len(links) > 1:
            await _notice(state, device, _key(device, "ambiguous"), "owner_ambiguous", failure=False)
        return None
    link = links[0]
    if not isinstance(link, dict) or not link.get("user_id") or not link.get("managed_by"):
        report.update(owner_link="invalid", outcome="owner_link_denied")
        return None
    report.update(owner_link="single", outcome="check_manager_admin")
    admin = await platform_authority_for(request).is_global_model_admin(user_id=link["managed_by"])
    report.update(manager_admin=_known_flag(admin), outcome="check_online")
    online = (await _presence_view(state.mesh_device_presence_store, device_id=device, now=now))["online"]
    report.update(online=_known_flag(online), outcome="load_observation")
    observation = await state.mesh_device_drive_store.load_helper_ready(device_id=device, include_versions=True)
    _observation_diagnostic(report, observation, device, now)
    report["outcome"] = "load_manifest"
    manifest = helper_manifest(state)
    if not manifest:
        report["outcome"] = "release_unavailable"
        return None
    report["outcome"] = "load_rollout"
    rollout = await load_plan(state, manifest)
    stage = rollout.get("stage") if isinstance(rollout, dict) else None
    report["rollout"] = (
        stage if isinstance(rollout, dict) and rollout.get("initialized") is True
        and stage in ("internal", "percentage", "all", "paused") else "uninitialized_or_invalid")
    return dict(device_id=device, managed_links=links, admin_now=admin, online=online,
                observation=observation, manifest=manifest, rollout=rollout,
                now=now)


async def _admission(request, env, device, now, report=None):
    """Context manager caller must already have the fresh owner proof."""
    from .oracle_mesh_read_return_routes import _engine_pc_files_target
    state = request.app.state
    facts = await _facts(request, device, now, report)
    if facts is None:
        return None, None, None
    uid = facts["managed_links"][0]["user_id"]
    return facts, uid, _engine_pc_files_target


async def _authorized(request, env, facts, session, uid, resolver):
    state = request.app.state
    device = facts["device_id"]
    identity = state.control_plane_identity_authority
    stage = None
    scope = await mode_connector_read(identity, "owner_scope", session_id=session.session_id)
    # The consent directory is keyed by the connector's own enrollment device
    # id, not by the Mesh node this link names. The deployment ownership map
    # is the server-owned pair of both strings, so its pinned device for this
    # node is the exact value a human consent screen names. Use it unchanged:
    # never reshape the Mesh string into a key and never loosen the consent
    # server's own reference check.
    source = getattr(state, "oracle_mesh_return_source", None)
    consent_of = getattr(source, "consent_device_for_node", None)
    scope_ready = (
        isinstance(scope, dict) and bool(scope.get("account_ref"))
        and bool(scope.get("workspace_ref"))
    )
    consent_ref = (
        consent_of(account_ref=scope["account_ref"], node_ref=device)
        if scope_ready and callable(consent_of) else None
    )
    if not isinstance(consent_ref, str) or not consent_ref:
        logger.warning("pc_maintenance_owner_authority outcome=denied stage=%s",
                       "consent_reference_missing" if scope_ready else "scope_missing")
        return None, None, "owner_consent_missing"
    try:
        consent = await mode_connector_read(identity, "consent", session_id=session.session_id, device_id=consent_ref)
    except Exception as exc:
        consent = None
        stage = "consent_read_error"
        # Closed identity codes only (fixed strings such as
        # connector_consent_not_found), never a value or message text.
        code = getattr(exc, "code", None)
        status = getattr(exc, "status_code", getattr(exc, "status", None))
        logger.warning("pc_maintenance_consent_read outcome=error kind=%s status=%s code=%s",
                       type(exc).__name__, status if isinstance(status, int) else "-",
                       code if isinstance(code, str) and _CLOSED_CODE.fullmatch(code) else "-")
    subject = session.subject.subject_id
    if stage is None:
        if not isinstance(scope, dict) or not scope.get("account_ref") or not scope.get("workspace_ref"):
            stage = "scope_missing"
        elif scope.get("owner_subject_id") != subject:
            stage = "scope_subject"
        elif not isinstance(consent, dict):
            stage = "consent_missing"
        elif consent.get("owner_subject_id") != subject:
            stage = "consent_subject"
        elif consent.get("device_id") != consent_ref:
            stage = "consent_device"
        elif consent.get("withdrawn_at") is not None:
            stage = "consent_withdrawn"
        elif not consent.get("consent_id"):
            stage = "consent_id"
        elif consent.get("account_ref") != scope.get("account_ref"):
            stage = "account_ref_mismatch"
        elif consent.get("workspace_ref") != scope.get("workspace_ref"):
            stage = "workspace_ref_mismatch"
    if stage is not None:
        logger.warning("pc_maintenance_owner_authority outcome=denied stage=%s", stage)
        return None, None, "owner_consent_missing"
    resolved, refusal = await resolver(request, session=session, selected_device_id=device, user_id=uid)
    target = resolved.get("target") if isinstance(resolved, dict) and resolved.get("authorized") is True else None
    if (refusal is not None or not isinstance(target, dict) or target.get("node_ref") != device
            or resolved.get("account_ref") != scope["account_ref"]
            or resolved.get("workspace_ref") != scope["workspace_ref"]):
        return None, None, "target_mismatch"
    intent, reason = admit_maintenance(
        env=env, **facts, owner_session=True, owner_consent=True,
        target_device_id=target.get("device_id"), target_link_id=target.get("link_id"))
    return intent, target, reason


def _candidate_digest(facts, env, report):
    fixed, reason = maintenance_candidate(env=env, **{
        k: facts[k] for k in ("device_id", "observation", "manifest", "rollout", "now")})
    report["maintenance_candidate"] = fixed[0] if fixed else reason
    return hashlib.sha256(fixed[1].encode()).hexdigest() if fixed else None


async def _defer(state, store, device, digest, now, reason):
    await store.defer_no_owner(device_id=device, source_sha256=digest, now=_stamp(now))
    if await store.deferred(device, digest):
        await _notice(state, device, _key(device, digest), reason)


async def consider_device(app, env, store, device, *, now=None, report=None):
    """One candidate, never a client-supplied device or command."""
    request = Request({"type": "http", "app": app, "headers": []})
    state = app.state
    now = now or _now()
    report = report if report is not None else _diagnostic()
    if not auto_update_enabled(env):
        report["outcome"] = "switch_off"
        return
    facts, uid, resolver = await _admission(request, env, device, now, report)
    if not facts:
        return
    if facts["admin_now"] is not True or facts["online"] is not True:
        report["outcome"] = "manager_not_admin" if facts["admin_now"] is not True else "offline"
        return
    report["outcome"] = "check_candidate"
    digest = _candidate_digest(facts, env, report)
    if digest is None:
        report["outcome"] = "candidate_denied"
        return
    try:
        report["outcome"] = "resolve_owner_session"
        async with maintenance_owner_context(app, uid) as session:
            report.update(owner_session="yes", outcome="check_owner_authority")
            intent, target, reason = await _authorized(request, env, facts, session, uid, resolver)
            if intent is None:
                report["outcome"] = reason
                if digest and reason == "owner_consent_missing":
                    await _defer(state, store, device, digest, now, reason)
                return
            report["outcome"] = "reserve_attempt"
            claim = await store.reserve(device_id=device, source_sha256=intent.source_sha256, now=_stamp(now))
            if claim is None:
                report["outcome"] = "reservation_denied"
                return
            report["outcome"] = "begin_job"
            await store.begin(claim, intent, now)
            report["outcome"] = "dispatch_attempted"
            await _dispatch(request, env, store, claim, intent, target, session, resolver, now)
    except ValueError as exc:
        if str(exc) == "maintenance_owner_unresolved" and digest:
            report.update(owner_session="no", outcome="owner_unresolved")
            await _defer(state, store, device, digest, now, "owner_unresolved")
        else:
            raise


async def _dispatch(request, env, store, claim, intent, target, session, resolver, now):
    from .chat_pc_drive import _new_lane_run_id
    from .oracle_mesh_read_return_routes import dispatch_oracle_mesh_command_intent
    state = request.app.state
    registration = dict(device_id=intent.device_id, sha256=intent.registration_sha256,
                        attempt_id=_key(intent.device_id, intent.source_sha256))
    write_started = False
    try:
        if not await state.mesh_device_drive_store.reserve_updater_registration(
                **registration, actor=intent.user_id, now=now):
            await store.finish(claim, "already_reserved", now=now)
            return
        reserved = await state.mesh_device_drive_store.load_updater_registration(
            device_id=intent.device_id, sha256=intent.registration_sha256)
        if (not isinstance(reserved, dict) or reserved.get("actor_user_id") != intent.user_id
                or reserved.get("attempt_id") != registration["attempt_id"]
                or reserved.get("dispatch_id") is not None or reserved.get("reason") is not None):
            await store.finish(claim, "already_reserved", now=now)
            return
        if not await _notice(state, intent.device_id, claim.token, "selected", failure=False):
            raise ValueError("maintenance audit unavailable")

        async def recheck():
            nonlocal write_started
            fresh = await _facts(request, intent.device_id, _now())
            if fresh is None or fresh["managed_links"][0]["user_id"] != intent.user_id:
                return False
            async with maintenance_owner_context(request.app, intent.user_id) as current:
                if (current.session_id != session.session_id or current.tenant_id != session.tenant_id
                        or current.subject.subject_id != session.subject.subject_id):
                    return False
                again, exact_target, _reason = await _authorized(
                    request, env, fresh, current, intent.user_id, resolver)
                return again == intent and exact_target == target

        if not await recheck():
            raise ValueError("maintenance authority changed")
        run = _new_lane_run_id()
        history = state.history_store
        conversation = await history.ensure_claw_automation_conversation(
            user_id=intent.user_id, rule_id="pc_maintenance_" + _key(intent.user_id),
            rule_name="PC 자동 유지보수")
        await history.record_chat_pc_drive_run(
            user_id=intent.user_id, run_id=run, workspace_id=session.tenant_id,
            user_text="PC 자동 유지보수: " + intent.action, conversation_id=conversation,
            action="pc_maintenance", title_prefix="PC 자동 유지보수: ")
        await store.pin_run(claim, run)

        async def before_write():
            nonlocal write_started
            if not await recheck():
                return False
            write_started = True  # no await between this proof and row creation
            return True

        result = await dispatch_oracle_mesh_command_intent(
            request, command=intent.command, wire={"run_id": run, "device_id": intent.device_id,
                                                  "confirmed": True},
            trusted_owner=(session, intent.user_id, session.tenant_id), files_target=target,
            user_mode=False, ttl_seconds=TTL, maintenance_before_write=before_write)
        if result.status_code != 200:
            raise ValueError("maintenance dispatch refused")
        dispatch = json.loads(result.body)["dispatch"]
        if (not write_started or dispatch.get("device_id") != intent.device_id
                or dispatch.get("run_id") != run or dispatch.get("user_mode") is not False
                or dispatch.get("kind") != "command" or not isinstance(dispatch.get("dispatch_id"), str)):
            raise ValueError("maintenance dispatch mismatch")
        await store.pin_dispatch(claim, dispatch["dispatch_id"])
        try:
            await state.mesh_device_drive_store.record_updater_registration(
                **registration, dispatch_id=dispatch["dispatch_id"])
            await _notice(state, intent.device_id, claim.token, "dispatched", failure=False)
        except Exception:
            logger.warning("pc_maintenance_registration_projection_failed")
    except Exception:
        proof = None if write_started else PrecontactProof.NO_DISPATCH_ROW
        await store.finish(claim, "dispatch_unconfirmed" if write_started else "precontact_refused",
                           now=_now(), proof=proof)


async def reconcile(app, store, now):
    from .mcp_gateway_shell import _read_original
    state = app.state
    request = Request({"type": "http", "app": app, "headers": []})
    await store.orphan_claims(state, now)
    for job in await store.active():
        claim = AttemptClaim(job["device_id"], job["source_sha256"], job["claim_token"])
        try:
            if job["status"] == "terminal":
                proof = PrecontactProof(job["proof"]) if job["proof"] else None
                await store.settle(claim, now=_stamp(now), verified=job["outcome"] == "verified", proof=proof)
                # Preserve the shared manual reservation for a proven retry;
                # it must never reopen an uncertain/completed manual command.
                rows = await store.rows(
                    "SELECT stopped FROM pc_helper_auto_attempts WHERE device_id=? AND source_sha256=?",
                    job["device_id"], job["source_sha256"])
                if (rows and rows[0]["stopped"] and not job["dispatch_id"]
                        and job["outcome"] != "already_reserved"):
                    await state.mesh_device_drive_store.record_updater_registration(
                        device_id=job["device_id"], sha256=job["registration_sha256"],
                        attempt_id=_key(job["device_id"], job["source_sha256"]), reason=job["outcome"])
                if await _notice(state, job["device_id"], claim.token, job["outcome"],
                                 failure=job["outcome"] != "verified"):
                    await store.mark_notified(claim.token)
                continue
            deadline = _time(job["deadline"])
            if deadline is None or now >= deadline:
                await store.finish(claim, "receipt_timeout", now=now)
                continue
            if job["status"] != "queued":
                # Crash during dispatch: wait, then stop as uncertain. Never
                # infer absence of a row or retry from a local timeout.
                continue
            await state.mesh_device_drive_store.record_updater_registration(
                device_id=job["device_id"], sha256=job["registration_sha256"],
                attempt_id=_key(job["device_id"], job["source_sha256"]), dispatch_id=job["dispatch_id"])
            await _notice(state, job["device_id"], claim.token, "dispatched", failure=False)
            dispatched = await state.history_store.get_oracle_mesh_dispatch_for_owner(
                user_id=job["owner_id"], dispatch_id=job["dispatch_id"])
            if not isinstance(dispatched, dict) or dispatched.get("run_id") != job["run_id"]:
                continue
            if dispatched.get("state") in ("pending", "received"):
                continue
            if dispatched.get("state") != "done" or dispatched.get("exit_code") != 0:
                await store.finish(claim, "dispatch_failed", now=now)
                continue
            run = await state.history_store.get_claw_run(job["owner_id"], job["run_id"])
            original = await _read_original(request, uid=job["owner_id"], dispatch=dispatched, run_row=run)
            if original is None:
                continue
            receipt = (parse_install_receipt if job["action"] == "install" else parse_receipt)(original)
            if receipt["action"] not in ("installed", "updated", "skipped"):
                await store.finish(claim, receipt["reason"], now=now)
                continue
            if job["receipt_at"] is None:
                await store.mark_receipt(claim.token, now)
                continue
            observation = await state.mesh_device_drive_store.load_helper_ready(
                device_id=job["device_id"], include_versions=True)
            if not isinstance(observation, dict) or observation.get("device_id") != job["device_id"]:
                continue
            seen = _time(observation.get("received_at"))
            when = _time(job["receipt_at"])
            observed = observation.get("state") or {}
            if (seen is not None and when is not None and when < seen <= now
                    and (now-seen).total_seconds() <= 180
                    and observed.get("helper_status_present") is True
                    and observed.get("updater_source_sha256") == SOURCE_SHA256
                    and observed.get("updater_task_present") is True
                    and observed.get("self_heal_task_present") is True
                    and (job["action"] != "install" or observed.get("helper_sha256") == job["release_sha256"])):
                await store.finish(claim, "verified", now=now)
        except Exception:
            logger.warning("pc_maintenance_reconcile_failed")


async def maintenance_round(app, env, store):
    if not auto_update_enabled(env):
        return
    now = _now()
    stamp = _stamp(now)
    logger.warning("pc_maintenance_round started=%s", stamp)
    await reconcile(app, store, now)
    pairing = app.state.pc_device_pairing_store
    managed = await pairing.list_managed_device_ids()
    if not isinstance(managed, list):
        logger.warning("pc_maintenance_inventory_invalid round=%s kind=managed", stamp)
        return
    managed = {device for device in managed if isinstance(device, str) and device}
    try:
        active = await pairing.list_active_device_ids()
        if not isinstance(active, list):
            raise ValueError("invalid inventory")
    except Exception:
        logger.warning("pc_maintenance_inventory_invalid round=%s kind=active", stamp)
        active = []
    devices = managed | {device for device in active if isinstance(device, str) and device}
    logger.warning("pc_maintenance_inventory round=%s total=%d managed=%d",
                   stamp, len(devices), len(managed))
    for slot, device in enumerate(sorted(devices), 1):
        report = _diagnostic()
        try:
            if device not in managed:
                report.update(managed="no", outcome="not_managed")
            else:
                report["managed"] = "listed"
                await consider_device(app, env, store, device, report=report)
        except Exception:
            report["outcome"] = "error_" + report["outcome"]
        finally:
            # The service journal is visible even with the default WARNING
            # level. Never log the device itself or the exception payload.
            logger.warning("pc_maintenance_candidate round=%s slot=%d %s", stamp, slot,
                           " ".join(f"{key}={value}" for key, value in report.items()))


def install_maintenance_timer(app, *, env, db, process_lock):
    """Only the CPython Chat host calls this, never Worker or Mesh queue."""
    if not auto_update_enabled(env):
        return
    task = None
    store = HostMaintenanceStore(db)

    async def loop():
        while True:
            if process_lock.acquire(wait=False):
                try:
                    await maintenance_round(app, env, store)
                except Exception:
                    logger.warning("pc_maintenance_round_failed")
                finally:
                    process_lock.release()
            else:
                logger.warning("pc_maintenance_round lock=busy")
            await asyncio.sleep(INTERVAL)

    async def start():
        nonlocal task
        logger.warning("pc_maintenance_timer_started")
        task = asyncio.create_task(loop())

    async def stop():
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    hooks = lifespan_hooks(app)
    hooks.on_startup.append(start)
    hooks.on_shutdown.insert(0, stop)
