"""Canonical PC device identity grammar (#5172).

One device identity crosses the whole PC boundary: the Broker device
directory, the browser selection, the saved preference, the model work
context, the Engine plan arguments, the ToolSpec, the signed dispatch and the
returned result. Every one of those boundaries has to accept the *same*
value, or the identity is silently dropped on the way and the PC is never
reachable even though the Mesh execution target resolved.

Two forms are canonical.

``bare``
    ``^[A-Za-z0-9_.:@+-]{1,128}$`` - the device id the Broker device
    directory and the deployment ownership map already use.

``mesh_node``
    ``^node/<domain>/<node-id>`` - the composed MeshCentral identity.
    MeshCentral itself composes it as ``"node/" + domain + "/" + node_id``,
    and the default MeshCentral domain is empty, so the default-domain form
    is ``node//<node-id>``. The node id segment is the bare form, because
    the composed identity is the same identity the bare one names.

The grammar is deliberately closed. It never admits a path, a URL, a
whitespace run, a control character or a second path separator, so a
composed identity can never smuggle a filesystem path or a remote location
through a boundary that only ever wanted to name one PC.

This module is the single authority for the grammar. Boundaries that cannot
import a shared package keep a local copy of the same pattern and a parity
test proves the copies are identical.
"""

from __future__ import annotations

import re

#: Maximum length of a bare device id.
PC_DEVICE_ID_MAX_CHARS = 128
#: Maximum length of a composed Mesh node id, including both separators.
PC_MESH_NODE_ID_MAX_CHARS = 256
#: Maximum length of the MeshCentral domain segment. The default domain is
#: the empty string, so the segment is optional.
PC_MESH_DOMAIN_MAX_CHARS = 64

#: The bare device id pattern, as source. Kept as source so the boundaries
#: that cannot import this module can copy the exact same string and prove
#: the copies are identical.
PC_DEVICE_ID_PATTERN = r"^[A-Za-z0-9_.:@+-]{1,128}$"
#: The composed Mesh node id pattern, as source.
PC_MESH_NODE_ID_PATTERN = (
    r"^node/[A-Za-z0-9._-]{0,64}/[A-Za-z0-9_.:@+-]{1,128}$"
)

PC_DEVICE_ID_RE = re.compile(PC_DEVICE_ID_PATTERN)
PC_MESH_NODE_ID_RE = re.compile(PC_MESH_NODE_ID_PATTERN)

#: The literal prefix MeshCentral uses for a composed node identity.
PC_MESH_NODE_ID_PREFIX = "node/"


def is_pc_device_id(value: object) -> bool:
    """True when the value is a canonical PC device identity of either form.

    The two forms are disjoint: a bare device id never contains the path
    separator, and a composed Mesh node id always starts with ``node/``.
    """
    if not isinstance(value, str) or not value:
        return False
    if len(value) > PC_MESH_NODE_ID_MAX_CHARS:
        return False
    return bool(
        PC_DEVICE_ID_RE.fullmatch(value) or PC_MESH_NODE_ID_RE.fullmatch(value)
    )


def is_pc_mesh_node_id(value: object) -> bool:
    """True only for the composed MeshCentral node identity."""
    if not isinstance(value, str) or not value:
        return False
    if len(value) > PC_MESH_NODE_ID_MAX_CHARS:
        return False
    return bool(PC_MESH_NODE_ID_RE.fullmatch(value))


def pc_device_id_form(value: object) -> str | None:
    """``"bare"``, ``"mesh_node"`` or ``None`` for an unusable value."""
    if not isinstance(value, str) or not value:
        return None
    if is_pc_mesh_node_id(value):
        return "mesh_node"
    if PC_DEVICE_ID_RE.fullmatch(value):
        return "bare"
    return None


__all__ = [
    "PC_DEVICE_ID_MAX_CHARS",
    "PC_DEVICE_ID_PATTERN",
    "PC_DEVICE_ID_RE",
    "PC_MESH_DOMAIN_MAX_CHARS",
    "PC_MESH_NODE_ID_MAX_CHARS",
    "PC_MESH_NODE_ID_PATTERN",
    "PC_MESH_NODE_ID_PREFIX",
    "PC_MESH_NODE_ID_RE",
    "is_pc_device_id",
    "is_pc_mesh_node_id",
    "pc_device_id_form",
]
