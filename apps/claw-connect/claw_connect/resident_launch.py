"""Canonical Resident launch plan for Claw Connect (#4139 STEP 3).

The Connector supervises exactly one existing Resident
(``kagent.local_agent_resident_process``). Starting that process *without* its
canonical Broker boundary configuration makes it refuse immediately
(``no_configured_broker_boundary``), so a tray start that launches the Resident
anyway produces a short-lived child and no task-receiving loop at all.

This module derives that configuration from facts the Connector already holds —
the committed enrollment record and the canonical protected credential
directory — and reuses the **exact** environment variable names the Resident's
own ``BrokerEntry.from_environment()`` reads. Nothing is minted here: no
authority ref, no request-port factory, no credential, no device identity. Each
value either comes from the committed record or from deployment configuration;
when one is missing the plan is refused with a bounded reason instead of being
defaulted, because a defaulted boundary is a boundary the Resident would accept
and the owner never configured.

    SECOND_BROKER_AUTHORITY=0
    SECOND_CREDENTIAL_STORE=0
    NEW_DEVICE_IDENTITY=0
    SECRET_MATERIAL_IN_ENV=0
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

#: The Resident's own configuration contract (``BrokerEntry.from_environment``).
#: Reused verbatim so the Connector cannot drift from what the Resident reads.
RESIDENT_ENV_DEVICE_ID = "PADIEM_AGENT_DEVICE_ID"
RESIDENT_ENV_AUTHORITY_REF = "PADIEM_AGENT_AUTHORITY_REF"
RESIDENT_ENV_REQUEST_PORT = "PADIEM_AGENT_REQUEST_PORT"
RESIDENT_ENV_CREDENTIAL_DIR = "PADIEM_AGENT_CREDENTIAL_DIR"

#: Bounded, secret-free refusal reasons. Each one names a *missing fact*, so an
#: operator can act on it, and none of them carries a value.
REASON_NO_COMMITTED_ENROLLMENT = "no_committed_enrollment"
REASON_ENROLLMENT_NOT_LIVE = "enrollment_not_live"
REASON_ENROLLMENT_RECORD_UNREADABLE = "enrollment_record_unreadable"
REASON_CREDENTIAL_DIR_UNCONFIGURED = "canonical_credential_dir_unconfigured"
REASON_CREDENTIAL_DIR_INVALID = "canonical_credential_dir_invalid"
REASON_AUTHORITY_REF_UNCONFIGURED = "broker_authority_ref_unconfigured"
REASON_REQUEST_PORT_UNCONFIGURED = "broker_request_port_unconfigured"

#: The Resident's ``module:attribute`` factory shape. Shape-checked only: this
#: module never imports or calls the factory, and never stands up a transport.
_REQUEST_PORT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$")
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")


@dataclass(frozen=True)
class ResidentLaunchPlan:
    """The configuration the one supervised Resident must be started with."""

    device_id: str
    authority_ref: str
    credential_dir: str
    request_port: str

    def environment(self, *, base: Mapping[str, str] | None = None) -> dict[str, str]:
        """The child environment, over the inherited one.

        Only the four canonical keys are set. The credential directory is a
        *path*; the credential itself is never placed in the environment, and
        the Resident keeps loading it from the protected store.
        """
        env = dict(os.environ if base is None else base)
        env[RESIDENT_ENV_DEVICE_ID] = self.device_id
        env[RESIDENT_ENV_AUTHORITY_REF] = self.authority_ref
        env[RESIDENT_ENV_CREDENTIAL_DIR] = self.credential_dir
        env[RESIDENT_ENV_REQUEST_PORT] = self.request_port
        return env

    def safe_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "authority_ref": self.authority_ref,
            "request_port": self.request_port,
            "credential_dir_configured": True,
            "raw_device_credential": False,
            "credential_dir_exposed": False,
            "second_broker_authority": False,
            "new_device_identity": False,
        }


def plan_resident_launch(
    *,
    record: Any,
    environ: Mapping[str, str] | None = None,
) -> tuple[ResidentLaunchPlan | None, str]:
    """Plan the Resident launch, or refuse with the missing fact's name.

    ``record`` is the already-committed enrollment record (or ``None``). The
    live/blocked judgement is delegated to the one existing credential gate
    (``autostart._is_live_enrollment``) rather than re-implemented here, so a
    revoked or expired device cannot be launched by this path either.
    """
    env = os.environ if environ is None else environ
    if record is None:
        return None, REASON_NO_COMMITTED_ENROLLMENT

    # Lazy import: the thin tray path must not pull the enrollment stack in at
    # import time, and the gate itself lives in the autostart contract.
    from .autostart import _is_live_enrollment

    if not _is_live_enrollment(record):
        return None, REASON_ENROLLMENT_NOT_LIVE

    device_id = getattr(record, "device_id", None)
    if not isinstance(device_id, str) or not _REF_RE.fullmatch(device_id):
        return None, REASON_ENROLLMENT_RECORD_UNREADABLE

    credential_dir = (env.get(RESIDENT_ENV_CREDENTIAL_DIR) or "").strip()
    if not credential_dir:
        return None, REASON_CREDENTIAL_DIR_UNCONFIGURED
    # The Resident's own store contract requires an absolute base dir and
    # refuses a symlinked root; refuse here for the same reason instead of
    # spawning a child that is guaranteed to fail.
    expanded = os.path.expanduser(credential_dir)
    if not os.path.isabs(expanded) or os.path.islink(expanded):
        return None, REASON_CREDENTIAL_DIR_INVALID

    authority_ref = (env.get(RESIDENT_ENV_AUTHORITY_REF) or "").strip()
    if not authority_ref or not _REF_RE.fullmatch(authority_ref):
        return None, REASON_AUTHORITY_REF_UNCONFIGURED

    request_port = (env.get(RESIDENT_ENV_REQUEST_PORT) or "").strip()
    if not _REQUEST_PORT_RE.fullmatch(request_port):
        return None, REASON_REQUEST_PORT_UNCONFIGURED

    return (
        ResidentLaunchPlan(
            device_id=device_id,
            authority_ref=authority_ref,
            credential_dir=expanded,
            request_port=request_port,
        ),
        "planned",
    )


__all__ = [
    "REASON_AUTHORITY_REF_UNCONFIGURED",
    "REASON_CREDENTIAL_DIR_INVALID",
    "REASON_CREDENTIAL_DIR_UNCONFIGURED",
    "REASON_ENROLLMENT_NOT_LIVE",
    "REASON_ENROLLMENT_RECORD_UNREADABLE",
    "REASON_NO_COMMITTED_ENROLLMENT",
    "REASON_REQUEST_PORT_UNCONFIGURED",
    "RESIDENT_ENV_AUTHORITY_REF",
    "RESIDENT_ENV_CREDENTIAL_DIR",
    "RESIDENT_ENV_DEVICE_ID",
    "RESIDENT_ENV_REQUEST_PORT",
    "ResidentLaunchPlan",
    "plan_resident_launch",
]
