"""#4647: merge existing meeting workbench into current B62 sidebar without regressions."""
from __future__ import annotations

import re

from _support.latest_sidebar import (
    css_facts,
    css_media_view,
    function_param_defaults,
    handler_view,
    index_view,
    js_view,
)

from app import worker_config


def _desktop_rules():
    return css_media_view("sidebar-history-scroll.css")["(min-width: 921px)"]


def _declarations_for(fragment: str) -> dict[str, str]:
    rules = [
        rule for rule in _desktop_rules()
        if any(fragment in selector for selector in rule.selectors)
    ]
    assert rules, fragment
    return dict(rules[0].declarations)


def test_owner_exact_menu_order_reuses_existing_chat_claw_search_buttons():
    """#7365 대표 결정(2026-11-10): 대화(새 채팅·Claw) → 도구·일정(유틸·캘린더·
    자동화·라이브러리) → 내 자료(프로젝트·최근 대화) → 아래 계정.
    #7780: 아래 계정은 바깥 새 소식·의견 보내기·사용 안내 뒤에 프로필 메뉴
    (설정·앱 연결·Padiem Home)가 계정 안에 있다. The meeting row left the
    sidebar: its trigger lives in the Util tab's meeting tool screen now."""
    page = index_view()
    ids = ("newChatButton", "sidebarSearchButton", "clawNavButton", "utilNavButton",
           "calendarNavButton", "automationNavButton", "filesNavButton",
           "newsButton", "feedbackButton", "helpNavLink", "settingsButton", "connectorsNavButton")
    positions = [page["position"][key] for key in ids]
    assert positions == sorted(positions)
    assert page["position"]["home-link"] > page["position"]["connectorsNavButton"]
    for id_ in ids:
        assert page["id_counts"][id_] == 1
    # The meeting row left the sidebar; its trigger is parked once in the Util
    # view's capture host (same element, same behavior).
    assert page["id_counts"]["meetingNavButton"] == 1
    assert page["position"]["meetingNavButton"] > page["position"]["utilAppRoot"]
    assert page["class_counts"]["sidebar-chat-claw-group"] == 1
    assert page["id_counts"]["sidebarCollapseButton"] == 1
    assert page["id_counts"]["historyToggleButton"] == 1


def test_meeting_workspace_is_inside_shared_main_not_outside_app_shell():
    # #4813 draft misplaced section AFTER </main> / </div> and would not
    # match .app-shell[data-state=meeting] selectors. Prevent reintroduction.
    page = index_view()
    assert page["in_main_panel"]["meetingView"] is True
    assert page["id_counts"]["meetingNavButton"] == 1
    for target in ("meetingTranscript", "meetingStart", "meetingStop",
                   "meetingDownloadAudio", "meetingDownloadText",
                   "meetingSaveAudioDrive", "meetingSaveTextDrive", "meetingDraftInClaw"):
        assert page["id_counts"][target] == 1
    # The view must show only on its own page. That condition moved into the
    # page contract table (the meeting entry names its panel) and one shared
    # loop hides every panel the current page does not own.
    nav = js_view("chat-nav-module.js")
    assert ("panelId", "meetingView") in nav["property_pairs"]
    # R5 A10: the shared panel-hide loop and the meeting-open listener moved to
    # chat-nav-module.js; app.js keeps the wire calls.
    assert nav["assignments_full"].get("panel.hidden") == "entry.panelId !== page.panelId"
    assert "padiem:meeting-open" in nav["string_literals"]
    app = js_view("app.js")
    assert any("wireNavEntryListeners" in callee for callee, _args in app["call_args"])
    sheet_css = css_facts("meeting-capture.css")
    assert any('data-state="meeting"' in selector for selector in sheet_css["selectors"])
    assert ("overflow-y", "auto") in sheet_css["declarations"]


def test_meeting_interception_does_not_fork_the_shared_composer_submit():
    # #3531: the shared composer handler must stay a plain general-chat submit
    # with no shell-state branch. The meeting module owns the interception with
    # its own capture-phase listener.
    handler = handler_view("chat-conversation-module.js", 'form.addEventListener("submit"')
    assert ("submitPrompt", "input.value") in handler["call_args"]
    assert "dataset.state" not in handler["member_chains"]
    assert "PadiemMeetingCapture" not in handler["identifiers"]
    capture = js_view("meeting-capture.js")
    assert "interceptComposerSubmit" in capture["calls"]
    assert any(
        callee.endswith("getElementById") and '"composerForm"' in args
        for callee, args in capture["call_args"]
    )
    assert any(callee.endswith("stopImmediatePropagation") for callee in capture["calls"])
    # The shell-state and intent gates still exist, just inside the meeting module.
    assert capture["optional_state_gate"] is True
    assert any(
        "isMeetingIntent" in callee and args == "value"
        for callee, args in capture["call_args"]
    )


def test_single_divider_only_between_project_and_history_preserves_scroll():
    sheet_css = css_facts("sidebar-history-scroll.css")
    assert any("#historySection:not([hidden])" in s for s in sheet_css["selectors"])
    assert ("border-top", "1px solid rgba(230, 240, 250, .20)") in sheet_css["declarations"]
    assert any("#historyList" in s for s in sheet_css["selectors"])
    assert ("overflow-y", "auto") in sheet_css["declarations"]
    assert any(".sidebar-bottom" in s for s in sheet_css["selectors"])
    assert ("margin-top", "auto") in sheet_css["declarations"]
    assert ("max-height", "min(44dvh, 360px)") in sheet_css["declarations"]


def test_desktop_history_section_can_never_spill_under_the_pinned_account_stack():
    # #4905 regression: the owner-ordered menus plus the pinned account/home
    # stack exceeded the viewport, so #historySection collapsed and its rows
    # were painted underneath .sidebar-bottom. The desktop parsed block proves
    # the section hides overflow, keeps a real height floor, and the sidebar
    # itself scrolls when the pinned layout cannot fit.
    history = _declarations_for("#historySection:not([hidden])")
    assert history.get("overflow") == "hidden"
    assert history.get("overflow") != "visible"
    floor = re.search(r"min-height:\s*(\d+)px;", "; ".join(
        f"{prop}: {value};" for prop, value in history.items()
    ))
    assert floor and int(floor.group(1)) >= 120, history
    sidebar_rules = [
        rule for rule in _desktop_rules()
        if "html body .app-shell .sidebar" in rule.selectors
    ]
    assert sidebar_rules
    assert dict(sidebar_rules[0].declarations).get("overflow-y") == "auto !important"
    assert any(".sidebar-bottom" in s for r in _desktop_rules() for s in r.selectors)
    assert ("margin-top", "auto") in {
        prop_value for rule in _desktop_rules() for prop_value in rule.declarations.items()
    }


def test_history_list_remains_the_single_desktop_conversation_scrollport():
    declarations = _declarations_for("#historyList")
    assert declarations.get("overflow-y") == "auto"
    assert declarations.get("min-height") == "0"


def test_drive_is_fail_closed_without_registered_host_port():
    from app import meeting_drive_upload_routes as routes

    assert routes.MEETING_DRIVE_SESSION_PATH == "/api/claw/meeting/drive-upload-session"
    assert function_param_defaults("app_factory")[("create_app", "meeting_drive_upload_session_port")] == "None"
    assert "https://www.googleapis.com" in worker_config.CONTENT_SECURITY_POLICY
    page = index_view()
    assert page["script_srcs"].count("./meeting-drive-upload.js") == 1
    assert page["script_srcs"].count("./meeting-capture.js") == 1
