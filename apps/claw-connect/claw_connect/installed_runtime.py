"""Installed release constants for the existing canonical Broker boundary.

These nonsecret pins are taken from the reviewed B54 activation gate, not
supplied by a browser or customer. The authoritative Broker still validates
every binding, credential, session, tenant, and product grant.
"""
from __future__ import annotations
from collections.abc import Mapping
from pathlib import Path

BROKER_ORIGIN = "https://local-agent.padiem.net"
AUTHORITY_REF = "control-plane.local-agent-broker.production.v1"
REQUEST_PORT = "kagent.local_agent_broker_production_entry:make_production_request_port"
VERIFIED_TEXT_PLAN_SOURCE = (
    "kagent.verified_engine_text_read_plan_source:make_verified_text_plan_source"
)


def installed_resident_environ(
    *, state_dir: Path, environ: Mapping[str, str],
) -> dict[str, str]:
    from .customer_enrollment import protected_credential_directory
    result = dict(environ)
    # Installed customer product has one fixed, inspected release boundary.
    # Ignore ambient overrides in the customer's context: no alternate Broker.
    result["PADIEM_AGENT_BROKER_URL"] = BROKER_ORIGIN
    result["PADIEM_AGENT_AUTHORITY_REF"] = AUTHORITY_REF
    result["PADIEM_AGENT_REQUEST_PORT"] = REQUEST_PORT
    # This only loads the canonical parser of authenticated Broker material.
    # It cannot approve a path or read without that command's verified receipt.
    result["PADIEM_AGENT_VERIFIED_TEXT_PLAN_SOURCE"] = VERIFIED_TEXT_PLAN_SOURCE
    result["PADIEM_AGENT_CREDENTIAL_DIR"] = str(
        protected_credential_directory(state_dir)
    )
    # #3099: the bounded local diagnostics file the Connector keeps up to
    # date and the Resident reads for the heartbeat it already sends. The
    # Resident inherits this value; no new channel is opened.
    from .local_diagnostics_report import (
        LOCAL_DIAGNOSTICS_FILE_ENV,
        local_diagnostics_path,
    )

    result[LOCAL_DIAGNOSTICS_FILE_ENV] = str(local_diagnostics_path(state_dir))
    return result
