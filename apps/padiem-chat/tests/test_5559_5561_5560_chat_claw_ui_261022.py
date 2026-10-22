"""#5559, #5561 and #5560 in one change: the Chat/Claw common UI.

Three owner decisions land in the same surface, so they are verified together:

* #5559 — one status surface for Chat and Claw. The card is rendered from the
  first moment of a turn, it names the real state, it opens on request, and
  the duplicate waiting surfaces (the meta badge, the composer notice, the
  waiting dots, the second answer listen button) are gone.
* #5561 — the composer has ONE primary action slot: the voice waveform for an
  empty composer, the send arrow once there is text. The M1 microphone stays a
  separate control.
* #5560 — the standalone sidebar rows (admin hub, conversation export,
  sign-out) moved into the existing Settings screen. The profile is the
  one-step Settings entry and Padiem Home stays in the sidebar.

The static contracts run everywhere. The browser contracts use Playwright and
skip when it is not installed.
"""

from __future__ import annotations

import http.server
import re
import threading
from pathlib import Path

import pytest

try:  # pragma: no cover - environment dependent
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - environment dependent
    sync_playwright = None

requires_browser = pytest.mark.skipif(
    sync_playwright is None, reason="playwright is not installed in this environment"
)

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC))

    def log_message(self, *args):
        pass


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True


@pytest.fixture(scope="module")
def server():
    with Server(("127.0.0.1", 0), Handler) as web:
        thread = threading.Thread(target=web.serve_forever, daemon=True)
        thread.start()
        yield f"http://127.0.0.1:{web.server_address[1]}/index.html"
        web.shutdown()


@pytest.fixture(scope="module")
def browser():
    if sync_playwright is None:
        pytest.skip("playwright is not installed in this environment")
    with sync_playwright() as pw:
        instance = pw.chromium.launch(headless=True)
        yield instance


# ── #5559 one status surface ───────────────────────────────────────────────


def test_the_status_card_is_the_one_status_surface() -> None:
    """The card renderer is shared, and a plain turn gets the card too."""
    lifecycle = _read("message-lifecycle.js")
    assert "function renderTaskCard(article, view, handlers = {})" in lifecycle
    assert "function renderTaskStatus(article, handlers = {})" in lifecycle
    # One renderer, one component: Chat and Claw do not fork the card.
    assert lifecycle.count('section.className = "capability-kit"') == 1
    assert 'section.dataset.orchestrationUi = "kit"' in lifecycle
    # A plain turn has no orchestration events and still gets the card.
    assert "if (!model.valid) {" in lifecycle
    assert "renderTaskStatus(article, handlers);" in lifecycle
    # The card is rendered from the first moment of the turn, not after it.
    app = _read("app.js")
    assert "window.PadiemChatLifecycle?.renderTaskStatus?.(article);" in app
    assert "window.PadiemChatLifecycle?.recordTaskEvent?.(article, \"request_sent\");" in app


def test_the_meta_badge_does_not_repeat_the_card_status() -> None:
    """The badge stays in the DOM (the auth projection reads it) but hidden.

    The card owns the live status of a running turn. The badge keeps the
    terminal outcome, so the two never show the same thing at once.
    """
    lifecycle = _read("message-lifecycle.js")
    assert "marker.hidden = Boolean(statusCardElement(article)) && cardShowsLiveStatus(article);" in lifecycle
    assert 'article.querySelector(\'[data-orchestration-ui="kit"]\')' in lifecycle
    assert 'return lifecycle === states.STREAMING || lifecycle === states.WAITING_APPROVAL;' in lifecycle
    # The plain lane keeps its outcome in the badge, so the card does not
    # repeat it.
    assert "terminalLine: false," in lifecycle


def test_the_duplicate_waiting_surfaces_are_gone() -> None:
    """The waiting state is the card. Nothing else says it again."""
    polish = _read("interaction-polish.js")
    assert "요청을 준비하고 있습니다." not in polish
    assert 'if (next === phases.PREPARING) return "";' in polish
    # The composer notice stays hidden when its phase has no copy.
    assert "statusNode.hidden = next === phases.IDLE || !message;" in polish
    # The waiting dots are not drawn any more. The marker element stays,
    # because the sources and export flows read it.
    app = _read("app.js")
    typing_block = app[app.index("function renderTyping(article)"):]
    typing_block = typing_block[: typing_block.index("\n  }")]
    assert 'typing.className = "typing";' in typing_block
    assert "document.createElement(\"i\")" not in typing_block
    assert 'typing.setAttribute("aria-hidden", "true");' in typing_block
    editorial = _read("padiem-editorial.css")
    assert ".typing:empty {" in editorial


