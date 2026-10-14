"""Chat and Claw share the same first-use DOM, art, composer and starter CSS.

These contracts protect Chat from unwanted UI regression while Claw presents
only its identity, four workspace choices and real-status-only connector paths.
No deployment or live PC/GitHub write access asserted.
"""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "claw-focus-layout.css").read_text(encoding="utf-8")
STYLES = (STATIC / "padiem-shared-ui.css").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")
ACTIONS = (STATIC / "claw-home-choices.js").read_text(encoding="utf-8")
LOCALE = (STATIC / "locale.js").read_text(encoding="utf-8")


class Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.nodes: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag, attrs):
        self.nodes.append((tag, dict(attrs)))


def nodes():
    p = Tags()
    p.feed(HTML)
    return p.nodes


def test_only_one_shared_chat_hero_and_composer_existing_product_structure():
    ids = [attrs.get("id") for _, attrs in nodes()]
    for one in (
        "emptyState", "messageInput", "composerForm", "attachmentButton",
        "sendButton", "connectorsDialog", "connectorsNavButton",
        "clawTaskHub", "clawWorkspace",
    ):
        assert ids.count(one) == 1, one
    assert '[hidden] { display: none !important; }' in STYLES
    assert 'href="./padiem-shared-ui.css"' in HTML
    assert 'class="starter-grid"' in HTML
    assert '.claw-workspace-starter' in CSS
    assert "claw-focus-layout.css" in HTML


def test_claw_four_cards_are_reused_chat_starters_in_exact_product_order():
    items = [
        ("clawComputerWorkspace", "컴퓨터 연결하기"),
        ("clawDriveWorkspace", "구글 드라이브"),
        ("clawGithubWorkspace", "GitHub"),
        ("clawWebWorkspace", "웹에서 하기"),
    ]
    anchors = []
    for ident, label in items:
        needle = f'id="{ident}"'
        assert HTML.count(needle) == 1
        offset = HTML.index(needle)
        assert 'class="starter claw-workspace-starter"' in HTML[offset-90:offset]
        assert label in HTML[offset:offset+750]
        anchors.append(offset)
    assert anchors == sorted(anchors)
    assert "웹에서 바로 작업하기" in HTML
    assert "설치 없이 웹에서" not in HTML
    assert all(f'document.getElementById("{k}")' not in APP for k, _ in items)
    assert "claw-home-choices.js" in HTML


def test_claw_identity_is_two_lines_without_a_duplicate_greeting():
    start = HTML.index('id="emptyState"')
    first = HTML[start:HTML.index('class="starter-grid"',start)]
    assert "작업하는 클로입니다." in first
    assert "직접 작업하는 파디엠 클로입니다." not in first
    assert '<span class="claw-hero-eyebrow">PADIEM CLAW</span>' in first
    assert "어디에서 작업할까요?" in first
    assert "claw-home-intro" in first and "claw-home-question" in first
    assert "chat-hero-line" in first
    assert "claw-hero-line" in first
    assert "querySelector(\".claw-hero-line\")" in LOCALE
    assert 'input.placeholder = localeOr("input", "Ask anything");' in APP
    assert "클로에게 작업을 맡겨보세요" in LOCALE
    assert "claw-home-intro" in LOCALE and "Where would you like to work?" in LOCALE
    assert LOCALE.count('"claw-home-previous-conversations"') == 2


def test_product_mode_is_scoped_and_starter_actions_never_create_fake_auth():
    assert '.app-shell[data-state="claw"] .chat-hero-line' in CSS
    assert '.claw-workspace[data-view="general"] ~ .conversation .claw-home-card' in CSS
    assert '.empty-state:not([hidden]) ~ #clawTaskHub' in CSS
    assert "#clawApprovedMemory,#clawRunHistory" in CSS
    assert 'document.getElementById("connectorsNavButton")' in ACTIONS
    assert 'document.getElementById("messageInput")?.focus()' in ACTIONS
    assert "credentials: \"same-origin\"" in ACTIONS
    assert '"/api/claw/local-access/devices"' in ACTIONS
    assert "ownerScoped !== true" in ACTIONS
    for forbidden in ('fetch("/api/claw/connector/enrollments/redeem",',
                      "dispatch_authorized: true", "window.location.href ="):
        assert forbidden not in ACTIONS


