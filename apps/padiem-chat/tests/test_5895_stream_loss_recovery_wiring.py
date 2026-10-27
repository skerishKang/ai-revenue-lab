"""#5895: a long turn whose stream is cut must recover, not read as a failure.

The Node test proves the two halves join: only a stream that stopped without a
verified result counts as a stream loss, and such a turn is read back from the
stored run result with GETs only. This Python gate keeps that contract inside the
normal pytest run and pins the small app wiring that turns the classification
into the existing pending-result recovery instead of a rendered failure.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
NODE_TEST = ROOT / "tests" / "test_5895_stream_loss_recovery.mjs"


def test_stream_loss_recovery_contract_runs_under_node():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed in this runner")
    completed = subprocess.run(
        [node, "--test", str(NODE_TEST)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_app_hands_a_cut_pc_stream_to_the_stored_result_recovery():
    transport = (STATIC / "chat-transport.js").read_text(encoding="utf-8")
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    locale = (STATIC / "locale.js").read_text(encoding="utf-8")

    # The classifier exists, names only the two stream-loss codes and is exported.
    assert 'new Set(["invalid_engine_stream", "invalid_engine_stream_event"])' in transport
    assert "isStreamLoss," in transport

    # The error-frame path defers to recovery before it can mark anything
    # terminal, and the deferral sits above the "explicit refusal" branch.
    deferral = app.index("chatTransport.isStreamLoss?.(data)")
    terminal = app.index("// An explicit refusal is terminal even before the first token.")
    assert deferral < terminal
    assert app.count("isStreamLoss?.(data)") == 1
    assert "MESSAGE_LIFECYCLE.STREAMING" in app[deferral:terminal]

    # The screen says what is true while the run is unfinished, in both
    # languages, and no new retry instruction is added.
    assert '"pc-processing-note"' in locale
    assert locale.count('"pc-processing-note"') == 2
    assert "완료되면 이 대화에 결과가 표시됩니다." in locale
    assert "the answer will appear in this conversation when it completes." in locale
