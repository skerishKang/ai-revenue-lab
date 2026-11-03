from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
INDEX = STATIC / "index.html"
CAPABILITIES = STATIC / "product-capabilities.js"
SEARCH = STATIC / "search-sources.js"
APP_FACTORY = ROOT / "app" / "app_factory.py"


class _ButtonParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.buttons: dict[str, dict[str, str | None]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "button":
            return
        values = dict(attrs)
        identifier = values.get("id")
        if identifier:
            self.buttons[identifier] = values


def _buttons() -> dict[str, dict[str, str | None]]:
    parser = _ButtonParser()
    parser.feed(INDEX.read_text(encoding="utf-8"))
    return parser.buttons


def test_only_login_is_a_deployment_conditional_primary_control():
    buttons = _buttons()
    assert "loginButton" in buttons
    assert "hidden" in buttons["loginButton"]
    assert "disabled" in buttons["loginButton"]
    assert buttons["loginButton"].get("aria-disabled") == "true"
    assert not ({"webSearchStarterButton", "webSearchButton", "deepResearchButton"} & buttons.keys())
    html = INDEX.read_text(encoding="utf-8")
    assert "projectsNavButton" not in html

def test_browser_capability_projection_is_bounded_visibility_not_execution_authority() -> None:
    source = CAPABILITIES.read_text(encoding="utf-8")
    assert 'nativeFetch("/health"' in source
    assert 'nativeFetch("/api/auth/status"' in source
    for flag in [
        "web_tools_ready",
        "deep_research_ready",
        "auth_configured",
        "history_store_bound",
        "projects_code_ready",
        "project_files_code_ready",
        "project_file_store_bound",
        "saved_outputs_code_ready",
        "saved_output_store_bound",
    ]:
        assert flag in source
    assert 'CustomEvent("padiem:capabilitychange"' in source
    assert "Object.freeze" in source
    # #5121 adds the PADIEM Custom credential metadata endpoint (key registration
    # and deletion only). Chat execution itself must stay out of this projection.
    assert '"/api/chat"' not in source
    assert '"/api/chat/stream"' not in source
    assert "payload.tool" not in source
    assert "localStorage" not in source
    assert "sessionStorage" not in source
    assert "document.cookie" not in source


def test_search_capabilities_remain_server_projected_without_composer_controls():
    source = CAPABILITIES.read_text(encoding="utf-8")
    search = SEARCH.read_text(encoding="utf-8")
    html = INDEX.read_text(encoding="utf-8")
    for identifier in ("webSearchButton", "webSearchStarterButton", "deepResearchButton"):
        assert identifier not in html
        assert identifier not in source
        assert identifier not in search
    for flag in ("web_tools_ready", "deep_research_ready"):
        assert flag in source
    assert "window.PadiemSearchSources" in search

def test_sidebar_search_is_an_independent_fail_closed_conversation_search_entry() -> None:
    html = INDEX.read_text(encoding="utf-8")
    buttons = _buttons()
    search = buttons["sidebarSearchButton"]
    # Visible on the second sidebar line beside New Chat. #4471: it now opens
    # real conversation search, but it is still rendered disabled in markup and
    # only enabled by conversation-search.js when the owner's history is ready
    # (fail-closed by default).
    assert "hidden" not in search
    assert "disabled" in search
    assert search.get("aria-disabled") == "true"
    assert html.index('id="newChatButton"') < html.index('id="sidebarSearchButton"') < html.index('class="side-nav"')
    assert 'script src="./conversation-search.js" defer' in html


def test_sidebar_search_is_separate_from_result_rendering():
    source = CAPABILITIES.read_text(encoding="utf-8")
    assert 'getElementById("sidebarSearchButton")' not in source
    assert "syncSidebarSearch" not in source
    conversation_search_raw = (STATIC / "conversation-search.js").read_text(encoding="utf-8")
    conversation_search = "\n".join(
        line for line in conversation_search_raw.splitlines() if not line.lstrip().startswith("//")
    )
    assert 'getElementById("sidebarSearchButton")' in conversation_search
    for forbidden in ("webSearchButton", "webSearchStarterButton", "deepResearchButton"):
        assert forbidden not in conversation_search
    search_js = SEARCH.read_text(encoding="utf-8")
    assert "sidebarSearchButton" not in search_js
    assert "window.PadiemSearchSources = Object.freeze({ render: renderSources });" in search_js

def test_auth_status_controls_account_session_visibility_while_health_controls_code_capability() -> None:
    source = CAPABILITIES.read_text(encoding="utf-8")
    assert "projects: bool(data.projects_code_ready)," in source
    assert "projectFiles: bool(data.project_files_code_ready) && bool(data.project_file_store_bound)," in source
    assert "savedOutputs: bool(data.saved_outputs_code_ready) && bool(data.saved_output_store_bound)," in source
    assert 'const authAvailable = auth.loaded && auth.ready && auth.sessionState !== "unavailable";' in source
    assert "&& deployment.projects" in source
    assert "&& auth.authenticated" in source
    assert "&& auth.historyReady;" in source
    assert "syncAccountPresentation();" in source
    assert "setHidden(projectsNavButton, !projectsAvailable);" in source

    server = APP_FACTORY.read_text(encoding="utf-8")
    assert 'Route("/health", health, methods=["GET"])' in server
    assert '"web_tools_ready": web_ready' in server
    assert '"deep_research_ready": research_ready' in server
    assert '"auth_configured": settings.auth_mode != "off"' in server
    assert '"history_store_bound": request.app.state.history_store is not None' in server


def test_capability_projection_only_mutates_the_custom_credential_surface() -> None:
    source = CAPABILITIES.read_text(encoding="utf-8")
    # #5824 permits only the two owner-authenticated BYOK verification/save
    # POSTs. Capability, managed model, tier and deployment mutations stay out.
    auto_source = source.split("async function autoByok(", 1)[1].split(
        "async function saveCustomKey()", 1
    )[0]
    assert auto_source.count('method: "POST"') == 1
    assert 'register ? "/api/byok/register" : "/api/byok/detect"' in auto_source
    assert 'credentials: "same-origin"' in auto_source
    assert 'body: JSON.stringify(payload)' in auto_source
    assert 'method: "POST"' not in source.replace(auto_source, "")
    assert 'method: "PATCH"' not in source
    # #5121 requires deleting the customer's own PADIEM Custom credential and
    # nothing else: exactly one DELETE, scoped to the custom credential route,
    # with no body. Model, tier and deployment surfaces stay read-only.
    assert source.count('method: "DELETE"') == 1
    delete_start = source.index("async function deleteCustomKey()")
    delete_end = source.index("function createCustomSection()", delete_start)
    delete_source = source[delete_start:delete_end]
    assert 'method: "DELETE"' in delete_source
    assert (
        '"/api/chat/custom/credential?provider=" + encodeURIComponent(provider.provider)'
        in delete_source
    )
    assert "body:" not in delete_source
    assert "b14" not in source.lower()
    assert "control_plane" not in source.lower()


def test_dead_window_exports_and_flat_tier_copy_admin_labels() -> None:
    dead_exports = {
        "claw-mesh-capture.js": "window.PadiemClawMeshCapture",
        "claw-office-chooser.js": "window.PadiemHarkOfficeChooser",
        "conversation-search.js": "window.PadiemConversationSearch",
    }
    for filename, symbol in dead_exports.items():
        script = (STATIC / filename).read_text(encoding="utf-8")
        assert symbol not in script, (filename, symbol)

    source = CAPABILITIES.read_text(encoding="utf-8")
    ko_copy, en_copy = source.split("const TIER_COPY", 1)[1].split("en: Object.freeze", 1)
    en_copy = en_copy.split("});", 1)[0]
    assert 'admin: "Padiem 관리자"' in ko_copy
    assert 'admin: "Padiem Admin"' in en_copy
    assert "Padiem 관리자" not in en_copy
    assert "admin: [" not in ko_copy
    assert "admin: [" not in en_copy
