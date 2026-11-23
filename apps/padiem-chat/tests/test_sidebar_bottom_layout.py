from __future__ import annotations

import re

# #8060: 시트 원문 읽기는 _support 헬퍼(claw_static·html_tags·css_rules)가
# 담당하고 시험은 파싱 값(id 집합·속성·CSS 선언 값)과 부재·위치 경계를
# 단언한다. 이 모듈은 원문 read를 갖지 않는다.
from _support import claw_static
from _support.html_tags import tags_for_page
from css_rules import declaration, find_rules_with_selector, rules_for_sheet


def _html() -> str:
    return claw_static.sheet("index.html")


def _ui_polish() -> str:
    return claw_static.sheet("padiem-chat-ui-polish.css")


def _six_panel_frame() -> str:
    return claw_static.sheet("shared-six-panel-frame.css")


def _sidebar_bottom_region(html: str) -> str:
    start = html.index('<div class="sidebar-bottom-tools"')
    end = html.index('</div>\n    </aside>', start)
    return html[start:end]


def test_settings_in_sidebar_bottom() -> None:
    html = _html()
    assert 'id="settingsButton"' in html
    assert 'class="sidebar-bottom' in html
    sidebar_start = html.index('<aside class="sidebar"')
    sidebar_end = html.index('</aside>', sidebar_start)
    topbar_start = html.index('<header class="topbar"')
    topbar_end = html.index('</header>', topbar_start)
    sidebar_html = html[sidebar_start:sidebar_end]
    topbar_html = html[topbar_start:topbar_end]
    assert 'id="settingsButton"' in sidebar_html
    assert 'class="sidebar-bottom' in sidebar_html
    # not in topbar as prominent control
    assert 'id="settingsButton"' not in topbar_html
    assert "account-controls" not in topbar_html


def test_login_account_in_sidebar_bottom() -> None:
    html = _html()
    assert 'id="loginButton"' in html
    assert 'id="accountName"' in html
    sidebar_start = html.index('<aside class="sidebar"')
    sidebar_end = html.index('</aside>', sidebar_start)
    topbar_start = html.index('<header class="topbar"')
    topbar_end = html.index('</header>', topbar_start)
    sidebar_html = html[sidebar_start:sidebar_end]
    topbar_html = html[topbar_start:topbar_end]
    assert 'id="loginButton"' in sidebar_html
    assert 'id="accountName"' in sidebar_html
    assert 'class="sidebar-account"' in sidebar_html or 'sidebar-bottom' in sidebar_html
    assert 'id="loginButton"' not in topbar_html


def test_topbar_not_prominent_settings_login() -> None:
    html = _html()
    topbar_start = html.index('<header class="topbar"')
    topbar_end = html.index('</header>', topbar_start)
    topbar_html = html[topbar_start:topbar_end]
    composer_start = html.index('<div class="composer-tools"')
    composer_end = html.index('</div>', composer_start)
    composer_tools_html = html[composer_start:composer_end]
    assert "settingsButton" not in topbar_html
    assert "loginButton" not in topbar_html
    assert "accountName" not in topbar_html
    assert 'class="model-pill' not in topbar_html
    assert 'class="model-pill composer-tier-trigger"' in composer_tools_html


def test_settings_dialog_still_present() -> None:
    ids = {attrs.get("id") for _tag, attrs in tags_for_page("index.html")
           if attrs.get("id")}
    assert {"settingsDialog", "settingsCloseButton", "themePicker", "languagePicker"} <= ids


def test_login_affordance_present_and_reachable() -> None:
    html = _html()
    login_tags = [attrs for _tag, attrs in tags_for_page("index.html")
                  if attrs.get("id") == "loginButton"]
    assert len(login_tags) == 1
    # button is not hidden by default structure (disabled but reachable)
    login_line = [line for line in html.splitlines() if 'id="loginButton"' in line][0]
    assert "<button" in login_line


def test_padiem_home_link_preserved() -> None:
    home_links = [attrs for _tag, attrs in tags_for_page("index.html")
                  if "home-link" in (attrs.get("class") or "") and attrs.get("href")]
    assert home_links, "the Padiem Home link is gone"
    attrs = home_links[0]
    assert attrs.get("href") == "https://padiem.net/"
    assert attrs.get("target") == "_blank"
    assert attrs.get("rel") == "noopener"


def test_visible_brand_remains_padiem_chat() -> None:
    html = _html()
    brand_line = [line for line in html.splitlines() if 'class="brand"' in line][0]
    assert "Padiem Chat" in brand_line
    assert "PADIEM CHAT" not in brand_line