def test_the_answer_carries_one_playback_control() -> None:
    """The answer action row keeps the listen control; the meta row loses it."""
    voice_answer = _read("voice-answer-ui.js")
    assert "voice-answer-listen" not in voice_answer
    assert "meta.appendChild(b)" not in voice_answer
    outputs = _read("outputs.js")
    assert '"answer-action answer-listen"' in outputs
    # The single control stops the M3 auto-speech instead of starting a
    # second reading of the same answer.
    assert 'article.dataset.ttsSpeaking === "true"' in outputs
    assert "window.PadiemVoiceAnswer?.stop?.();" in outputs


def test_no_stage_is_invented() -> None:
    """Only a real event or a real lifecycle state produces a label."""
    lifecycle = _read("message-lifecycle.js")
    for forbidden in ("생각 중", "thinking", "정리 중", "progressbar"):
        assert forbidden not in lifecycle, forbidden
    # Every status label is a closed catalogue entry.
    assert 'preparing: Object.freeze({ state: "active"' in lifecycle
    assert 'generating: Object.freeze({ state: "active"' in lifecycle
    assert 'searching: Object.freeze({ state: "active"' in lifecycle
    # The web-search label is only reachable through a real server tool.
    sources = _read("search-sources.js")
    assert 'window.PadiemChatLifecycle?.setTaskHint?.(article, "searching");' in sources
    assert 'window.PadiemChatLifecycle?.recordTaskEvent?.(article, "web_search");' in sources
    assert "data.tool.id === \"web_search\"" in sources


# ── #5561 one primary action slot ──────────────────────────────────────────


def test_the_voice_waveform_and_the_send_arrow_share_one_slot() -> None:
    menu = _read("voice-ui-menu.js")
    assert 'doc.getElementById("voiceWaveformButton")' not in menu
    assert 'wave.id = "voiceWaveformButton"' not in menu
    # The slot is the send button and it carries both faces.
    assert 'send.querySelector(".send-arrow-icon")' in menu
    assert 'send.querySelector(".send-waveform-icon")' in menu
    assert 'send.dataset.primaryAction = voice ? "voice" : "send";' in menu
    # The microphone stays a separate control.
    assert 'const MIC_BUTTON_ID = "voiceMicButton";' in _read("voice-composer.js")
    assert 'button.id = MIC_BUTTON_ID;' in _read("voice-composer.js")


def test_the_slot_switches_on_the_input_state() -> None:
    menu = _read("voice-ui-menu.js")
    # Whitespace alone is an empty composer.
    assert 'String(input.value || "").trim() === ""' in menu
    # An open IME composition is not an empty composer.
    assert "if (composing) return false;" in menu
    # A request in flight is not an empty composer.
    assert "if (input.disabled === true) return false;" in menu
    # The voice picker is only offered when the product really has one.
    assert "function voiceAvailable()" in menu
    assert 'return Boolean(liveAPI && typeof liveAPI.create === "function" && key());' in menu
    # The composer owns the input value and re-reads it.
    app = _read("app.js")
    assert "window.PadiemVoiceMenu?.syncPrimaryAction?.();" in app


def test_the_slot_keeps_its_touch_target_and_does_not_move() -> None:
    css = _read("voice-composer.css")
    assert "#composerForm .send-button {" in css
    block = css[css.index("#composerForm .send-button {"):]
    block = block[: block.index("}")]
    assert "width: 44px;" in block
    assert "height: 44px;" in block
    assert "flex: 0 0 44px;" in block
    # Only the active face is drawn, so the slot never changes size.
    assert ".send-arrow-icon[hidden]," in css
    assert ".send-waveform-icon[hidden] {" in css
    assert "display: none !important;" in css


def test_the_primary_action_markup_carries_both_faces() -> None:
    html = _read("index.html")
    send = html[html.index('id="sendButton"'):]
    send = send[: send.index("</button>")]
    assert 'class="send-arrow-icon"' in send
    assert 'class="send-waveform-icon"' in send
    assert 'data-locale-aria-label="send"' in send


# ── #5560 the sidebar rows moved into Settings ─────────────────────────────


