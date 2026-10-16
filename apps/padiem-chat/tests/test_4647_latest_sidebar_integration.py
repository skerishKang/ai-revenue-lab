"""#4647: merge existing meeting workbench into current B62 sidebar without regressions."""
from pathlib import Path
import re

STATIC=Path(__file__).resolve().parents[1]/"static"
INDEX=(STATIC/"index.html").read_text(encoding="utf-8")
APP=(STATIC/"app.js").read_text(encoding="utf-8")
SCROLL=(STATIC/"sidebar-history-scroll.css").read_text(encoding="utf-8")
CSS=(STATIC/"meeting-capture.css").read_text(encoding="utf-8")


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
    assert 'PadiemMeetingCapture?.tryOpenFromClaw' in APP
    assert 'data-state="meeting"' in CSS
    assert 'overflow-y: auto;' in CSS


def test_single_divider_only_between_project_and_history_preserves_scroll():
    assert '#historySection:not([hidden])' in SCROLL
    assert "border-top: 1px solid rgba(230, 240, 250, .20)" in SCROLL
    assert '#historyList' in SCROLL
    assert 'overflow-y: auto;' in SCROLL
    assert '.sidebar-bottom' in SCROLL
    assert 'margin-top: auto;' in SCROLL
    assert 'max-height: min(44dvh, 360px);' in SCROLL


def test_drive_is_fail_closed_without_registered_host_port():
    from app import meeting_drive_upload_routes as routes
    from app import app_factory
    from app import worker_config
    assert routes.MEETING_DRIVE_SESSION_PATH == "/api/claw/meeting/drive-upload-session"
    assert "meeting_drive_upload_session_port=None" in Path(app_factory.__file__).read_text(encoding="utf-8")
    assert "https://www.googleapis.com" in worker_config.CONTENT_SECURITY_POLICY
    assert INDEX.count('src="./meeting-drive-upload.js"')==1
    assert INDEX.count('src="./meeting-capture.js"')==1
