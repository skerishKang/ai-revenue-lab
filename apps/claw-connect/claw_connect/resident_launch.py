"""Canonical Resident launch plan for Claw Connect (#4139 STEP 3).

The Connector supervises exactly one existing Resident
(``kagent.local_agent_resident_process``). Starting that process *without* its
canonical Broker boundary configuration makes it refuse immediately
(``no_configured_broker_boundary``), so a tray start that launches the Resident
anyway produces a short-lived child and no task-receiving loop at all.

This module derives that configuration from facts the Connector already holds —
the committed enrollment record and the canonical protected credential
directory — and reuses the **exact** environment variable names the Resident
reads. Nothing is minted here: no authority ref, no request-port factory, no
credential, no device identity. Each value either comes from the committed
record or from deployment configuration; when one is missing the plan is refused
with a bounded reason instead of being defaulted, because a defaulted boundary
is a boundary the Resident would accept and the owner never configured.

Four keys are read by the Resident's own ``BrokerEntry.from_environment()``. The
fifth, ``PADIEM_AGENT_BROKER_URL``, is read by the request-port *factory* that
entry is configured with (``PADIEM_AGENT_REQUEST_PORT`` is a
``module:factory`` string, not a TCP port number), so a plan that omitted it
would spawn a child that dies constructing its port. It is required here for
the same reason as the rest: the Connector must not start what it cannot
configure.

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
#: Read by the request-port factory itself rather than by ``from_environment``.
#: Without it the factory refuses, and the child dies before it can emit any
#: bounded refusal of its own.
RESIDENT_ENV_BROKER_URL = "PADIEM_AGENT_BROKER_URL"
#: Optional P01 verified-text plan material supplied by deployment (module:attribute).
#: Absent leaves the TXT lane inactive; never minted locally.
RESIDENT_ENV_VERIFIED_TEXT_PLAN_SOURCE = "PADIEM_AGENT_VERIFIED_TEXT_PLAN_SOURCE"

#: Bounded, secret-free refusal reasons. Each one names a *missing fact*, so an
#: operator can act on it, and none of them carries a value.
REASON_NO_COMMITTED_ENROLLMENT = "no_committed_enrollment"
REASON_ENROLLMENT_NOT_LIVE = "enrollment_not_live"
REASON_ENROLLMENT_RECORD_UNREADABLE = "enrollment_record_unreadable"
REASON_CREDENTIAL_DIR_UNCONFIGURED = "canonical_credential_dir_unconfigured"
REASON_CREDENTIAL_DIR_INVALID = "canonical_credential_dir_invalid"
REASON_AUTHORITY_REF_UNCONFIGURED = "broker_authority_ref_unconfigured"
REASON_REQUEST_PORT_UNCONFIGURED = "broker_request_port_unconfigured"
REASON_BROKER_URL_UNCONFIGURED = "broker_url_unconfigured"
REASON_VERIFIED_TEXT_PLAN_SOURCE_INVALID = "verified_text_plan_source_invalid"

#: The Resident's ``module:attribute`` factory shape. Shape-checked only: this
#: module never imports or calls the factory, and never stands up a transport.
_REQUEST_PORT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$")
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")
#: Keep in step with ``enrollment._BROKER_URL_RE``: the Resident carries the
#: device credential to this origin, so it is held to the same TLS-only,
#: credentials-free, query-free contract the Connector already pins for the
#: broker endpoint it enrolls against. A looser check here would let a plan
#: configure cleartext delivery of a credential the Connector itself refuses.
_BROKER_URL_RE = re.compile(r"^https://[A-Za-z0-9.\-]+(?::443)?(?:/[^\s?#]*)?$")


@dataclass(frozen=True)
class ResidentLaunchPlan:
    """The configuration the one supervised Resident must be started with."""

    device_id: str
    authority_ref: str
    credential_dir: str
    request_port: str
    broker_url: str
    verified_text_plan_source: str | None = None

    def environment(self, *, base: Mapping[str, str] | None = None) -> dict[str, str]:
        """The child environment, over the inherited one.

        Only the canonical keys are set. The credential directory is a
        *path*; the credential itself is never placed in the environment, and
        the Resident keeps loading it from the protected store. The optional
        verified-text plan source is forwarded only when configured.
        """
        env = dict(os.environ if base is None else base)
        env[RESIDENT_ENV_DEVICE_ID] = self.device_id
        env[RESIDENT_ENV_AUTHORITY_REF] = self.authority_ref
        env[RESIDENT_ENV_CREDENTIAL_DIR] = self.credential_dir
        env[RESIDENT_ENV_REQUEST_PORT] = self.request_port
        env[RESIDENT_ENV_BROKER_URL] = self.broker_url
        if self.verified_text_plan_source is None:
            env.pop(RESIDENT_ENV_VERIFIED_TEXT_PLAN_SOURCE, None)
        else:
            env[RESIDENT_ENV_VERIFIED_TEXT_PLAN_SOURCE] = self.verified_text_plan_source
        return env

    def safe_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "authority_ref": self.authority_ref,
            "request_port": self.request_port,
            "broker_url_configured": True,
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

    # Required because the configured factory reads it, and refuses without it.
    # Checked against the Connector's own broker-endpoint contract so a plan
    # cannot point the Resident at a cleartext origin for the credential.
    broker_url = (env.get(RESIDENT_ENV_BROKER_URL) or "").strip()
    if not _BROKER_URL_RE.fullmatch(broker_url):
        return None, REASON_BROKER_URL_UNCONFIGURED

    # Optional P01 verified-text material. CENTRAL supplies module:factory;
    # absent leaves TXT inactive. Invalid shape refuses rather than
    # forwarding a broken value.
    verified_text_plan_source = (
        env.get(RESIDENT_ENV_VERIFIED_TEXT_PLAN_SOURCE) or ""
    ).strip()
    if verified_text_plan_source and not _REQUEST_PORT_RE.fullmatch(
        verified_text_plan_source
    ):
        return None, REASON_VERIFIED_TEXT_PLAN_SOURCE_INVALID
    if not verified_text_plan_source:
        verified_text_plan_source = None

    return (
        ResidentLaunchPlan(
            device_id=device_id,
            authority_ref=authority_ref,
            credential_dir=expanded,
            request_port=request_port,
            broker_url=broker_url,
            verified_text_plan_source=verified_text_plan_source,
        ),
        "planned",
    )


__all__ = [
    "REASON_AUTHORITY_REF_UNCONFIGURED",
    "REASON_BROKER_URL_UNCONFIGURED",
    "REASON_VERIFIED_TEXT_PLAN_SOURCE_INVALID",
    "REASON_CREDENTIAL_DIR_INVALID",
    "REASON_CREDENTIAL_DIR_UNCONFIGURED",
    "REASON_ENROLLMENT_NOT_LIVE",
    "REASON_ENROLLMENT_RECORD_UNREADABLE",
    "REASON_NO_COMMITTED_ENROLLMENT",
    "REASON_REQUEST_PORT_UNCONFIGURED",
    "RESIDENT_ENV_AUTHORITY_REF",
    "RESIDENT_ENV_BROKER_URL",
    "RESIDENT_ENV_CREDENTIAL_DIR",
    "RESIDENT_ENV_VERIFIED_TEXT_PLAN_SOURCE",
    "RESIDENT_ENV_DEVICE_ID",
    "RESIDENT_ENV_REQUEST_PORT",
    "ResidentLaunchPlan",
    "plan_resident_launch",
]
