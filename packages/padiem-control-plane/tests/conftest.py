from __future__ import annotations

from pathlib import Path
import sys


# Deployment adapters live beside, not inside, the side-effect-free foundation package.
# Pytest starts at the repository root, so expose that adapter directory explicitly.
_ADAPTER_ROOT = Path(__file__).parents[1]
_ADAPTER_ROOT_TEXT = str(_ADAPTER_ROOT)
if _ADAPTER_ROOT_TEXT not in sys.path:
    sys.path.insert(0, _ADAPTER_ROOT_TEXT)

# The edge proof verifier reuses the shared output-store lock helper, which
# lives in the core package (not this one): expose it for the same runs.
_CORE_ROOT = Path(__file__).parents[2] / "padiem-ai-core"
_CORE_ROOT_TEXT = str(_CORE_ROOT)
if _CORE_ROOT_TEXT not in sys.path:
    sys.path.insert(0, _CORE_ROOT_TEXT)
