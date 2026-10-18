"""#4488 stage 1: the shared scroll module is actually wired, not shipped.

B62 conversation-motion and B66 easy-mode must call the shared
container-gap/follow functions; each product keeps its own follow limit and
window/document scroll responsibility. Script order guarantees the shared
module is defined before its consumers run.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CANONICAL = ROOT / "packages/padiem-conversation-ui/scroll-follow.js"


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_canonical_exports_shared_gap_math():
    text = CANONICAL.read_text(encoding="utf-8")
    assert "function remainingToEnd(container)" in text
    assert "NEAR_BOTTOM_PX = 120" in text
    assert "remainingToEnd, isNearBottom, followToBottom" in text


def test_b62_index_loads_shared_scroll_before_composer_and_app():
    html = _read("apps/padiem-chat/static/index.html")
    assert '<script src="./shared-conversation-scroll.js"></script>' in html
    assert html.index("./shared-conversation-scroll.js") < html.index("./app.js")


def test_b62_conversation_motion_calls_shared_gap_first():
    motion = _read("apps/padiem-chat/static/conversation-motion.js")
    assert "window.PadiemConversationScroll || window.SharedConversationScroll" in motion
    assert 'typeof shared.remainingToEnd === "function"' in motion
    # Shared call precedes the product's legacy fallback math.
    assert motion.index("return shared.remainingToEnd(conv);") < motion.index(
        "return conv.scrollHeight - conv.scrollTop - conv.clientHeight;"
    )


def test_b66_index_loads_shared_scroll_before_easy_mode():
    html = _read("reference/business-66-padiem-quote-v1/index.html")
    assert '<script src="shared-conversation-scroll.js" defer></script>' in html
    assert html.index("shared-conversation-scroll.js") < html.index("easy-mode.js")


def test_b66_easy_mode_calls_shared_follow_first():
    easy = _read("reference/business-66-padiem-quote-v1/easy-mode.js")
    # B66 product files must stay product-neutral: only the Shared alias.
    assert "window.SharedConversationScroll" in easy
    assert "PadiemConversationScroll" not in easy
    assert "Padiem" not in easy
    # Shared calls precede the preserved legacy branches.
    assert easy.index("sharedScroll.isNearBottom(conversation)") < easy.index(
        "conversation.scrollHeight - conversation.scrollTop - conversation.clientHeight < 120"
    )
    assert easy.index("sharedScroll.followToBottom(conversation)") < easy.index(
        "conversation.scrollTop = conversation.scrollHeight;"
    )
    # Measurement stays BEFORE append, follow AFTER append (old order kept).
    assert easy.index("const wasNearBottom") < easy.index("messageList.appendChild(article);") < easy.index(
        "sharedScroll.followToBottom(conversation)"
    )
