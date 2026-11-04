"""#6855 regression: the B14 COM2 installer stages every Core module deploy.sh stages.

2026-11-05 00:19 (reproduced 06:37): deploy.sh had staged
``conversation_bounds`` and ``evidence_blocks`` since #6848, but the COM2
installer still staged only ``pc_work_metrics``. The release crashed at first
boot with ``ModuleNotFoundError: No module named
'padiem_ai_core.conversation_bounds'`` while CI stayed green, because CI built
the bundle from deploy.sh's list and nothing compared the installer's list.
The fix makes the installer read deploy.sh's list at run time; these tests pin
that contract.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[1]
DEPLOY_SH = REPO / "apps" / "korean-ai-platform" / "deploy.sh"
INSTALL_SH = HERE / "b14" / "install.sh"

# The two modules #6848 added to deploy.sh — the exact ones the stale
# installer list dropped.
_MODULES_ADDED_BY_6848 = ("conversation_bounds.py", "evidence_blocks.py")


def deploy_sh_module_list() -> list[str]:
    text = DEPLOY_SH.read_text(encoding="utf-8")
    loops = [m.group(1).split() for m in re.finditer(r"for module in ([^;]+); do", text)]
    if len(loops) != 2 or loops[0] != loops[1] or not loops[0]:
        raise AssertionError(f"deploy.sh module loops unreadable: {loops}")
    return loops[0]


def installer_core_modules() -> list[str]:
    """Run the installer's own list derivation against deploy.sh."""
    import subprocess
    import sys

    text = INSTALL_SH.read_text(encoding="utf-8")
    match = re.search(
        r"CORE_MODULES=\$\(python3 - \"\$DEPLOY_SH\" <<'PY'[^\n]*\n(.*?)\nPY\n\)", text, re.DOTALL
    )
    if match is None:
        raise AssertionError("install.sh lost the deploy.sh-derived CORE_MODULES block")
    completed = subprocess.run(
        [sys.executable, "-c", match.group(1), str(DEPLOY_SH)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(f"installer list derivation failed: {completed.stderr.strip()}")
    return completed.stdout.split()


class B14CoreStagingParity(unittest.TestCase):
    def test_installer_derives_its_list_from_deploy_sh(self) -> None:
        text = INSTALL_SH.read_text(encoding="utf-8")
        self.assertIn(
            'DEPLOY_SH="$SRC_DIR/../../apps/korean-ai-platform/deploy.sh"',
            text,
            "the installer must read deploy.sh, not keep a second hand-written list",
        )

    def test_derived_list_matches_deploy_sh_and_has_the_6848_modules(self) -> None:
        expected = deploy_sh_module_list()
        self.assertEqual(installer_core_modules(), expected)
        for name in _MODULES_ADDED_BY_6848:
            self.assertIn(name, expected)

    def test_installer_no_longer_stages_a_single_hardcoded_module(self) -> None:
        text = INSTALL_SH.read_text(encoding="utf-8")
        self.assertNotIn(
            "staged:pc_work_metrics",
            text,
            "the single-module staging is the drift that broke the 00:19 release",
        )
        self.assertNotRegex(text, r"install .*pc_work_metrics\.py\"")


if __name__ == "__main__":
    unittest.main()
