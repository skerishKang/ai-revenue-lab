"""Source contract for Chat first-frame appearance during reading mode."""
# #8060: shipped reads live in _support; assertions stay here.
from _support.admin_brand_home_source import (
    app_js, b66_quote_routes, capabilities_js, connector_owner_setup_page, index_html,
    install_html, locale_source, read, settings_js, six_panel_css, theme_js,
)

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
FRAME = six_panel_css()
THEME = theme_js()


def test_owner_visual_authority_outweighs_reading_css() -> None:
    assert "CENTRAL_OWNER_HOME_VISUAL_LOCK_20261015" in FRAME
    assert '.app-shell[data-state="chat"] .conversation.conversation' in FRAME
    assert "rgba(248,250,251,.88)" in FRAME
    assert "rgba(233,238,241,.84)" in FRAME
    assert "opacity: var(--glass-art-opacity)" in FRAME
    assert "filter: var(--glass-art-filter)" in FRAME
    assert "transform: translate3d(0,0,0) scale(1)" in FRAME


def test_reading_semantics_and_existing_layout_still_available() -> None:
    # Reading is still projected from the explicit shell state, and now also for
    # a live Claw thread; the shared frame lanes are untouched by that.
    assert 'if(shell.dataset.state==="chat") return "reading";' in THEME
    assert 'conv.querySelector("#messageList .message")' in THEME
    assert '--padiem-six-panel-width' in FRAME
    assert '.calendar-view, .connectors-view' in FRAME
    assert '.library-view, .automation-view' in FRAME
    assert "history-more" in FRAME
    assert "scrollbar-gutter: stable" in FRAME
