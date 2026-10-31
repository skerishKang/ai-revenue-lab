"""#5895: the quote dialog must ship the PC form its launcher promises.

The Node test proves the behaviour on the shipped bytes: opening the quote
dialog shows the b66-quote-pcform section and its "내 PC 엑셀 양식 가져오기"
button attached inside the quote form — never the detached-node no-op that
shipped without them. This Python gate keeps that contract inside the normal
pytest run and pins that the detached after() call cannot come back.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
NODE_TEST = ROOT / "tests" / "test_b66_quote_pc_form_attach.mjs"


def test_quote_pc_form_attach_contract_runs_under_node():
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


def test_the_pc_form_is_appended_with_the_form_never_after_a_detached_node():
    source = (STATIC / "b66-quote-runtime.js").read_text(encoding="utf-8")
    # Element.after() on a parentless node is a per-DOM no-op; the call ran
    # before either node was attached, so the PC form never reached the dialog
    # and the launcher advertised a form the dialog could not show.
    assert "messageLabel.after(pcForm)" not in source
    append_call = source[source.index("form.append("):]
    append_call = append_call[:append_call.index(");")]
    assert "pcForm" in append_call
    assert (
        append_call.index("messageLabel")
        < append_call.index("pcForm")
        < append_call.index("submit")
    )