def test_the_sidebar_no_longer_owns_the_three_rows() -> None:
    html = _read("index.html")
    bottom = html[html.index('<div class="sidebar-bottom"'):]
    bottom = bottom[: bottom.index("</div>\n    </aside>")]
    assert 'id="adminHubLink"' not in bottom
    assert 'id="conversationExportButton"' not in bottom
    # Padiem Home stays in the sidebar.
    assert 'class="home-link"' in bottom
    assert 'id="settingsButton"' in bottom
    assert 'class="sidebar-account account-controls"' in bottom


def test_settings_owns_the_admin_export_and_sign_out_entries() -> None:
    html = _read("index.html")
    assert 'id="adminSettingsSection"' in html
    assert 'id="adminHubLink"' in html
    assert 'href="./admin"' in html
    assert 'id="dataSettingsSection"' in html
    assert 'id="dataSettingsActions"' in html
    assert 'id="settingsLogoutButton"' in html
    # The password change stays a password-account-only entry.
    assert 'id="accountPasswordActions" hidden' in html
    assert 'id="passwordChangeOpen"' in html


def test_the_export_entry_mounts_in_settings_and_keeps_its_scope() -> None:
    export = _read("conversation-export.js")
    assert 'document.getElementById("dataSettingsActions")' in export
    assert "exportMount.appendChild(exportButton);" in export
    # The fail-closed export scope is unchanged.
    assert "lifecycleApi().isCompleted(article)" in export
    assert "exportButton.hidden = !settled;" in export
    assert "exportButton.disabled = !usable;" in export


def test_the_sign_out_has_one_implementation() -> None:
    app = _read("app.js")
    assert "async function signOutCurrentAccount()" in app
    assert 'await fetch("/api/auth/logout"' in app
    # Both entries reach the same implementation.
    sign_out = app[app.index("async function signOutCurrentAccount()"):]
    sign_out = sign_out[: sign_out.index("\n  }")]
    assert "resetConversationView(false);" in sign_out
    assert "await loadAuthStatus();" in sign_out
    assert "settingsLogoutButton.addEventListener(\"click\"" in app
    assert "await signOutCurrentAccount();" in app
    # The sidebar keeps the sign-in affordance; the signed-in profile is the
    # one-step Settings entry.
    # #5479: the sign-in entry point also survives an unreadable session state,
    # so the hide rule comes from the shared presentation rule.
    assert 'loginButton.hidden = presentation.loginHidden;' in app
    assert 'loginButton.hidden = sessionState === "unavailable" || sessionState === "signed_in";' not in app
    capabilities = _read("product-capabilities.js")
    assert "loginButton.hidden = shared.loginHidden;" in capabilities
    assert "loginButton.hidden = !available || state === \"signed_in\";" not in capabilities
    assert 'loginButton.hidden !== shared.loginHidden' in capabilities


def test_the_admin_entry_still_asks_the_server() -> None:
    entry = _read("admin-entry.js")
    assert '"/api/admin/session"' in entry
    assert "credentials: \"same-origin\"" in entry
    assert "data.authenticated === true" in entry
    assert "link.hidden = !authorized" in entry
    assert 'document.getElementById("adminSettingsSection")' in entry


def test_the_locale_carries_the_new_settings_copy() -> None:
    locale = _read("locale.js")
    ko, en = locale.split("en: {", 1)
    for key in ("admin-settings-title", "admin-hub", "admin-hub-aria", "data-settings-title"):
        assert f'"{key}":' in ko, key
        assert f'"{key}":' in en, key


def test_the_settings_screen_stays_reachable_on_a_phone() -> None:
    """The screen owns three more sections now, so it scrolls instead of clipping."""
    css = _read("padiem-chat-ui-polish.css")
    block = css[css.index(".settings-dialog {"):]
    block = block[: block.index("}")]
    assert "max-height: calc(100dvh - 32px);" in block
    assert "overflow-y: auto;" in block
    # The export entry carries the settings button skin, not the sidebar one.
    export = _read("conversation-export.js")
    assert 'exportButton.className = "settings-action conversation-export-button";' in export


