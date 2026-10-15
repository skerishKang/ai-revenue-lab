"""One canonical composer behavior for Chat, Claw and B66, with adapters."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / "apps/padiem-chat/static"
B66 = REPO / "reference/business-66-padiem-quote-v1"
CANONICAL = REPO / "packages/padiem-conversation-ui/composer-core.js"


def test_canonical_bytes_are_exactly_same_for_two_release_targets():
    content = CANONICAL.read_bytes()
    assert content
    for path in (STATIC / "shared-conversation-composer.js",
                 B66 / "shared-conversation-composer.js"):
        assert path.read_bytes() == content
    assert b"shouldSubmitOnEnter" in content
    assert b"resizeTextarea" in content


def test_all_three_load_canonical_before_product_adapters():
    chat = (STATIC / "index.html").read_text(encoding="utf-8")
    b66 = (B66 / "index.html").read_text(encoding="utf-8")
    assert chat.index('src="./shared-conversation-composer.js"') < chat.index('src="./app.js"')
    assert b66.index('src="shared-conversation-composer.js"') < b66.index('src="easy-mode.js"')
    assert 'window.PadiemConversationComposer || localHandoffModule' in (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'sharedComposer?.shouldSubmitOnEnter?.(event, compositionGuard)' in (B66 / "easy-mode.js").read_text(encoding="utf-8")


def test_product_server_boundaries_stay_distinct():
    chat = (STATIC / "app.js").read_text(encoding="utf-8")
    b66 = (B66 / "easy-mode.js").read_text(encoding="utf-8")
    assert "submitPrompt(input.value)" in chat
    assert "submitComposer();" in b66
    assert "inputHandler(text)" in b66
