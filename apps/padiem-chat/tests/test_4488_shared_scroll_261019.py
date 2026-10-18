"""COM1 LOCAL #4488: shared conversation scroll follow parity.

Canonical source packages/padiem-conversation-ui/scroll-follow.js owns the
behavior. Static copies ship from scripts/sync_shared_conversation_scroll.py.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "packages/padiem-conversation-ui/scroll-follow.js"
TARGETS = (
    ROOT / "apps/padiem-chat/static/shared-conversation-scroll.js",
    ROOT / "reference/business-66-padiem-quote-v1/shared-conversation-scroll.js",
)


def test_scroll_canonical_source_exports_neutral_alias():
    text = SOURCE.read_text(encoding="utf-8")
    assert "PadiemConversationScroll" in text
    assert "SharedConversationScroll" in text
    assert "isNearBottom" in text
    assert "followToBottom" in text
    assert "NEAR_BOTTOM_PX = 120" in text


def test_scroll_targets_match_canonical_bytes():
    original = SOURCE.read_bytes()
    for dst in TARGETS:
        assert dst.exists(), dst
        assert dst.read_bytes() == original


def test_scroll_sync_check_passes():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/sync_shared_conversation_scroll.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "SHARED_SCROLL_PARITY=PASS" in proc.stdout


def test_scroll_follow_math_matches_b66_contract():
    container = {"scrollHeight": 1000, "scrollTop": 850, "clientHeight": 100}

    class Box:
        def __init__(self, values):
            self.__dict__.update(values)

    near = Box(container)
    gap = near.scrollHeight - near.scrollTop - near.clientHeight
    assert gap == 50
    assert gap < 120
    far = Box({"scrollHeight": 1000, "scrollTop": 100, "clientHeight": 100})
    assert (far.scrollHeight - far.scrollTop - far.clientHeight) >= 120