@requires_browser
def test_the_settings_actions_are_reachable_at_390px(browser, server):
    """Every new settings entry can be scrolled to and used on a phone."""
    page = browser.new_page(viewport={"width": 390, "height": 844})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(server, wait_until="domcontentloaded")
    page.wait_for_timeout(1200)
    page.evaluate(
        """() => {
          const dialog = document.getElementById('settingsDialog');
          if (dialog && dialog.open) return;
          const profile = document.getElementById('accountProfileButton');
          if (profile) profile.click();
          if (dialog && !dialog.open) {
            const button = document.getElementById('settingsButton');
            if (button) button.click();
          }
          if (dialog && !dialog.open && typeof dialog.showModal === 'function') dialog.showModal();
        }"""
    )
    page.wait_for_timeout(400)
    state = page.evaluate(
        """() => {
          const dialog = document.getElementById('settingsDialog');
          const account = document.getElementById('accountSettingsSection');
          return {
            open: Boolean(dialog && dialog.open),
            scrollable: Boolean(dialog && dialog.scrollHeight > dialog.clientHeight),
            exportInSettings: Boolean(document.getElementById('dataSettingsActions')),
            logoutInAccount: Boolean(document.getElementById('settingsLogoutButton')),
            accountHidden: account ? account.hidden : null,
          };
        }"""
    )
    assert state["open"] is True, state
    # The screen scrolls, so the last sections are not clipped out of reach.
    assert state["scrollable"] is True, state
    assert state["exportInSettings"] is True, state
    assert state["logoutInAccount"] is True, state
    # Without a session there is nothing to sign out of, so the account
    # section stays closed. The sign-in affordance stays in the sidebar.
    assert state["accountHidden"] is True, state
    assert not errors, errors
    page.close()


# ── browser contracts ──────────────────────────────────────────────────────


@requires_browser
def test_the_empty_composer_shows_the_waveform_and_the_typed_one_the_arrow(browser):
    """The slot shows one face at a time and the slot itself never moves.

    The page is a harness, not the product shell: the voice picker needs an
    account whose voice identity the server accepted, and a guest session
    must not be shown a control that cannot work.
    """
    page = browser.new_page(viewport={"width": 390, "height": 844})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.set_content(
        """<!doctype html><html lang="ko"><body>
          <div class="app-shell" data-state="chat">
            <form id="composerForm">
              <div class="composer-actions">
                <button id="sendButton" type="submit">
                  <svg class="send-arrow-icon" aria-hidden="true"></svg>
                  <svg class="send-waveform-icon" aria-hidden="true" hidden></svg>
                </button>
              </div>
              <textarea id="messageInput"></textarea>
            </form>
            <main id="messageList"></main>
          </div>
        </body></html>"""
    )
    page.add_script_tag(path=str(STATIC / "voice-live-turn-controller.js"))
    page.evaluate(
        """() => {
          window.PadiemVoiceComposer = {
            getController: () => ({
              getStatus: () => ({ authenticated: true, authKnown: true, identityKey: 'voice-key', generation: 1 }),
            }),
          };
        }"""
    )
    page.add_script_tag(path=str(STATIC / "voice-ui-menu.js"))

    def slot() -> dict:
        return page.evaluate(
            """() => {
              const send = document.getElementById('sendButton');
              const arrow = send.querySelector('.send-arrow-icon');
              const wave = send.querySelector('.send-waveform-icon');
              const r = send.getBoundingClientRect();
              return {
                action: send.dataset.primaryAction || null,
                arrowHidden: arrow ? arrow.hidden : null,
                waveHidden: wave ? wave.hidden : null,
                width: Math.round(r.width),
                height: Math.round(r.height),
                left: Math.round(r.left),
                menu: Boolean(document.getElementById('voiceModeMenu')),
                waveButton: Boolean(document.getElementById('voiceWaveformButton')),
              };
            }"""
        )

    empty = slot()
    assert empty["waveButton"] is False, empty
    assert empty["action"] == "voice", empty
    assert empty["arrowHidden"] is True, empty
    assert empty["waveHidden"] is False, empty
    assert empty["height"] >= 44, empty
    assert empty["width"] >= 44, empty

    # The waveform face opens the M2/M3/M4 picker and does not submit.
    page.evaluate("""() => document.getElementById('sendButton').click()""")
    page.wait_for_timeout(150)
    opened = page.evaluate(
        """() => ({
          menuOpen: Boolean(document.getElementById('voiceModeMenu'))
            && document.getElementById('voiceModeMenu').hidden === false,
          expanded: document.getElementById('sendButton').getAttribute('aria-expanded'),
          sent: window.__sent === true,
        })"""
    )
    assert opened["menuOpen"] is True, opened
    assert opened["expanded"] == "true", opened
    assert opened["sent"] is False, opened

    page.evaluate("""() => document.getElementById('sendButton').click()""")
    page.wait_for_timeout(100)

    # Text turns the same slot into the send arrow.
    page.evaluate(
        """() => {
          const input = document.getElementById('messageInput');
          input.value = '안녕';
          input.dispatchEvent(new Event('input', { bubbles: true }));
        }"""
    )
    page.wait_for_timeout(150)
    typed = slot()
    assert typed["action"] == "send", typed
    assert typed["arrowHidden"] is False, typed
    assert typed["waveHidden"] is True, typed
    # The slot itself did not move.
    assert typed["left"] == empty["left"], (empty, typed)
    assert typed["width"] == empty["width"], (empty, typed)
    assert typed["height"] == empty["height"], (empty, typed)

    # Whitespace alone is still an empty composer.
    page.evaluate(
        """() => {
          const input = document.getElementById('messageInput');
          input.value = '   ';
          input.dispatchEvent(new Event('input', { bubbles: true }));
        }"""
    )
    page.wait_for_timeout(150)
    blank = slot()
    assert blank["action"] == "voice", blank
    assert blank["waveHidden"] is False, blank
    assert not errors, errors
    page.close()


