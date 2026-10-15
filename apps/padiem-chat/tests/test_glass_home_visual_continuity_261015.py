"""Source contract for Chat first-frame appearance during reading mode."""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
FRAME = (STATIC / "shared-six-panel-frame.css").read_text(encoding="utf-8")
THEME = (STATIC / "theme.js").read_text(encoding="utf-8")


def test_owner_visual_authority_outweighs_reading_css() -> None:
    assert "CENTRAL_OWNER_HOME_VISUAL_LOCK_20261015" in FRAME
    assert '.app-shell[data-state="chat"] .conversation.conversation' in FRAME
    assert "rgba(248,250,251,.88)" in FRAME
    assert "rgba(233,238,241,.84)" in FRAME
    assert "opacity: var(--glass-art-opacity) !important" in FRAME
    assert "filter: var(--glass-art-filter) !important" in FRAME
    assert "transform: translate3d(0,0,0) scale(1) !important" in FRAME


def test_reading_semantics_and_existing_layout_still_available() -> None:
    assert 'shell.dataset.state==="chat" ? "reading" : "home"' in THEME
    assert '--padiem-six-panel-width' in FRAME
    assert '.calendar-view, .connectors-view' in FRAME
    assert '.library-view, .automation-view' in FRAME
    assert "history-more" in FRAME
    assert "scrollbar-gutter: stable" in FRAME
