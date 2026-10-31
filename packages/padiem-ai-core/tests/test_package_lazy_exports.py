"""The package surface is exported lazily at exactly the old fidelity.

Importing ``padiem_ai_core`` used to execute every submodule eagerly, which is
how a Worker isolate's first request paid for memory/agent/skill/connector
modules no request path needed. The surface itself is unchanged — ``__all__``
keeps its original contents and order, every name resolves to the same object
as its owning submodule, and the optional tool-runtime/image-helper groups
keep their custom dependency messages.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]

_PROBE = r"""
import sys

import padiem_ai_core

heavy = [
    "padiem_ai_core.memory",
    "padiem_ai_core.memory_context",
    "padiem_ai_core.agent_planner",
    "padiem_ai_core.skill_registry",
    "padiem_ai_core.connectors",
    "padiem_ai_core.orchestration",
    "padiem_ai_core.web_runtime",
    "padiem_ai_core.grounding_runtime",
]
loaded = [name for name in heavy if name in sys.modules]
if loaded:
    raise AssertionError("package import executed submodules: " + ", ".join(loaded))

import padiem_ai_core.document_semantics as document_semantics

if padiem_ai_core.DocumentNormalizationError is not document_semantics.DocumentNormalizationError:
    raise AssertionError("lazy export is not the owning submodule's object")

try:
    padiem_ai_core.definitely_not_a_core_export
except AttributeError:
    pass
else:
    raise AssertionError("unknown attribute resolved")

print("LAZY_SURFACE_OK")
"""


def test_importing_the_package_executes_no_submodule_and_keeps_the_surface():
    completed = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=_PACKAGE_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )
    assert completed.returncode == 0, (completed.stdout + completed.stderr)[-2000:]
    assert "LAZY_SURFACE_OK" in completed.stdout


def test_dir_still_lists_the_whole_surface():
    import padiem_ai_core

    listed = dir(padiem_ai_core)
    for name in padiem_ai_core.__all__:
        assert name in listed


@pytest.mark.parametrize("name", ["AgentProfile", "B14RoutingOptions", "DocumentNormalizationError"])
def test_named_exports_match_their_owning_submodule(name):
    import importlib

    import padiem_ai_core

    owning = padiem_ai_core._LAZY_SUBMODULE_EXPORTS[name]
    assert getattr(padiem_ai_core, name) is getattr(importlib.import_module(owning, "padiem_ai_core"), name)
