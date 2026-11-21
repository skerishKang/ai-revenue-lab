"""Release selection: an offer is metadata, never a PC authorization grant."""
from __future__ import annotations

import hashlib
from types import SimpleNamespace

from padiem_ai_core.pc_device_identity import is_pc_device_id

from .pc_helper_update_policy import version_parts

STAGES = ("internal", "percentage", "all", "paused")
DEFAULT_PERCENT = 10
DEVICE_HEADER = "X-Padiem-Device-Id"


def cohort(device_id, managed, percent):
    if managed:
        return "internal"
    if is_pc_device_id(device_id):
        bucket = int.from_bytes(hashlib.sha256(device_id.encode("ascii")).digest()[:8], "big") % 100
        if bucket < percent:
            return "percentage"
    return "remaining"


def _snapshot(manifest):
    return {key: manifest[key] for key in ("version", "sha256", "download_url")}


def _checked_snapshot(value, minimum):
    from .pc_helper_version_routes import helper_manifest

    if not isinstance(value, dict) or set(value) != {"version", "sha256", "download_url"}:
        raise ValueError("invalid release snapshot")
    actual = helper_manifest(SimpleNamespace(pc_pairing_user_helper_url=value["download_url"],
                                             pc_pairing_user_helper_sha256=value["sha256"]))
    if actual is None or _snapshot(actual) != value or version_parts(value["version"]) is None:
        raise ValueError("invalid release snapshot")
    return {**value, "min_supported_version": minimum}


def effective_plan(row, candidate):
    """The last all-stage release becomes the baseline for the next release."""
    if candidate is None:
        raise ValueError("release unavailable")
    minimum = candidate["min_supported_version"]
    if version_parts(candidate["version"]) is None or version_parts(minimum) is None:
        raise ValueError("invalid release version")
    if version_parts(candidate["version"]) < version_parts(minimum):
        raise ValueError("release is below the minimum")
    if row is None:
        return {"initialized": False, "revision": 0, "stage": "all",
                "percent": DEFAULT_PERCENT, "stable": candidate, "target": candidate}
    plan = row["plan"]
    if (not isinstance(plan, dict) or set(plan) != {"stage", "percent", "stable", "target"}
            or plan["stage"] not in STAGES or type(plan["percent"]) is not int
            or not 1 <= plan["percent"] <= 99):
        raise ValueError("invalid rollout")
    stable = _checked_snapshot(plan["stable"], minimum)
    target = _checked_snapshot(plan["target"], minimum)
    stage, percent = plan["stage"], plan["percent"]
    if _snapshot(target) != _snapshot(candidate):
        if stage == "all":
            stable = target
        if version_parts(candidate["version"]) <= version_parts(stable["version"]):
            # A versioned artifact must not silently change bytes or go backwards.
            if _snapshot(candidate) != _snapshot(stable):
                raise ValueError("non-monotonic release")
        if candidate["version"] == target["version"]:
            raise ValueError("release identity changed")
        target, stage = candidate, "paused" if stage == "paused" else "internal"
    return {"initialized": True, "revision": row["revision"], "stage": stage,
            "percent": percent, "stable": stable, "target": target}


def offer(plan, *, device_id=None, managed=False):
    stable, target = plan["stable"], plan["target"]
    # A raised minimum supersedes every rollout stage, including pause.
    if version_parts(stable["version"]) < version_parts(target["min_supported_version"]):
        return target
    group = cohort(device_id, managed, plan["percent"])
    stage = plan["stage"]
    if stage == "all" or (stage == "internal" and group == "internal") or (
            stage == "percentage" and group in ("internal", "percentage")):
        return target
    return stable


def change_plan(plan, action, percent):
    """Only bounded state changes; candidates and URLs come from deployment config."""
    stage = plan["stage"]
    if action == "initialize" and not plan["initialized"]:
        stage = "all"
    elif not plan["initialized"]:
        raise ValueError("initialize rollout first")
    elif action == "next":
        stage = {"paused": "internal", "internal": "percentage", "percentage": "all"}.get(stage)
        if stage is None:
            raise ValueError("already fully open")
    elif action == "pause":
        stage = "paused"
    elif action != "percentage":
        raise ValueError("invalid rollout action")
    return {"stage": stage, "percent": percent,
            "stable": _snapshot(plan["stable"]), "target": _snapshot(plan["target"])}


async def load_plan(state, candidate):
    pairing = getattr(state, "pc_device_pairing_store", None)
    getter = getattr(pairing, "load_helper_rollout", None)
    row = await getter() if callable(getter) else None
    return effective_plan(row, candidate)


async def device_offer(state, candidate, *, device_id=None, install_id=False):
    plan = await load_plan(state, candidate)
    if not plan["initialized"] or plan["stage"] in ("all", "paused"):
        return offer(plan)
    pairing = state.pc_device_pairing_store
    if is_pc_device_id(device_id):
        resolved = await pairing.resolve_helper_rollout_device(device_id=device_id, install_id=install_id)
        if isinstance(resolved, dict):
            return offer(plan, device_id=resolved["device_id"], managed=resolved["managed"])
    return offer(plan)


def summarize(plan, devices, managed_ids, observations, outcomes):
    groups = {name: {"total": 0, "updated": 0, "failed": 0, "rollback": 0}
              for name in ("internal", "percentage", "remaining")}
    for device in devices:
        group = groups[cohort(device, device in managed_ids, plan["percent"])]
        group["total"] += 1
        if observations.get(device, {}).get("helper_sha256") == plan["target"]["sha256"]:
            group["updated"] += 1
        outcome = outcomes.get(device)
        if outcome in ("failed", "rollback"):
            group[outcome] += 1
    return groups
