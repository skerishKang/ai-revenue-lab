"""#5573 PR-3: the pairing card is the existing computer card's own flow.

The browser harness runs the real module against a scripted fetch, so the flow
the owner sees is executed rather than described: issue a code, see the linked
PC with its approved folder, revoke a folder or the link, and read a server that
is not ready as "not ready" instead of as an empty success.
"""
from __future__ import annotations
import re
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
STATIC = HERE.parents[0] / "static"
MODULE = STATIC / "pc-pairing-card.js"
HARNESS = HERE / "pc_pairing_card_harness.js"
INDEX = STATIC / "index.html"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is required for the browser harness")


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([NODE, *args], capture_output=True, text=True, timeout=120,
                          encoding="utf-8", errors="replace")


def test_the_module_is_loaded_by_the_page_that_hosts_the_computer_card():
    source = MODULE.read_text(encoding="utf-8")
    html = INDEX.read_text(encoding="utf-8")
    assert "connectorComputerCard" in source
    assert './pc-pairing-card.js' in html
    # The card is one host: the section is created by the module, so the shipped
    # markup gains a script and nothing else.
    assert 'id="pcPairingSection"' not in html
    assert "innerHTML" not in source


def test_only_the_windows_install_sentence_is_offered():
    source = MODULE.read_text(encoding="utf-8")
    # One install sentence per locale, and both name Windows and nothing else. The
    # unsigned-download warning names it once more per locale, because the screen it
    # describes is Windows'.
    assert len(re.findall(r'Windows', source)) == 4
    # The code-typing affordance is gone from the card: nothing on it asks for
    # or shows a code, and the file arrives under one fixed name.
    assert "installHint" not in source
    assert 'INSTALL_FILENAME = "padiem-pc-connect.ps1"' in source
    assert 'INSTALL_EXE_FILENAME = "padiem-pc-connect.exe"' in source
    for other in ("macOS", "Mac 앱", "Linux", "android", "iOS"):
        assert other not in source, other


def test_the_pairing_surface_is_the_only_thing_this_card_calls():
    source = MODULE.read_text(encoding="utf-8")
    urls = set(re.findall(r'"(/[a-z0-9/_.-]+)"', source, re.IGNORECASE))
    assert urls == {"/api/pc/pairings", "/api/pc/pairings/install-file",
                    "/api/pc/pairings/install-exe", "/label"}
    # The code is a possession proof for the PC, never a URL token that lands in
    # history, referrer or a shared link.
    assert "code=" not in source
    # #5573's own surface: the paired-PC card answers for every account that has
    # a link, including the one where #5951 hides the old desktop handoff. It
    # reads nothing from that projection, so hiding the desktop card can never
    # hide "connect this PC" with it.
    assert "local-access" not in source
    html = INDEX.read_text(encoding="utf-8")
    handoff_open = html.index('id="clawLocalHandoff"')
    handoff_close = html.index("</section>", handoff_open)
    card_host = html.index('id="connectorComputerCard"')
    assert not handoff_open < card_host < handoff_close


def test_the_harness_flow_passes_every_check():
    result = _run(str(HARNESS), str(MODULE))
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "PC_PAIRING_CARD=PASS" in output
    # 32 checks: the 2026-10-29 redesign's contract — one offer (one big connect
    # button), one run guide naming the three presses, a self-updating wait that
    # turns into 연결됨 ✓ by itself, a two-PC list whose row menu renames, pauses,
    # resumes and disconnects, and the mesh identity and folder-approval UI that
    # stay off the screen while the server features stay in the module.
    assert output.count("PC_PAIRING_CARD_CHECK") == 32
    assert "FAIL" not in output


def test_the_harness_itself_fails_when_the_card_lies():
    """Differential proof: the same harness refuses a card that reports success
    while the server says it is not ready. Edited copy, not shipped code."""
    broken = MODULE.read_text(encoding="utf-8").replace(
        'notReady: "PC 연결 기능은 아직 준비 중입니다. 잠시 후 다시 시도해 주세요.",',
        'notReady: "PC 연결됨",',
    )
    assert broken != MODULE.read_text(encoding="utf-8")
    temporary = HERE / "_pc_pairing_card_broken.js"
    temporary.write_text(broken, encoding="utf-8")
    try:
        result = _run(str(HARNESS), str(temporary))
    finally:
        temporary.unlink(missing_ok=True)
    assert result.returncode != 0
    assert "PC_PAIRING_CARD=FAIL" in result.stdout + result.stderr
    assert "an unapplied migration reads as 준비 중 FAIL" in result.stdout
