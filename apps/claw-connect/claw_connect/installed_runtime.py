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
    result["PADIEM_AGENT_CREDENTIAL_DIR"] = str(
        protected_credential_directory(state_dir)
    )
    return result
