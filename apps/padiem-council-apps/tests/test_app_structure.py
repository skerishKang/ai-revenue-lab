"""The council apps entry is a self-contained static app with no second authority.

Structural contracts:

- the app owns only its entry surface (``/healthz``, ``/``, static assets)
  and imports no repository package;
- the browser module reuses the EXISTING PADIEM endpoints and nothing else;
- the Chat/Claw surface (``apps/padiem-chat/**``) is not touched by this app,
  which is proven by the repository diff, not asserted here (see the PR).
"""

from __future__ import annotations

from pathlib import Path
import re

from starlette.testclient import TestClient

from app.app_factory import create_app
from _council_module import local_asset_targets

APP_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = APP_ROOT / "static"
COUNCIL_JS = STATIC_DIR / "council-app.js"
COUNCIL_CSS = STATIC_DIR / "council-app.css"
INDEX_HTML = STATIC_DIR / "index.html"

#: The exact endpoint set the shared contract layer may touch. This is the
#: shipped util contract: the public chat lane, the project-file store and
#: the session status probe. Anything else is a second authority.
#: #5942 adds the EXISTING password credential route, so a signed-out visitor
#: signs in inside this page instead of being sent to the Chat home; it is the
#: same server-owned session contract, not a new login system.
ALLOWED_ENDPOINTS = {
    "/api/chat",
    "/api/projects",
    "/api/projects/",
    "/api/auth/status",
    "/api/auth/password/login",
}

FORBIDDEN_MARKERS = (
    '"/api/b66',
    '"/api/claw',
    '"/api/util',
    '"/api/council',
    '"/auth/',
    '"calendar_turn_id',
    '"timezone',
)


def test_app_files_exist() -> None:
    for name in ("index.html", "council-app.js", "council-app.css"):
        assert (STATIC_DIR / name).is_file(), name


def test_create_app_serves_healthz_index_and_static() -> None:
    client = TestClient(create_app())
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json() == {"ok": True, "app": "padiem-council-apps"}

    index = client.get("/")
    assert index.status_code == 200
    assert "PADIEM 의원3종" in index.text
    assert "./static/council-app.js" in index.text

    asset = client.get("/static/council-app.js")
    assert asset.status_code == 200
    assert "PadiemCouncilApps" in asset.text


def test_the_browser_module_only_touches_the_existing_endpoints() -> None:
    source = COUNCIL_JS.read_text(encoding="utf-8")
    called = set(re.findall(r'fetch\(\s*"([^"]+)"', source))
    # Dynamic URL fragments are built by concatenation; the static prefixes
    # must all be within the allowed set.
    assert called, "the module should call the reused backend"
    for url in called:
        assert any(url == allowed or url.startswith(allowed) for allowed in ALLOWED_ENDPOINTS), url


def test_the_browser_module_keeps_the_util_payload_and_declares_the_util_scope() -> None:
    """The call surface stays the shipped util contract, in code — not comments."""
    source = COUNCIL_JS.read_text(encoding="utf-8")
    code_only = "\n".join(
        line for line in source.splitlines()
        if not line.lstrip().startswith(("*", "/*", "//"))
    )
    assert 'mode: "auto"' in code_only
    assert "PadiemTierSelection" in code_only
    # The #5916 execution-boundary contract: the module declares which
    # utility it is, or the shared calendar branch can hijack a meeting
    # text containing 확인/추가/일정.
    assert 'payload.util = util' in code_only
    for scope in ('"speech"', '"sns"', '"meeting"'):
        assert scope in code_only, scope
    for marker in FORBIDDEN_MARKERS:
        assert marker not in code_only, marker


def test_the_browser_module_keeps_the_session_cookie_contract() -> None:
    source = COUNCIL_JS.read_text(encoding="utf-8")
    assert source.count('credentials: "include"') >= 5

def test_the_entry_page_gates_the_tools_on_sign_in_and_declares_independence() -> None:
    source = COUNCIL_JS.read_text(encoding="utf-8")
    # fail-closed like councillor.js: builders attach only when authenticated.
    assert 'data.authenticated === true' in source
    assert "fail-closed" in source
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert "축사·인사말" in html
    assert "SNS 홍보" in html
    assert "회의정리·활동집" in html
    assert "noindex" in html


def test_the_entry_css_exists_and_does_not_import_chat_assets() -> None:
    css = COUNCIL_CSS.read_text(encoding="utf-8")
    assert "@import" not in css
    # Naming the family is fine; importing or mutating a Chat asset is not. The cinematic
    # layer may only reach files that ship inside this app's own static/assets/, so the
    # bundle stays self-contained and no other origin is contacted at paint time.
    for target in local_asset_targets(css):
        assert target.startswith("./assets/"), f"asset outside this app: {target}"


def test_the_app_declares_no_business_number() -> None:
    readme = (APP_ROOT / "README.md").read_text(encoding="utf-8")
    assert "Business 번호" in readme
    assert "미확정" in readme
