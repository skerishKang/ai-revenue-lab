"""#5172 canonical PC device identity grammar.

The device identity is one value that crosses the Broker directory, the
browser selection, the saved preference, the model work context, the Engine
plan arguments and the signed dispatch. These tests pin the single grammar
every one of those boundaries uses, and pin that it stays closed: a path, a
URL, whitespace, a control character and a second path separator are never a
device identity.
"""

from __future__ import annotations

import re

import pytest

from padiem_ai_core.pc_device_identity import (
    PC_DEVICE_ID_MAX_CHARS,
    PC_DEVICE_ID_PATTERN,
    PC_MESH_NODE_ID_PATTERN,
    is_pc_device_id,
    is_pc_mesh_node_id,
    pc_device_id_form,
)

# The real MeshCentral node reference shape observed on the deployed Mesh
# server: a bare node id that carries the domain separator.
REAL_MESH_NODE_REF = "Ab3Cd4Ef5Gh6Ij7Kl8Mn9Op0Qr1St2Uv3Wx4" + "@" + "meshdomain1"

# The composed identity MeshCentral itself builds, with the default (empty)
# domain and with an explicit domain.
DEFAULT_DOMAIN_NODE_ID = "node//" + REAL_MESH_NODE_REF
EXPLICIT_DOMAIN_NODE_ID = "node/meshdomain1/" + REAL_MESH_NODE_REF


@pytest.mark.parametrize(
    "value",
    [
        "device-1",
        "office",
        "mesh-node",
        REAL_MESH_NODE_REF,
        "pc_01H",
        "a",
        "A" * PC_DEVICE_ID_MAX_CHARS,
    ],
)
def test_bare_device_ids_are_accepted(value: str) -> None:
    assert is_pc_device_id(value) is True
    assert pc_device_id_form(value) == "bare"


@pytest.mark.parametrize(
    "value",
    [
        DEFAULT_DOMAIN_NODE_ID,
        EXPLICIT_DOMAIN_NODE_ID,
        "node//abc",
        "node/mydomain/abc",
        "node/mine_srv-1/abc.def:1@x",
    ],
)
def test_composed_mesh_node_ids_are_accepted(value: str) -> None:
    assert is_pc_device_id(value) is True
    assert is_pc_mesh_node_id(value) is True
    assert pc_device_id_form(value) == "mesh_node"


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "node/",
        "node//",
        "node/a/",
        "node/a/b/c",
        "node//a/b",
        "node/a/b ",
        "node /a/b",
        "node/a/b\n",
        "node/a/b\t",
        "https://example.test/node/a",
        "https://example.test",
        "../../etc/passwd",
        "C:\\Windows\\System32",
        "node//a\x00b",
        "node//a\nb",
        "a" * (PC_DEVICE_ID_MAX_CHARS + 1),
    ],
)
def test_non_device_identities_are_refused(value: str) -> None:
    assert is_pc_device_id(value) is False
    assert is_pc_mesh_node_id(value) is False
    assert pc_device_id_form(value) is None


def test_non_string_values_are_refused() -> None:
    for value in (None, 1, 1.5, True, b"node//abc", ["node//abc"], {"device_id": "a"}):
        assert is_pc_device_id(value) is False
        assert pc_device_id_form(value) is None


def test_the_two_forms_are_disjoint() -> None:
    """A bare id never contains a path separator; a node id always does."""
    bare = re.compile(PC_DEVICE_ID_PATTERN)
    node = re.compile(PC_MESH_NODE_ID_PATTERN)
    for value in ("device-1", REAL_MESH_NODE_REF, "node//abc", "node/d/abc"):
        assert not (bare.fullmatch(value) and node.fullmatch(value))


def test_the_bare_form_still_accepts_every_previously_valid_device_id() -> None:
    """The grammar is additive: nothing the old closed form allowed is lost.

    The old deployed bare form was ``^[A-Za-z0-9_.:-]{1,128}$``. A device
    identity is never used as a filesystem path, so keeping the old shape
    admissible cannot widen it into a path: a separator, a whitespace run, a
    control character and a URL scheme stay refused.
    """
    old = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
    for value in ("a", "A" * 128, "a.b_c:d-e", "..", "___", ":-:", "node"):
        assert old.fullmatch(value) is not None
        assert is_pc_device_id(value) is True


def test_the_composed_form_is_bounded() -> None:
    """A composed identity cannot grow without bound."""
    assert is_pc_device_id("node/" + "d" * 64 + "/" + "n" * 128) is True
    assert is_pc_device_id("node/" + "d" * 65 + "/" + "n" * 1) is False
    assert is_pc_device_id("node//" + "n" * 129) is False
