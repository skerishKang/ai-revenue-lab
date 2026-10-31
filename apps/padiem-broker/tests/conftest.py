from __future__ import annotations

import sys
from pathlib import Path

# The broker service and its adapter modules live beside, not inside, a package.
_BROKER_ROOT = str(Path(__file__).resolve().parents[1])
if _BROKER_ROOT not in sys.path:
    sys.path.insert(0, _BROKER_ROOT)
_TESTS_ROOT = str(Path(__file__).resolve().parent)
if _TESTS_ROOT not in sys.path:
    sys.path.insert(0, _TESTS_ROOT)
_ADAPTER_ROOT = str(Path(__file__).resolve().parents[3] / "packages" / "padiem-control-plane")
if _ADAPTER_ROOT not in sys.path:
    sys.path.insert(0, _ADAPTER_ROOT)
