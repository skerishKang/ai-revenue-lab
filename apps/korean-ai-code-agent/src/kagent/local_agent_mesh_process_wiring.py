"""Assemble the MeshCentral process stop lane without growing the executor.

The executor's file-size cap is a warning, not a place to put new code (#7216).
This module owns the small piece of composition: one authenticated control
socket and one lane per node. A deployment that signs in with a login key keeps
the terminal fallback, because the socket authenticates with the operator
password header.
"""
from __future__ import annotations

import os
from typing import Any, Callable

from .local_agent_meshcentral_process_port import (
    MeshCentralProcessLane,
    MeshCentralProcessSocket,
)


def process_lane_kwargs(
    login_user: str,
    password_provider: Callable[[], str],
    mesh_url: str,
    login_key_file: str | None,
) -> dict[str, Any]:
    """The two command-port arguments that turn the process lane on or off.

    The switch is read once, when the executor is built, exactly like every
    other deployment setting. The factory is per node: a multi-PC executor
    must not reuse one lane's node id for a stop on another PC.
    """
    if login_key_file is not None:
        return {"process_lane_factory": None, "process_lane_enabled": False}
    socket = MeshCentralProcessSocket(
        login_user=login_user,
        password_provider=password_provider,
        url=mesh_url,
    )

    def lane_for(node_ref: str) -> MeshCentralProcessLane:
        return MeshCentralProcessLane(
            node_ref=node_ref,
            ask=socket.ask,
            response_id="padiem-process-" + os.urandom(8).hex(),
        )

    flag = os.environ.get("PADIEM_MESH_PROCESS_LANE", "1").strip().lower()
    return {
        "process_lane_factory": lane_for,
        "process_lane_enabled": flag not in ("0", "false", "no", "off"),
    }
