"""#4643 the browser voice engine contract runs in the Chat pytest lane.

The live transcription engine and the shared input adapter are plain browser
JavaScript, so their contract lives in Node test files. The Chat pytest lane
is the one that always runs for a Chat change, so this module executes those
Node suites and fails closed when they fail.

Without this, a regression in the ported live engine (the turn boundary, the
rotation handoff, the tail flush or the credential boundary) would only be
found by a local run.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE_SUITES = (
    "tests/test_voice_live_transcript_4643.cjs",
    "tests/test_voice_stt_wiring_fallback_4643.cjs",
    "tests/test_voice_stt_input_adapter_4643.cjs",
)


def _node() -> str | None:
    """The Node executable, or None when this runner has none."""
    return shutil.which("node")


@pytest.mark.parametrize("suite", NODE_SUITES)
def test_browser_voice_engine_suite_passes(suite: str) -> None:
    node = _node()
    if node is None:
        pytest.skip("node is not installed on this runner")
    path = ROOT / suite
    assert path.exists(), f"missing browser voice suite: {suite}"
    result = subprocess.run(
        [node, "--test", str(path)],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(ROOT),
    )
    assert result.returncode == 0, (
        f"{suite} failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
