"""#3098 LOCAL3 — sys.path wiring for the cross-area Web↔Desktop E2E harness.

The harness composes real product modules from three areas:

* ``apps/padiem-chat``          — the Claw Web surface (``app`` package);
* ``packages/padiem-control-plane`` — the canonical broker/pairing authority;
* ``apps/korean-ai-code-agent`` — the Local Agent desktop runtime (``kagent``).

No production file is modified and no model/provider call exists on the path
under test; third-party dependencies come from the ``padiem-chat`` dev venv.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_CHAT_ROOT = REPO_ROOT / "apps" / "padiem-chat"
_CONTROL_PLANE_ROOT = REPO_ROOT / "packages" / "padiem-control-plane"
_KAGENT_SRC = REPO_ROOT / "apps" / "korean-ai-code-agent" / "src"
_AI_CORE_ROOT = REPO_ROOT / "packages" / "padiem-ai-core"

for _candidate in (_CHAT_ROOT, _CONTROL_PLANE_ROOT, _KAGENT_SRC, _AI_CORE_ROOT):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))