def test_padiem_home_is_final_sidebar_bottom_utility() -> None:
    sidebar_bottom = _sidebar_bottom_region(_html())
    # #7780: 바깥은 새 소식·의견 보내기·사용 안내, 계정 안에 프로필 메뉴가 있고
    # 설정·앱 연결·Padiem Home이 그 메뉴 안에 있다(마지막 유틸은 메뉴 안 Home).
    account_index = sidebar_bottom.index('class="sidebar-account')
    menu_index = sidebar_bottom.index('id="profileMenu"')
    settings_index = sidebar_bottom.index('id="settingsButton"')
    connectors_index = sidebar_bottom.index('id="connectorsNavButton"')
    home_index = sidebar_bottom.index('class="home-link"')
    assert sidebar_bottom.index('id="newsButton"') < sidebar_bottom.index('id="feedbackButton"') < sidebar_bottom.index('id="helpNavLink"') < account_index
    assert account_index < menu_index < settings_index < connectors_index < home_index


def test_glass_home_frame_has_desktop_vertical_breathing_room() -> None:
    ui_polish = _ui_polish()
    frame = _six_panel_frame()
    # One rule lists the three surfaces that carry the conversation; #2594 used
    # to reach the same result by pasting the Chat block again for Claw. The
    # lane position itself belongs to the shared frame, which puts the composer
    # inside the six-panel box, so it is asserted there and its absence here is
    # what keeps the frame from being restyled per product.
    assert '@media (min-width: 921px)' in ui_polish
    assert '.app-shell:is([data-state="home"], [data-state="chat"], [data-state="claw"]) .conversation' in ui_polish
    rules = rules_for_sheet("padiem-chat-ui-polish.css")
    conversation = find_rules_with_selector(
        rules,
        'html[data-theme="padiem-glass"] body .app-shell:is([data-state="home"], [data-state="chat"], [data-state="claw"]) .conversation',
    )
    assert len(conversation) == 1
    assert declaration(conversation[0], "margin-top") == "16px"
    assert declaration(conversation[0], "margin-bottom") == "16px"
    assert '.app-shell:is([data-state="home"], [data-state="chat"], [data-state="claw"]) .composer-wrap' in ui_polish
    wrap = find_rules_with_selector(
        rules,
        'html[data-theme="padiem-glass"] body .app-shell:is([data-state="home"], [data-state="chat"], [data-state="claw"]) .composer-wrap',
    )
    assert len(wrap) == 1
    assert declaration(wrap[0], "padding-bottom") == "16px"
    assert declaration(wrap[0], "padding-top") == "20px"
    # The property has to start a declaration: a note about the lane, a comment
    # between the brace and the property, or `margin-bottom` must not read as the
    # frame's position being restyled here.
    assert not re.search(r"(?:^|[;{}\s])bottom\s*:\s*16px !important", ui_polish), \
        "the composer lane position belongs to the shared frame"
    assert '.app-shell:is([data-state="home"],[data-state="chat"],[data-state="claw"]) .composer-wrap {\n    bottom: 16px !important;' in frame


def test_glass_home_composer_vertical_padding_is_balanced() -> None:
    ui_polish = _ui_polish()
    assert '.app-shell:is([data-state="home"], [data-state="chat"], [data-state="claw"]) .composer {' in ui_polish
    assert '.app-shell:is([data-state="home"], [data-state="chat"], [data-state="claw"]) .composer textarea {' in ui_polish
    rules = rules_for_sheet("padiem-chat-ui-polish.css")
    composer = find_rules_with_selector(
        rules,
        'html[data-theme="padiem-glass"] body .app-shell:is([data-state="home"], [data-state="chat"], [data-state="claw"]) .composer',
    )
    textarea = find_rules_with_selector(
        rules,
        'html[data-theme="padiem-glass"] body .app-shell:is([data-state="home"], [data-state="chat"], [data-state="claw"]) .composer textarea',
    )
    assert len(composer) == 1
    assert len(textarea) == 1
    assert declaration(composer[0], "padding") == "12px 12px 11px"
    assert declaration(textarea[0], "padding") == "9px 9px 7px"


def test_padiem_home_glass_utility_is_one_centered_row() -> None:
    rules = find_rules_with_selector(
        rules_for_sheet("accessibility-polish.css"),
        'html[data-theme="padiem-glass"] body .app-shell .sidebar-bottom .home-link',
    )
    assert len(rules) == 1
    declarations = rules[0].declarations
    assert declarations.get("display") == "flex !important"
    assert declarations.get("align-items") == "center !important"
    assert declarations.get("justify-content") == "flex-start !important"
    assert declarations.get("flex-wrap") == "nowrap !important"
    assert "place-items" not in declarations


def test_padiem_home_glass_label_cannot_wrap() -> None:
    accessibility = rules_for_sheet("accessibility-polish.css")
    marker = find_rules_with_selector(
        accessibility,
        'html[data-theme="padiem-glass"] body .app-shell .sidebar-bottom .home-link .home-link-mark',
    )
    label = find_rules_with_selector(
        accessibility,
        'html[data-theme="padiem-glass"] body .app-shell .sidebar-bottom .home-link [data-locale-key="home-link"]',
    )
    assert len(marker) == 1
    assert len(label) == 1
    assert declaration(marker[0], "line-height") == "1 !important"
    assert declaration(label[0], "line-height") == "1.2 !important"
    assert declaration(label[0], "white-space") == "nowrap !important"
