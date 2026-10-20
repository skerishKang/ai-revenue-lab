"""#3099 the PC diagnostic vocabulary is identical in every package.

The shared package is not guaranteed to be installed in every deployment of
the Chat lane, so the packages that carry this contract keep a local copy of
the vocabulary. A local copy is only safe if a machine check proves it
matches the canonical one, so this test reads the five definitions from their
source and compares them.

It parses the source rather than importing it, so the proof holds even in a
lane where one of the packages is not importable.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

#: The canonical definition and the four local copies, with the names each
#: package uses for the same three closed vocabularies.
SOURCES = {
    "core": (
        "packages/padiem-ai-core/padiem_ai_core/pc_device_diagnostics.py",
        {
            "keys": "DIAGNOSTIC_KEYS",
            "agent_source": "AGENT_SOURCE_STATES",
            "autostart": "AUTOSTART_STATES",
            "resident": "RESIDENT_STATES",
            "unknown": "UNKNOWN",
        },
    ),
    "chat": (
        "apps/padiem-chat/app/pc_device_diagnostics_projection.py",
        {
            "keys": "DIAGNOSTIC_KEYS",
            "agent_source": "AGENT_SOURCE_STATES",
            "autostart": "AUTOSTART_STATES",
            "resident": "RESIDENT_STATES",
            "unknown": "UNKNOWN",
        },
    ),
    "kagent": (
        "apps/korean-ai-code-agent/src/kagent/pc_device_diagnostics.py",
        {
            "keys": "DIAGNOSTIC_KEYS",
            "agent_source": "AGENT_SOURCE_STATES",
            "autostart": "AUTOSTART_STATES",
            "resident": "RESIDENT_STATES",
            "unknown": "UNKNOWN",
        },
    ),
    "broker": (
        "packages/padiem-control-plane/local_agent_broker_device_diagnostics.py",
        {
            "keys": "DIAGNOSTIC_KEYS",
            "agent_source": "AGENT_SOURCE_STATES",
            "autostart": "AUTOSTART_STATES",
            "resident": "RESIDENT_STATES",
            "unknown": "UNKNOWN",
        },
    ),
    "connector": (
        "apps/claw-connect/claw_connect/local_diagnostics_report.py",
        {
            "keys": "LOCAL_CHECK_KEYS",
            "agent_source": "LOCAL_AGENT_SOURCE_STATES",
            "autostart": "LOCAL_AUTOSTART_STATES",
            "resident": "LOCAL_RESIDENT_STATES",
            "unknown": "UNKNOWN",
        },
    ),
}


def _literal(path: Path, name: str):
    """The value of one module-level literal assignment, read from source."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                return ast.literal_eval(node.value)
    raise AssertionError(f"{path} does not define {name}")


def test_every_package_carries_the_same_vocabulary():
    canonical = {
        slot: _literal(REPO / SOURCES["core"][0], SOURCES["core"][1][slot])
        for slot in ("keys", "agent_source", "autostart", "resident", "unknown")
    }
    assert canonical["keys"] == ("agent_source", "autostart", "resident")
    assert canonical["unknown"] == "unknown"
    for label, (relative, names) in SOURCES.items():
        for slot, name in names.items():
            value = _literal(REPO / relative, name)
            assert value == canonical[slot], f"{label}.{name} drifted"


def test_the_vocabulary_carries_no_path_or_secret_shape():
    for label, (relative, names) in SOURCES.items():
        for slot, name in names.items():
            value = _literal(REPO / relative, name)
            if isinstance(value, str):
                assert value.islower() and " " not in value, f"{label}.{name}"
                continue
            for entry in value:
                assert isinstance(entry, str)
                assert "/" not in entry and "\\" not in entry
                assert len(entry) <= 32
