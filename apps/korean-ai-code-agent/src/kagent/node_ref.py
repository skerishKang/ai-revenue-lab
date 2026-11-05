"""The one reference alphabet a MeshCentral node id is validated against.

Two lanes read the same PC: the private reader (``local_agent_meshcentral_
private_reader``) and the Oracle read executor (``local_agent_oracle_mesh_read``).
Each kept its own copy of this pattern, and #6889 widened only the first, so a
node id carrying ``$`` — every MeshCentral node id does, e.g.
``7P4o…$v5ziNLxqfb$pB`` — was still refused on the product path in 15 ms, before
``meshctrl.js`` ran, while pc_list/pc_shell answered the same node through the
command lane.

The alphabet stays a reference alphabet: a MeshCentral node id is opaque, but it
is not arbitrary text. Space, control characters, an empty value and anything
longer than 256 characters are still refused, and the first character must be a
letter, a digit or ``$`` so a value cannot begin with a separator.

One definition, imported by both lanes, is what keeps the next widening from
reaching only one of them.
"""
from __future__ import annotations

import re
from typing import Any

#: 256 characters at most; ``$`` is part of a MeshCentral node id.
NODE_REF_RE = re.compile(r"^[A-Za-z0-9$][A-Za-z0-9$._:@+\-]{0,255}$")


def is_node_ref(value: Any) -> bool:
    """Whether ``value`` is a node reference both read lanes accept.

    Deliberately no ``strip()``: a value that arrives with surrounding
    whitespace is not the same reference, and trimming it here would accept one
    the caller never wrote.
    """
    return isinstance(value, str) and NODE_REF_RE.fullmatch(value) is not None