def test_connectors_show_github_and_computer_as_not_ready_without_fake_links():
    computer = HTML[HTML.index('id="connectorComputerCard"'):]
    github = HTML[HTML.index('id="connectorGithubCard"'):]
    assert 'data-connector-status="preparing"' in computer[:130]
    assert 'data-connector-status="preparing"' in github[:130]
    assert 'id="clawComputerLiveStatus"' in computer[:600]
    assert "GitHub 직접 연결은 준비 중" in github[:350]
    assert 'href="https://github.com/' not in github[:350]
    assert 'href="/download/' not in computer[:600]


def test_shared_portrait_and_existing_legacy_claw_workflows_stay_available():
    assert '#clawTaskHub' in CSS
    assert "main-panel::before" in CSS
    assert 'content: none;' in CSS
    assert ':not(:has(.claw-workspace[data-view="general"] ~ .conversation .empty-state:not([hidden]))) .main-panel::before' in CSS
    assert '.claw-hero-eyebrow' in CSS
    assert 'claw-connection-chips.js' in HTML
    assert 'display: block !important;\n  opacity: var(--glass-art-opacity)' not in CSS
    assert "clawApprovedMemory" in HTML
    assert "clawRunHistory" in HTML
    assert "clawExcelStartButton" in HTML
    assert "clawCompareStartButton" in HTML
    assert "clawDocumentStartButton" in HTML
    assert 'src="./claw-local-adapter.js"' in HTML


def test_claw_previous_conversations_reuses_owner_scoped_history():
    assert HTML.count('id="clawPreviousConversations"') == 1
    assert 'aria-controls="historySection"' in HTML
    assert 'id="historyList"' in HTML
    assert 'id="clawPreviousConversationsFeedback"' in HTML
    assert 'historySection' in ACTIONS and 'historyList' in ACTIONS
    assert 'loginButton' in ACTIONS
    assert 'accountContainer' in ACTIONS
    assert 'if (!signedIn && login' in ACTIONS
    assert 'sidebarRestoreButton' in ACTIONS
    assert 'mobileMenu' in ACTIONS
    assert 'history.focus?' in ACTIONS
    assert 'openSavedConversation' in APP
    assert "clawConversationIds.has(conversation.id)" in APP
    assert "isVerifiedClawThread" in APP
    assert ".claw-history-shortcut" in CSS
    assert 'claw-runs-title' in LOCALE
    assert 'fetch("/api/claw/runs"' not in ACTIONS


def test_claw_connection_chips_keep_canonical_authority_and_do_not_forge_disconnect():
    script = (STATIC / "claw-connection-chips.js").read_text(encoding="utf-8")
    for k in ("pc", "drive", "github"):
        assert f'data-claw-connection="{k}"' in HTML
    assert 'data-claw-connection="web"' not in HTML
    assert 'clawConnectionFeedback' in HTML
    assert '"/api/connectors/status"' in script
    assert '"/api/claw/local-access/devices"' in script
    assert 'workspace_state_authority===true' in script
    assert 'data-connection-state' in HTML
    assert "window.confirm(" not in script
    assert "A reviewed disconnect action is not available yet" in script
    assert 'set("github","unknown")' in script
    assert 'credentials:"same-origin"' in script
    assert 'fetch(' in script
    assert 'method:"POST"' not in script
    assert 'method:"DELETE"' not in script
    assert 'localStorage' not in script
    assert 'claw-connection-toggle' in CSS
    assert 'claw-card-icon' in CSS
    assert '.sidebar-account' in script
    assert 'data-claw-card="computer"' in HTML
    assert 'data-claw-card="github"' in HTML


def test_shared_chat_visuals_are_not_duplicated_for_claw_landing():
    assert "padiem-glass-female.jpg" not in CSS
    assert 'claw-home-chat-parity.css' not in HTML
    assert 'id="composerForm"' in HTML
    assert 'id="messageInput"' in HTML
    assert '--glass-chat-surface' in CSS or '--glass-chat-border' in CSS
    assert '.app-shell[data-state="claw"] #clawPreviousConversations' in CSS
    assert '#clawMemoryReview' in CSS
    assert 'content: none;' in CSS  # retained for active workbench only


def test_first_use_claw_retains_chat_alignment_and_input_tools():
    assert "display: grid !important;" in CSS  # The shared hero is never right-shifted by flex.
    assert ".composer-tools {\n  display: flex !important;" in CSS
    assert "#clawManualEntryBar {\n  display: none !important;" in CSS
    assert HTML.count('class="claw-connection-track"') == 3
    assert HTML.count('class="claw-state-on">ON') == 3
    assert HTML.count('class="claw-state-off">OFF') == 3
    script = (STATIC / "claw-connection-chips.js").read_text(encoding="utf-8")
    assert 'label.textContent=display' in script
    assert 'element.dataset.connectionState=value' in script
