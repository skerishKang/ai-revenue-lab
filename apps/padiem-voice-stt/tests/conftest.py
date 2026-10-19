"""Make the Worker source importable without the Cloudflare Workers runtime.

``voice_stt_contract`` is deliberately dependency-free and never imports the
``workers`` runtime, so the contract can be exercised on plain CPython. This
conftest only puts the app directory on ``sys.path``.
"""

from __future__ import annotations

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
