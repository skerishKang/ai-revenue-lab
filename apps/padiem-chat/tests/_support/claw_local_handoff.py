"""#8060 parsed facts for the browser-only claw local handoff module.

The raw static read stays here so the projection contract can execute the real
module and assert parsed facts instead of pinning source spelling.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "static" / "claw-local-handoff.js"

FORBIDDEN_TOKENS = (
    "new WebSocket", "fetch(", "localStorage", "sessionStorage", "atob(", "btoa(",
)


def module_source() -> str:
    return MODULE.read_text(encoding="utf-8")


def module_facts() -> dict:
    source = module_source()
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.MULTILINE)
    return {
        "derive_device_directory_present": "deriveDeviceDirectory" in code,
        "forbidden_tokens": tuple(token for token in FORBIDDEN_TOKENS if token in code),
    }
