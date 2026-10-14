"""Production broker request port for the resident process (#4139 LOCAL2).

The resident's ``PADIEM_AGENT_REQUEST_PORT`` points at this factory. It
connects to the shared production broker service over HTTPS; it never creates
a local authority.

The broker origin comes from ``PADIEM_AGENT_BROKER_URL`` (already the
canonical connector-configured origin). Absent or malformed origin refuses.
"""

from __future__ import annotations

import os

from .contracts import ContractError
from .local_agent_broker_pairing_handoff_entry import BrokerClientPort

__all__ = ["make_production_request_port"]


def make_production_request_port() -> BrokerClientPort:
    base_url = (os.environ.get("PADIEM_AGENT_BROKER_URL") or "").strip()
    if not base_url:
        raise ContractError("PADIEM_AGENT_BROKER_URL must name the shared broker service")
    return BrokerClientPort(base_url)
