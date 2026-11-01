"""#pending-poll-stop 261102: a refused submit must not start result checks.

The Node test proves the transport marker and the gone bookkeeping inside the
recovery module. This gate keeps the small app wiring that turns both into
behavior: the requestAnswer catch skips recovery when the POST itself was
rejected, and a run the server answered 404 for is dropped from any further
checking on the client side too, so a retry over the same handle shows its
own failure instead of reading a gone run again.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
NODE_TEST = ROOT / "tests" / "test_pending_poll_stop_261102.mjs"


def test_pending_poll_stop_contract_runs_under_node():
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


def test_app_skips_the_result_check_when_the_submit_was_refused():
    transport = (STATIC / "chat-transport.js").read_text(encoding="utf-8")
    app = (STATIC / "app.js").read_text(encoding="utf-8")

    # The transport marks HTTP-level refusals of the submit call itself, and
    # only when an HTTP status was passed (a cut stream has none).
    assert "error.submissionRejected = true" in transport
    assert "Number.isInteger(status) && status >= 400" in transport

    # The catch that starts pending-result recovery refuses that error kind.
    assert app.count("!error?.submissionRejected") == 1
    guard_at = app.index("!error?.submissionRejected")
    guard_line = app[app.rindex("if (", 0, guard_at):guard_at]
    assert "contextSnapshot?.pcRunId" in guard_line
    assert "!error?.terminalRecord" in guard_line


def test_app_drops_a_gone_run_from_any_further_checking():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    recovery = (STATIC / "chat-pc-result-recovery.js").read_text(encoding="utf-8")

    # The recovery module answers a repeat read of a gone run without any GET.
    assert "var gone = new Set();" in recovery
    assert 'if (gone.has(runId)) return {kind: "rejected", status: 404, gone: true};' in recovery
    assert "if (status === 404) gone.add(runId);" in recovery

    # And the app forgets the run on its side too, in both wait paths, so a
    # retry over the same handle goes straight to the existing failure copy.
    assert app.count("if (first.gone === true) resolvedPcRuns.add(runId);") == 1
    assert app.count("if (result.gone === true) resolvedPcRuns.add(runId);") == 1


def test_cut_stream_recovery_stays_allowed():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    # #5895 deferral above the terminal-refusal branch is untouched.
    deferral = app.index("chatTransport.isStreamLoss?.(data)")
    terminal = app.index("// An explicit refusal is terminal even before the first token.")
    assert deferral < terminal
    assert app.count("isStreamLoss?.(data)") == 1