@requires_browser
def test_a_guest_session_is_not_shown_a_voice_control_that_cannot_work(browser):
    """Without a server-attested voice identity the slot stays the arrow."""
    page = browser.new_page(viewport={"width": 390, "height": 844})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.set_content(
        """<!doctype html><html lang="ko"><body>
          <div class="app-shell" data-state="chat">
            <form id="composerForm">
              <div class="composer-actions">
                <button id="sendButton" type="submit">
                  <svg class="send-arrow-icon" aria-hidden="true"></svg>
                  <svg class="send-waveform-icon" aria-hidden="true" hidden></svg>
                </button>
              </div>
              <textarea id="messageInput"></textarea>
            </form>
            <main id="messageList"></main>
          </div>
        </body></html>"""
    )
    page.add_script_tag(path=str(STATIC / "voice-live-turn-controller.js"))
    page.evaluate(
        """() => {
          window.PadiemVoiceComposer = {
            getController: () => ({
              getStatus: () => ({ authenticated: false, authKnown: true, identityKey: '', generation: 1 }),
            }),
          };
        }"""
    )
    page.add_script_tag(path=str(STATIC / "voice-ui-menu.js"))
    state = page.evaluate(
        """() => {
          const send = document.getElementById('sendButton');
          const wave = send.querySelector('.send-waveform-icon');
          return {
            action: send.dataset.primaryAction || null,
            waveHidden: wave ? wave.hidden : null,
            voiceAction: Boolean(window.PadiemVoiceMenu.isVoicePrimaryAction()),
          };
        }"""
    )
    assert state["action"] == "send", state
    assert state["waveHidden"] is True, state
    assert state["voiceAction"] is False, state
    assert not errors, errors
    page.close()


@requires_browser
def test_the_settings_screen_carries_the_three_entries(browser, server):
    """The profile opens the existing settings screen, and it owns the rows."""
    page = browser.new_page(viewport={"width": 390, "height": 844})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(server, wait_until="domcontentloaded")
    page.wait_for_timeout(1200)

    state = page.evaluate(
        """() => {
          const bottom = document.querySelector('.sidebar-bottom');
          const dialog = document.getElementById('settingsDialog');
          const admin = document.getElementById('adminHubLink');
          const exportButton = document.getElementById('conversationExportButton');
          const logout = document.getElementById('settingsLogoutButton');
          return {
            adminInSidebar: Boolean(bottom.querySelector('#adminHubLink')),
            exportInSidebar: Boolean(bottom.querySelector('#conversationExportButton')),
            homeInSidebar: Boolean(bottom.querySelector('.home-link')),
            settings: Boolean(dialog),
            adminSection: Boolean(document.getElementById('adminSettingsSection')),
            dataSection: Boolean(document.getElementById('dataSettingsSection')),
            accountSection: Boolean(document.getElementById('accountSettingsSection')),
            logout: Boolean(logout),
            adminInSettings: Boolean(admin && dialog && dialog.contains(admin)),
            exportInSettings: Boolean(exportButton && dialog && dialog.contains(exportButton)),
            logoutInAccount: Boolean(logout && document.getElementById('accountSettingsSection')
              && document.getElementById('accountSettingsSection').contains(logout)),
          };
        }"""
    )
    assert state["adminInSidebar"] is False, state
    assert state["exportInSidebar"] is False, state
    assert state["homeInSidebar"] is True, state
    assert state["settings"] is True, state
    assert state["adminSection"] is True, state
    assert state["dataSection"] is True, state
    assert state["accountSection"] is True, state
    assert state["logout"] is True, state
    # The three entries live inside the existing settings screen.
    assert state["adminInSettings"] is True, state
    assert state["exportInSettings"] is True, state
    assert state["logoutInAccount"] is True, state
    assert not errors, errors
    page.close()


