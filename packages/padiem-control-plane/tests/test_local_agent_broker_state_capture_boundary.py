from __future__ import annotations

import pytest

from padiem_control_plane.local_agent_broker import InMemoryLocalAgentBrokerAuthority
from padiem_control_plane.local_agent_broker_state import (
    InMemoryLocalAgentBrokerStatePort,
    LocalAgentBrokerStateSnapshot,
    StateBackedLocalAgentBrokerAuthority,
)

PEPPER = b"snapshot-capture-boundary-pepper"
AUTHORITY_REF = "control-plane.local-agent-broker.capture-boundary.v1"


def test_snapshot_capture_accepts_only_materialized_canonical_core() -> None:
    canonical = InMemoryLocalAgentBrokerAuthority(pepper=PEPPER, authority_ref=AUTHORITY_REF)
    snapshot = LocalAgentBrokerStateSnapshot.capture(canonical)
    assert snapshot.authority_ref == AUTHORITY_REF

    state_backed = StateBackedLocalAgentBrokerAuthority(
        pepper=PEPPER,
        authority_ref=AUTHORITY_REF,
        state_port=InMemoryLocalAgentBrokerStatePort(),
    )
    with pytest.raises(ValueError, match="exact InMemoryLocalAgentBrokerAuthority"):
        LocalAgentBrokerStateSnapshot.capture(state_backed)
