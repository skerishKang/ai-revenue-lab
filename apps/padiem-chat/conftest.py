"""Cross-platform test entry defaults for the Windows lanes.

Only one thing changes here and only on Windows: pytest's default temporary
root is ``%LOCALAPPDATA%\\Temp\\pytest-of-<user>``, which this fleet's Windows
accounts cannot write (WinError 5), so every ``tmp_path`` test errors before it
runs. Windows uses a short, user/process-specific directory under
``%SystemDrive%\\pt`` (override the parent with ``PADIEM_PYTEST_TEMP_ROOT``).
An explicit ``--basetemp`` wins. Linux and macOS keep pytest's own default.
"""
from __future__ import annotations

import os
from pathlib import Path

# Keep the full default basetemp below 20 characters: the deepest test
# suffix is 239 characters and Windows still enforces the 259-character limit.
def _windows_basetemp() -> Path:
    import getpass
    import hashlib

    root = Path(os.environ.get(
        "PADIEM_PYTEST_TEMP_ROOT",
        os.environ.get("SystemDrive", "C:") + "\\pt",
    ))
    user = os.environ.get("USERDOMAIN", "") + "\\" + getpass.getuser()
    user_key = hashlib.sha256(user.encode("utf-8")).hexdigest()[:4]
    return root / f"c{user_key}{os.getpid():x}"


def pytest_configure(config) -> None:
    """Use a short, user/process-specific root unless --basetemp was given."""
    if os.name != "nt" or config.option.basetemp:
        return
    basetemp = _windows_basetemp()
    basetemp.mkdir(parents=True, exist_ok=True)
    config.option.basetemp = str(basetemp)


# 261106 · the subject→product_user reverse-lookup cache added in
# perf/identity-resolve-subject-261106 is process-wide on purpose (it removes
# one Control-Plane DO RPC per repeated request). Every test therefore starts
# with an empty cache, so suites never observe each other's entries and
# response-shape tests still reach the RPC path.
import pytest


@pytest.fixture(autouse=True)
def _fresh_identity_subject_cache():
    try:
        from app.control_plane_identity_worker import _product_user_cache
    except Exception:
        yield
        return
    _product_user_cache.clear()
    yield
    _product_user_cache.clear()
