from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALIGNMENT_CSS = (ROOT / "static/padiem-glass-gutter-alignment.css").read_text(encoding="utf-8")
CHAT_CSS = (ROOT / "static/padiem-cinematic-chat.css").read_text(encoding="utf-8")


def test_alignment_layer_loads_after_prior_glass_polish() -> None:
    polish = "@import url('./padiem-glass-brand-polish.css');"
    alignment = "@import url('./padiem-glass-gutter-alignment.css');"
    assert polish in CHAT_CSS
    assert alignment in CHAT_CSS
    assert CHAT_CSS.index(polish) < CHAT_CSS.index(alignment)


def test_desktop_conversation_and_composer_share_one_canonical_lane() -> None:
    assert "--padiem-chat-lane-offset:" in ALIGNMENT_CSS
    assert "--padiem-chat-lane-width:" in ALIGNMENT_CSS
    assert ".conversation {\n    width: var(--padiem-chat-lane-width) !important;" in ALIGNMENT_CSS
    assert ".composer-wrap {\n    left: calc(var(--workspace-rail, 252px) + var(--padiem-chat-lane-offset)) !important;\n    width: var(--padiem-chat-lane-width) !important;" in ALIGNMENT_CSS
    assert "@media (min-width: 1440px)" in ALIGNMENT_CSS
    assert "@media (min-width: 1024px) and (max-width: 1439px)" in ALIGNMENT_CSS


def test_internal_message_rail_uses_full_outer_lane_but_keeps_avatar_grid() -> None:
    assert ".message-list {\n  width: 100% !important;\n  margin-inline: 0 !important;" in ALIGNMENT_CSS
    assert ".assistant-body," in ALIGNMENT_CSS
    assert ".assistant-content {\n  width: 100% !important;\n  max-width: none !important;" in ALIGNMENT_CSS
    # Preserve the assistant grid and match its first track to the accepted
    # 32px Glass avatar so the visible avatar-to-content gap stays intentional.
    assert "grid-template-columns: 32px minmax(0, 1fr) !important;" in ALIGNMENT_CSS
    assert "assistant-avatar" not in ALIGNMENT_CSS
    assert "display: none" not in ALIGNMENT_CSS


def test_error_surface_can_expand_to_shared_grid() -> None:
    assert ".error-box {\n  width: 100% !important;\n  max-width: none !important;" in ALIGNMENT_CSS


def test_mobile_conversation_matches_existing_composer_gutters() -> None:
    assert "@media (max-width: 920px)" in ALIGNMENT_CSS
    assert "width: calc(100vw - 28px) !important;" in ALIGNMENT_CSS
    assert "@media (max-width: 620px)" in ALIGNMENT_CSS
    # The narrow breakpoint may tighten bubble padding, but it must not change
    # the 14px outer conversation/composer gutter established at <=920px.
    assert "width: calc(100vw - 20px) !important;" not in ALIGNMENT_CSS
    assert "padding-left: 24px !important;" in ALIGNMENT_CSS


def test_alignment_is_layout_only_and_glass_scoped() -> None:
    assert 'html[data-theme="padiem-glass"]' in ALIGNMENT_CSS
    for forbidden in (
        "fetch(",
        "provider",
        "quota",
        "Authorization",
        "localStorage",
        "sessionStorage",
        "overflow-x: hidden",
    ):
        assert forbidden not in ALIGNMENT_CSS
