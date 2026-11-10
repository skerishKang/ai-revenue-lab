"""Claw (kagent) test-suite defaults (#6828 3단계)."""
from __future__ import annotations

import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
for _rel in ("../../src", "../../packages/padiem-control-plane", "../../packages/padiem-ai-core"):
    _p = str((_TESTS_DIR / _rel).resolve())
    if _p not in sys.path:
        sys.path.insert(0, _p)

if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from tests._registry_switch_default import ensure_default_registry_switch

ensure_default_registry_switch()
