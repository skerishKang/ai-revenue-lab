from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")


def _sidebar_markup() -> str:
    return INDEX.split('<aside class="sidebar"', 1)[1].split("</aside>", 1)[0]


def _sidebar_bottom_markup() -> str:
    sidebar = _sidebar_markup()
    return sidebar.split('<div class="sidebar-bottom"', 1)[1].split("</div>", 1)[0]


def test_sidebar_no_longer_duplicates_prompt_discovery() -> None:
    sidebar = _sidebar_markup()
    assert 'id="recentTitle"' not in sidebar
    assert "추천 질문" not in sidebar
    assert "data-prompt=" not in sidebar
    assert "AI를 쉽게 설명해줘" not in sidebar
    assert "제주도 여행 계획" not in sidebar
    assert "저녁 메뉴 추천" not in sidebar


def test_empty_state_remains_the_prompt_discovery_surface() -> None:
    assert '<div class="starter-grid" aria-label="추천 질문">' in INDEX
    assert 'class="starter" data-prompt="AI를 처음 쓰는 사람에게 AI가 뭔지 아주 쉽게 설명해줘"' in INDEX
    assert 'class="starter" data-prompt="이번 주말 가족과 집 근처에서 할 만한 일을 추천해줘"' in INDEX
    assert 'class="starter" id="documentStarterButton"' in INDEX
    assert 'class="starter" id="webSearchStarterButton"' in INDEX
    assert 'document.querySelectorAll("[data-prompt]")' in APP


def test_sidebar_primary_order_is_navigation_history_then_utilities() -> None:
    sidebar = _sidebar_markup()
    new_chat = sidebar.index('id="newChatButton"')
    nav = sidebar.index('class="side-nav"')
    projects = sidebar.index('id="projectsSection"')
    history = sidebar.index('id="historySection"')
    outputs = sidebar.index('id="outputsSection"')
    footer = sidebar.index('class="sidebar-footer"')
    bottom = sidebar.index('class="sidebar-bottom"')
    assert new_chat < nav < projects < history < outputs < footer < bottom


def test_padiem_home_settings_and_account_share_bottom_utility_group() -> None:
    sidebar = _sidebar_markup()
    bottom = _sidebar_bottom_markup()
    assert sidebar.count('class="home-link"') == 1
    assert 'href="https://padiem.net/"' in bottom
    assert 'data-locale-key="home-link"' in bottom
    assert 'id="settingsButton"' in bottom
    assert 'class="sidebar-account account-controls"' in bottom
    assert bottom.index('class="home-link"') < bottom.index('id="settingsButton"') < bottom.index('class="sidebar-account account-controls"')


def test_sidebar_ia_change_does_not_add_runtime_capability_authority() -> None:
    sidebar = _sidebar_markup()
    for forbidden in ("/api/", "fetch(", "localStorage", "sessionStorage", "document.cookie"):
        assert forbidden not in sidebar
