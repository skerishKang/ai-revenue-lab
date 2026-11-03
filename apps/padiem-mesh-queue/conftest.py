"""Test entry for the COM2 queue contract lane on a Windows workstation.

Two workstation-only differences, both no-ops on the Linux CI job:

* Import paths. The queue suite composes the real Chat app and the real KAgent
  drive reporter, and CI gives them through ``PYTHONPATH`` (see
  ``.github/workflows/com2-mesh-queue-contract-tests.yml``). A lane that runs
  ``python -m pytest`` in this directory has no such variable, so the same five
  roots are prepended here, in the same order.
* Temporary root. pytest's default Windows temp root is not writable on this
  fleet (WinError 5), which errors every ``tmp_path`` test before it runs; on
  Windows the session uses a user/process-specific child of ``%SystemDrive%\\pt``.
  ``PADIEM_PYTEST_TEMP_ROOT`` overrides that parent; ``--basetemp`` wins.
  Linux keeps pytest's own default, so CI behaviour is unchanged.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
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
    return root / f"q{user_key}{os.getpid():x}"

#: Exactly the value the CI workflow's ``env.PYTHONPATH`` carries.
_IMPORT_ROOTS = (
    _REPO_ROOT / "apps" / "padiem-chat",
    _REPO_ROOT / "packages" / "padiem-ai-core",
    _REPO_ROOT / "packages" / "padiem-control-plane",
    _REPO_ROOT / "apps" / "korean-ai-code-agent" / "src",
    _REPO_ROOT / "apps" / "padiem-ai-engine" / "clients" / "python",
)
if os.name == "nt":
    for _root in reversed(_IMPORT_ROOTS):
        _path = str(_root)
        if _path not in sys.path:
            sys.path.insert(0, _path)


def pytest_configure(config) -> None:
    """Use a short, user/process-specific root unless --basetemp was given."""
    if os.name != "nt" or config.option.basetemp:
        return
    basetemp = _windows_basetemp()
    basetemp.mkdir(parents=True, exist_ok=True)
    config.option.basetemp = str(basetemp)
