"""#3099 read-only Connector self-diagnosis and secret-free support bundle.

A PC fails in one of a small number of places: the Agent source is not
installed, the device was never paired, the enrollment was blocked or
revoked, the supervised Resident is not up, or the user turned the
Connector off. The Connector already observes every one of those facts
locally, but it exposed them one command at a time, so neither the user nor
support could see *why* a PC was not connected.

This module turns those local facts into ONE bounded diagnosis with a closed
reason vocabulary and a single recommended next action, plus a support
bundle a user can hand over.

The contract:

* **Read-only.** No Broker call, no network, no credential readback, no
  device identity write, no Agent execution, no registry mutation.
* **No secret.** No credential, no pairing code, no enrollment record value,
  no token, no absolute path, no stdout, no task payload.
* **No identifier.** The bundle carries a non-reversible short fingerprint of
  the device id so support can correlate two reports, never the id itself.
* **Closed vocabulary.** Every reason, action and advisory comes from the
  tuples below, so a new observation can never leak an arbitrary string into
  user-facing or support-facing output.

The facts are injected, so the diagnosis is a pure function of observed state
and is verifiable offline without a tray, Broker, Agent or Windows session.
"""
from __future__ import annotations

import hashlib
from typing import Any, Mapping

DIAGNOSIS_VERSION = "padiem-connector-self-diagnosis.v1"
SUPPORT_BUNDLE_VERSION = "padiem-connector-support-bundle.v1"

#: A blocking reason. Exactly one is reported, chosen by the fixed priority
#: below. ``ok`` means nothing blocks the first-run chain.
REASONS = (
    "ok",
    "agent_source_not_configured",
    "agent_source_invalid",
    "agent_source_conflict",
    "not_enrolled",
    "enrollment_blocked",
    "enrollment_revoked",
    "resident_not_running",
    "not_connected",
    "paused",
)

#: The single next action for the reported reason. ``none`` means there is
#: nothing for the user to do.
ACTIONS = (
    "none",
    "install_agent",
    "review_agent_source",
    "login_and_pair",
    "review_enrollment",
    "start_connector",
    "resume_connector",
)

#: Non-blocking observations. They never change the reason or the action.
ADVISORIES = (
    "autostart_off",
    "single_instance_not_held",
)

#: Agent source states projected from the reviewed Agent preflight.
_AGENT_SOURCE_STATES = {
    "ok": "ready",
    "agent_source_not_configured": "not_configured",
    "agent_source_invalid": "invalid",
    "agent_source_conflict": "conflict",
    "agent_source_config_invalid": "invalid",
}

#: Enrollment states projected from the committed device binding.
_ENROLLMENT_STATES = {
    "enrolled": "enrolled",
    "not_enrolled": "not_enrolled",
    "blocked": "blocked",
    "revoked": "revoked",
}


def device_fingerprint(device_id: str | None) -> str | None:
    """A non-reversible short fingerprint of a device id.

    Support needs to correlate two reports about the same PC without the
    bundle carrying the device id itself. A truncated SHA-256 is enough to
    correlate and useless to recover the id.
    """
    if not isinstance(device_id, str) or not device_id:
        return None
    digest = hashlib.sha256(device_id.encode("utf-8")).hexdigest()
    return "sha256:" + digest[:16]


def _agent_source_state(agent: Mapping[str, Any] | None) -> str:
    if not isinstance(agent, Mapping):
        return "not_configured"
    status = agent.get("agent_status")
    if not isinstance(status, str):
        return "not_configured"
    return _AGENT_SOURCE_STATES.get(status, "invalid")


def _enrollment_state(enrollment: Mapping[str, Any] | None) -> str:
    if not isinstance(enrollment, Mapping):
        return "not_enrolled"
    if enrollment.get("enrolled") is not True:
        return "not_enrolled"
    lifecycle = enrollment.get("device_lifecycle")
    if isinstance(lifecycle, str) and "revok" in lifecycle.lower():
        return "revoked"
    if enrollment.get("blocked") is True:
        return "blocked"
    return "enrolled"


def diagnose(
    *,
    agent: Mapping[str, Any] | None = None,
    enrollment: Mapping[str, Any] | None = None,
    connection_state: str = "disconnected",
    resident_running: bool = False,
    autostart_enabled: bool = False,
    single_instance: bool = False,
) -> dict[str, Any]:
    """One bounded self-diagnosis from locally observed facts only.

    The reason priority is fixed so the same facts always report the same
    reason: the earliest broken link in the first-run chain wins, and a
    later symptom never masks an earlier one.
    """
    agent_state = _agent_source_state(agent)
    enrollment_state = _enrollment_state(enrollment)
    state = connection_state if isinstance(connection_state, str) else "disconnected"

    advisories: list[str] = []
    if not autostart_enabled:
        advisories.append("autostart_off")
    if not single_instance:
        advisories.append("single_instance_not_held")

    if agent_state != "ready":
        reason = {
            "not_configured": "agent_source_not_configured",
            "invalid": "agent_source_invalid",
            "conflict": "agent_source_conflict",
        }[agent_state]
        action = {
            "not_configured": "install_agent",
            "invalid": "review_agent_source",
            "conflict": "review_agent_source",
        }[agent_state]
    elif enrollment_state == "not_enrolled":
        reason, action = "not_enrolled", "login_and_pair"
    elif enrollment_state == "revoked":
        reason, action = "enrollment_revoked", "review_enrollment"
    elif enrollment_state == "blocked":
        reason, action = "enrollment_blocked", "review_enrollment"
    elif state == "paused":
        reason, action = "paused", "resume_connector"
    elif state not in ("connected", "connecting"):
        reason, action = "not_connected", "start_connector"
    elif not resident_running:
        reason, action = "resident_not_running", "start_connector"
    else:
        reason, action = "ok", "none"

    return {
        "diagnosis_version": DIAGNOSIS_VERSION,
        "ready": reason == "ok",
        "reason": reason,
        "action": action,
        "checks": {
            "agent_source": agent_state,
            "enrollment": enrollment_state,
            "resident": "running" if resident_running else "not_running",
            "autostart": "enabled" if autostart_enabled else "disabled",
            "connection": state,
        },
        "advisories": advisories,
    }


def support_bundle(
    diagnosis: Mapping[str, Any], *, connector_version: str, device_id: str | None = None
) -> dict[str, Any]:
    """The secret-free support bundle a user can hand to support.

    It carries the diagnosis, the Connector version and a non-reversible
    device fingerprint. It never carries a device id, a binding ref, an
    account ref, a workspace ref, a credential, a pairing code, an absolute
    path, stdout or a task payload.
    """
    return {
        "bundle_version": SUPPORT_BUNDLE_VERSION,
        "connector_version": connector_version,
        "device_fingerprint": device_fingerprint(device_id),
        "diagnosis": dict(diagnosis),
    }


__all__ = [
    "ACTIONS",
    "ADVISORIES",
    "DIAGNOSIS_VERSION",
    "REASONS",
    "SUPPORT_BUNDLE_VERSION",
    "diagnose",
    "device_fingerprint",
    "support_bundle",
]