@requires_browser
def test_the_turn_carries_the_status_card_from_the_first_moment(browser, server):
    """The card is the one status surface of a turn."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(server, wait_until="domcontentloaded")
    page.wait_for_timeout(1200)

    state = page.evaluate(
        """() => {
          const lifecycle = window.PadiemChatLifecycle;
          if (!lifecycle) return {missing: true};
          const article = document.createElement('article');
          article.className = 'assistant-message';
          article.innerHTML = '<div class="assistant-meta">'
            + '<span data-assistant-product>Padiem Chat</span>'
            + '<span class="demo-label" data-runtime-label>답변 준비 중</span>'
            + '</div><div class="assistant-body"><div class="assistant-content"></div></div>';
          document.body.appendChild(article);
          lifecycle.set(article, 'streaming');
          lifecycle.recordTaskEvent(article, 'request_sent');
          lifecycle.renderTaskStatus(article);
          const card = article.querySelector('.capability-kit');
          const badge = article.querySelector('[data-runtime-label]');
          const status = card ? card.querySelector('.capability-current') : null;
          const out = {
            missing: false,
            card: Boolean(card),
            badgeHidden: badge ? badge.hidden : null,
            status: status ? status.textContent.trim() : null,
            stages: card ? card.querySelectorAll('.capability-stage').length : 0,
            summary: card ? card.querySelector('summary') : null,
            open: card ? card.querySelector('details').open : null,
          };
          article.remove();
          return out;
        }"""
    )
    assert state["missing"] is False, state
    assert state["card"] is True, state
    # The badge does not show a second copy of the live status.
    assert state["badgeHidden"] is True, state
    assert state["status"] == "답변 준비 중", state
    assert state["stages"] == 1, state
    # The card starts closed: the reader opens the real steps on request.
    assert state["open"] is False, state
    assert not errors, errors
    page.close()


@requires_browser
def test_the_terminal_outcome_stays_in_the_badge(browser, server):
    """A finished turn keeps its own outcome wording, once."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(server, wait_until="domcontentloaded")
    page.wait_for_timeout(1200)
    state = page.evaluate(
        """() => {
          const lifecycle = window.PadiemChatLifecycle;
          if (!lifecycle) return {missing: true};
          const article = document.createElement('article');
          article.className = 'assistant-message';
          article.innerHTML = '<div class="assistant-meta">'
            + '<span data-assistant-product>Padiem Chat</span>'
            + '<span class="demo-label" data-runtime-label></span>'
            + '</div><div class="assistant-body"><div class="assistant-content"></div></div>';
          document.body.appendChild(article);
          lifecycle.set(article, 'streaming');
          lifecycle.recordTaskEvent(article, 'request_sent');
          lifecycle.renderTaskStatus(article);
          const duringBadge = article.querySelector('[data-runtime-label]');
          const during = {hidden: duringBadge.hidden, text: duringBadge.textContent.trim()};
          // The turn ends with its own outcome copy.
          lifecycle.applyRuntimeLabel(article, '생성 취소됨', 'status');
          lifecycle.set(article, 'cancelled');
          const afterBadge = article.querySelector('[data-runtime-label]');
          const card = article.querySelector('.capability-kit');
          const out = {
            missing: false,
            during: during,
            afterHidden: afterBadge.hidden,
            afterText: afterBadge.textContent.trim(),
            cardTerminal: Boolean(card && card.querySelector('[data-capability-terminal]')),
          };
          article.remove();
          return out;
        }"""
    )
    assert state["missing"] is False, state
    # While the turn runs the card owns the status and the badge stays hidden.
    assert state["during"]["hidden"] is True, state
    # When the turn ends the badge carries the outcome exactly once.
    assert state["afterHidden"] is False, state
    assert state["afterText"] == "생성 취소됨", state
    # The plain lane's card does not repeat the outcome.
    assert state["cardTerminal"] is False, state
    assert not errors, errors
    page.close()
