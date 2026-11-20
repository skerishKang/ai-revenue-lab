from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALIGNMENT_CSS = (ROOT / "static/padiem-glass-gutter-alignment.css").read_text(encoding="utf-8")
CHAT_CSS = (ROOT / "static/padiem-cinematic-chat.css").read_text(encoding="utf-8")
INDEX = (ROOT / "static/index.html").read_text(encoding="utf-8")


def test_alignment_layer_loads_after_prior_glass_polish() -> None:
    # #7811 C1: 8개 @import가 index.html <link>로 펼쳐졌다(@import는 부르는
    # 시트보다 앞에 온다). 순서와 부르는 시트 앞 위치를 그대로 확인한다.
    polish = 'href="./padiem-glass-brand-polish.css"'
    alignment = 'href="./padiem-glass-gutter-alignment.css"'
    entry = 'href="./padiem-cinematic-chat.css"'
    assert polish in INDEX
    assert alignment in INDEX
    assert INDEX.index(polish) < INDEX.index(alignment)
    assert INDEX.index(alignment) < INDEX.index(entry)


def test_desktop_conversation_and_composer_share_one_canonical_lane() -> None:
    # Owner requires home and active chat geometry to be identical.
    assert "FIRST SCREEN = ACTIVE CHAT FRAME" in ALIGNMENT_CSS
    assert "--padiem-chat-lane-offset:" not in ALIGNMENT_CSS
    assert "--padiem-chat-lane-width:" not in ALIGNMENT_CSS
    assert ".composer-wrap {\n    left:" not in ALIGNMENT_CSS
    assert ".conversation {\n    width: var(--padiem-chat-lane-width)" not in ALIGNMENT_CSS


def test_internal_message_rail_uses_full_outer_lane_but_keeps_avatar_grid() -> None:
    # #8008 8차: 값만 단정한다. 중요도 캡은 계산값을 바꾸지 않는 구현 detail.
    assert ".message-list {\n  width: 100%;\n  margin-inline: 0;" in ALIGNMENT_CSS
    assert ".assistant-body," in ALIGNMENT_CSS
    assert ".assistant-content {\n  width: 100%;\n  max-width: none;" in ALIGNMENT_CSS
    # Preserve the assistant grid and match its first track to the accepted
    # 32px Glass avatar so the visible avatar-to-content gap stays intentional.
    assert "grid-template-columns: 32px minmax(0, 1fr);" in ALIGNMENT_CSS
    assert "assistant-avatar" not in ALIGNMENT_CSS
    assert "display: none" not in ALIGNMENT_CSS


def test_error_surface_balances_left_and_right_gutters() -> None:
    assert 'width: calc(100% - 32px - var(--padiem-chat-meta-gap));' in ALIGNMENT_CSS
    assert '.assistant-content > .error-box {' in ALIGNMENT_CSS
    assert 'width: calc(100% + var(--padiem-chat-inner-gutter));' in ALIGNMENT_CSS
    # The wide rich response is a distinct selector; the error box must not
    # be widened to cover the right-hand user bubble region.
    selector = '.assistant-content > .rich-response,'
    assert selector not in ALIGNMENT_CSS


def test_mobile_conversation_matches_existing_composer_gutters() -> None:
    assert "@media (max-width: 920px)" in ALIGNMENT_CSS
    assert "--padiem-chat-inner-gutter: clamp(14px, 4vw, 24px)" in ALIGNMENT_CSS
    assert "@media (max-width: 620px)" in ALIGNMENT_CSS
    assert "width: calc(100vw - 28px) !important;" not in ALIGNMENT_CSS
    # #8008: the importance cap is gone; the value stays.
    assert "padding-left: 24px;" in ALIGNMENT_CSS


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
