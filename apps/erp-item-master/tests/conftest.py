"""Make the app and the shared Core package importable from the test tree.

The app is run from its own directory in production. This keeps the test
command identical from the repository root and from the app directory, so a
reviewer never has to guess how to run the focused regression.
"""

from __future__ import annotations

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parents[1]
CORE_ROOT = REPO_ROOT / "packages" / "padiem-ai-core"

for path in (str(APP_ROOT), str(CORE_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)
