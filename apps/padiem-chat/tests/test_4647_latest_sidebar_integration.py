"""#4647: merge existing meeting workbench into current B62 sidebar without regressions."""
from pathlib import Path
import re

STATIC=Path(__file__).resolve().parents[1]/"static"
INDEX=(STATIC/"index.html").read_text(encoding="utf-8")
APP=(STATIC/"app.js").read_text(encoding="utf-8")
SCROLL=(STATIC/"sidebar-history-scroll.css").read_text(encoding="utf-8")
CSS=(STATIC/"meeting-capture.css").read_text(encoding="utf-8")
CAPTURE=(STATIC/"meeting-capture.js").read_text(encoding="utf-8")


def test_owner_exact_menu_order_reuses_existing_chat_claw_search_buttons():
    ids=("newChatButton", "sidebarSearchButton", "clawNavButton", "meetingNavButton",
         "automationNavButton", "filesNavButton", "calendarNavButton", "connectorsNavButton")
    positions=[INDEX.index(f'id="{key}"') for key in ids]
    assert positions==sorted(positions)
    for id_ in ids:
        assert INDEX.count(f'id="{id_}"')==1
    assert INDEX.count('class="sidebar-chat-claw-group"') == 1
    assert 'id="sidebarCollapseButton"' in INDEX
    assert 'id="historyToggleButton"' in INDEX


def test_meeting_workspace_is_inside_shared_main_not_outside_app_shell():
    # #4813 draft misplaced section AFTER </main> / </div> and would not
    # match .app-shell[data-state=meeting] selectors. Prevent reintroduction.
    view=INDEX.index('id="meetingView"')
    main_open=INDEX.index('<main class="main-panel">')
    main_close=INDEX.index('    </main>')
    assert main_open < view < main_close
    assert 'id="meetingNavButton"' in INDEX
    for target in ("meetingTranscript","meetingStart","meetingStop",
                   "meetingDownloadAudio","meetingDownloadText",
                   "meetingSaveAudioDrive","meetingSaveTextDrive","meetingDraftInClaw"):
        assert INDEX.count(f'id="{target}"')==1
    assert 'state !== "meeting"' in APP
    assert 'padiem:meeting-open' in APP
    assert 'data-state="meeting"' in CSS
    assert 'overflow-y: auto;' in CSS


def test_meeting_interception_does_not_fork_the_shared_composer_submit():
    # #3531: the shared composer handler must stay a plain general-chat submit
    # with no shell-state branch. #4905 originally inserted
    # `shell.dataset.state === "claw" && ...tryOpenFromClaw(...)` straight into
    # that handler, which broke test_3531_claw_general_routing. The meeting
    # module now owns the interception with its own capture-phase listener.
    handler = APP[APP.index('form.addEventListener("submit"'):]
    handler = handler[:handler.index("\n  });")]
    assert "submitPrompt(input.value)" in handler
    assert "dataset.state" not in handler
    assert "PadiemMeetingCapture" not in handler
    assert "interceptComposerSubmit();" in CAPTURE
    assert 'doc.getElementById("composerForm")' in CAPTURE
    assert "stopImmediatePropagation()" in CAPTURE
    # The shell-state and intent gates still exist, just inside the meeting module.
    assert 'shell?.dataset.state !== "claw"' in CAPTURE
    assert "isMeetingIntent(value)" in CAPTURE


def test_single_divider_only_between_project_and_history_preserves_scroll():
    assert '#historySection:not([hidden])' in SCROLL
    assert "border-top: 1px solid rgba(230, 240, 250, .20)" in SCROLL
    assert '#historyList' in SCROLL
    assert 'overflow-y: auto;' in SCROLL
    assert '.sidebar-bottom' in SCROLL
    assert 'margin-top: auto;' in SCROLL
    assert 'max-height: min(44dvh, 360px);' in SCROLL


def test_desktop_history_section_can_never_spill_under_the_pinned_account_stack():
    # #4905 regression, reproduced on real Chromium at 1280x800: the owner-ordered
    # menus plus the pinned account/home stack exceeded the viewport, so
    # #historySection (flex: 1 1 0; min-height: 0; overflow: visible) collapsed to
    # ~34px. Its rows were laid out past the section and painted *underneath*
    # .sidebar-bottom, which then intercepted every click aimed at a conversation
    # or project row (conversation-delete and project-delete browser QA timed out).
    desktop = SCROLL[SCROLL.index("@media (min-width: 921px)"):SCROLL.index("@media (max-width: 920px)")]
    history_block = re.search(r"#historySection:not\(\[hidden\]\)\s*\{([^}]*)\}", desktop).group(1)
    assert "overflow: hidden;" in history_block
    assert "overflow: visible;" not in history_block
    floor = re.search(r"min-height:\s*(\d+)px;", history_block)
    assert floor and int(floor.group(1)) >= 120, history_block
    # The pinned layout is kept while it fits; when it cannot fit, the sidebar
    # itself scrolls instead of leaving rows under the pinned stack.
    sidebar_block = re.search(r"\.sidebar\s*\{([^}]*)\}", desktop).group(1)
    assert "overflow-y: auto !important;" in sidebar_block
    assert ".sidebar-bottom" in desktop and "margin-top: auto;" in desktop


def test_history_list_remains_the_single_desktop_conversation_scrollport():
    desktop = SCROLL[SCROLL.index("@media (min-width: 921px)"):SCROLL.index("@media (max-width: 920px)")]
    list_block = re.search(r"#historyList\s*\{([^}]*)\}", desktop).group(1)
    assert "overflow-y: auto;" in list_block
    assert "min-height: 0;" in list_block


def test_drive_is_fail_closed_without_registered_host_port():
    from app import meeting_drive_upload_routes as routes
    from app import app_factory
    from app import worker_config
    assert routes.MEETING_DRIVE_SESSION_PATH == "/api/claw/meeting/drive-upload-session"
    assert "meeting_drive_upload_session_port=None" in Path(app_factory.__file__).read_text(encoding="utf-8")
    assert "https://www.googleapis.com" in worker_config.CONTENT_SECURITY_POLICY
    assert INDEX.count('src="./meeting-drive-upload.js"')==1
    assert INDEX.count('src="./meeting-capture.js"')==1
