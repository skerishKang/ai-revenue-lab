"""#5785 — run one 의원3종 scenario against the real util-menu.js.

The three tools (축사·인사말 / SNS 홍보 / 회의정리·활동집) share one shipped
browser module and the existing PADIEM endpoints, so each group's behavioural
test needs the same host: the real ``static/util-menu.js`` executed against a
fake DOM with a recording fake of ``/api/chat``, ``/api/projects`` and
``/api/projects/{id}/files``.

``_5785_util_harness.js`` is that host (adapted from the #5608 / #5728 harness
contract, not a second product boundary). This module only launches it and
caches the observations, so importing three groups in one pytest session does
not re-run the same scenario.
"""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import shutil
import subprocess

CHAT_ROOT = Path(__file__).resolve().parents[1]
UTIL_MENU_JS = CHAT_ROOT / "static" / "util-menu.js"
HARNESS_JS = CHAT_ROOT / "tests" / "_5785_util_harness.js"

SCENARIOS = ("speech", "sns", "meeting", "shared", "tier", "pcref", "pcref_nopc", "pcref_refusals", "edit", "g5", "g5fail", "tools")


@lru_cache(maxsize=len(SCENARIOS))
def run(scenario: str) -> dict:
    """Return the observations of one scenario (cached per pytest session)."""

    if scenario not in SCENARIOS:
        raise AssertionError(f"unknown util scenario: {scenario!r}")
    node = shutil.which("node")
    assert node, "node runtime is required for the util-menu behavioural harness"
    completed = subprocess.run(
        [node, str(HARNESS_JS), str(UTIL_MENU_JS), scenario],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(CHAT_ROOT),
        check=False,
    )
    assert completed.stdout.strip(), completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result["ok"] is True, result
    assert result["scenario"] == scenario, result
    return result["observation"]
