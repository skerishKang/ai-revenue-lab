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


def test_deployment_conditional_primary_controls_fail_closed_hidden() -> None:
    buttons = _buttons()
    conditional = {
        "sidebarSearchButton",
        "projectsNavButton",
        "loginButton",
        "webSearchStarterButton",
        "webSearchButton",
        "deepResearchButton",
    }
    assert conditional <= buttons.keys()
    for identifier in conditional:
        assert "hidden" in buttons[identifier], identifier
        assert "disabled" in buttons[identifier], identifier
        assert buttons[identifier].get("aria-disabled") == "true", identifier

    html = INDEX.read_text(encoding="utf-8")
    assert "<span class=\"mini-badge\">준비 중</span>" not in html
    assert "웹 검색은 준비 중입니다" not in html
    assert 'script src="./product-capabilities.js"' in html
    assert html.index('script src="./product-capabilities.js"') < html.index('script src="./search-sources.js"')


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
    assert "/api/chat" not in source
    assert "payload.tool" not in source
    assert "localStorage" not in source
    assert "sessionStorage" not in source
    assert "document.cookie" not in source


def test_search_and_research_visibility_separates_deployment_unavailable_from_busy() -> None:
    source = SEARCH.read_text(encoding="utf-8")
    assert 'document.getElementById("webSearchButton")' in source
    assert 'document.getElementById("webSearchStarterButton")' in source
    assert 'document.getElementById("deepResearchButton")' in source
    assert 'textContent.includes("웹 검색")' not in source
    assert 'textContent.includes("웹에서 찾아줘")' not in source

    assert "webSearchButton.hidden = !webReady;" in source
    assert "webSearchStarter.hidden = !webReady;" in source
    assert "deepResearchButton.hidden = !researchReady;" in source
    assert "const webBusy = webReady && busy;" in source
    assert "const researchBusy = researchReady && busy;" in source
    assert "webSearchButton.disabled = webBusy;" in source
    assert "deepResearchButton.disabled = researchBusy;" in source
    assert 'window.addEventListener("padiem:capabilitychange"' in source


def test_sidebar_search_is_real_capability_backed_navigation_and_mirrors_busy_state() -> None:
    source = CAPABILITIES.read_text(encoding="utf-8")
    assert 'document.getElementById("sidebarSearchButton")' in source
    assert 'document.getElementById("webSearchButton")' in source
    assert "sidebarSearchButton.hidden = !available;" in source
    assert "const busy = webSearchButton.disabled;" in source
    assert "sidebarSearchButton.disabled = busy;" in source
    assert "webSearchButton.click();" in source
    assert "messageInput.focus();" in source
    assert "mobileClose.click();" in source


def test_auth_status_controls_account_session_visibility_while_health_controls_code_capability() -> None:
    source = CAPABILITIES.read_text(encoding="utf-8")
    assert "projects: bool(data.projects_code_ready)," in source
    assert "projectFiles: bool(data.project_files_code_ready) && bool(data.project_file_store_bound)," in source
    assert "savedOutputs: bool(data.saved_outputs_code_ready) && bool(data.saved_output_store_bound)," in source
    assert "const authAvailable = auth.loaded && auth.ready;" in source
    assert "&& deployment.projects" in source
    assert "&& auth.authenticated" in source
    assert "&& auth.historyReady;" in source
    assert "setHidden(loginButton, !authAvailable);" in source
    assert "setHidden(projectsNavButton, !projectsAvailable);" in source

    server = APP_FACTORY.read_text(encoding="utf-8")
    assert 'Route("/health", health, methods=["GET"])' in server
    assert '"web_tools_ready": web_ready' in server
    assert '"deep_research_ready": settings.runtime_mode == "b14" and web_ready' in server
    assert '"auth_configured": settings.auth_mode == "google"' in server
    assert '"history_store_bound": request.app.state.history_store is not None' in server


def test_capability_projection_does_not_mutate_server_or_model_surfaces() -> None:
    source = CAPABILITIES.read_text(encoding="utf-8")
    assert 'method: "POST"' not in source
    assert 'method: "PATCH"' not in source
    assert 'method: "DELETE"' not in source
    assert "b14" not in source.lower()
    assert "control_plane" not in source.lower()
