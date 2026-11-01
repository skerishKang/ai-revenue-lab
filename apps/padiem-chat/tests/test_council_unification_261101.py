"""2026-11-01: the three 의원3종 tools have one home — /apps/council/.

Chat keeps the util page shell and the PDF → Markdown menu. The council entries
leave for the independent app with the tool in the fragment (same session
cookie, no second login), and the retired councillor profile screen is a
redirect. These tests execute the shipped util-menu.js on a fake DOM for the
link behaviour and read the shipped route for the redirect.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
UTIL_MENU = STATIC / "util-menu.js"
INDEX_HTML = STATIC / "index.html"
UTIL_CSS = STATIC / "util-menu.css"
APP_JS = STATIC / "app.js"
HARNESS = ROOT / "tests" / "_council_unify_harness.js"


def run_util_menu() -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the util-menu harness"
    completed = subprocess.run(
        [node, str(HARNESS), str(UTIL_MENU)],
        capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT), check=False,
    )
    assert completed.stdout.strip(), completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result["ok"] is True, result
    return result["observation"]


def test_the_three_council_entries_leave_for_the_independent_app() -> None:
    observed = run_util_menu()
    assert observed["assigned"] == [
        "/apps/council/#speech",
        "/apps/council/#sns",
        "/apps/council/#meeting",
        "/apps/council/#sns",
        "/apps/council/#meeting",
    ]


def test_pdf_to_markdown_still_opens_inside_chat() -> None:
    observed = run_util_menu()["pdfmd"]
    assert observed["assigned"] == []
    assert observed["initialized"] == ["utilPdfmdPanel"]
    assert observed["panelHidden"] is False
    assert observed["title"] == "PDF → Markdown"


def test_the_council_screens_and_their_code_left_the_chat_bundle() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    js = UTIL_MENU.read_text(encoding="utf-8")
    css = UTIL_CSS.read_text(encoding="utf-8")
    for gone in ("utilSpeechPanel", "utilSnsPanel", "utilMeetingPanel",
                 "utilSpeechForm", "utilSpeechOutput", "councillor/util-entry-adapter.js"):
        assert gone not in html, gone
    for gone in ("utilSpeechForm", "utilSnsPanel", "buildSns", "buildMeeting",
                 "apiChat(", "PC_REF_COPY", "saveProjectFile"):
        assert gone not in js, gone
    for gone in ("#utilSpeechPanel", ".util-photo", ".util-sns-tab", ".util-pc-ref",
                 ".util-save-choice"):
        assert gone not in css, gone
    # The two utilities that still live in Chat keep their surface.
    assert 'id="utilPdfmdPanel"' in html
    assert "initPdfMdUtility" in js
    assert ".pdfmd-shell" in css


def test_the_council_links_are_the_only_destination_and_carry_no_authority() -> None:
    js = UTIL_MENU.read_text(encoding="utf-8")
    assert 'speech: "/apps/council/#speech"' in js
    assert 'sns: "/apps/council/#sns"' in js
    assert 'meeting: "/apps/council/#meeting"' in js
    # Same-origin navigation only: no token, user id or query parameter.
    assert "location.assign" in js
    assert "?" not in js.split("COUNCIL_TOOL_HREF", 1)[1].split("}", 1)[0]


def test_the_retired_councillor_screen_is_gone_and_the_alias_redirects() -> None:
    assert not (STATIC / "councillor").exists()
    assert not (STATIC / "councillor" / "brands" / "miraen.json").exists()
    factory = (ROOT / "app" / "app_factory.py").read_text(encoding="utf-8")
    assert 'COUNCILLOR_REDIRECT_PATH = "/councillor/"' in factory
    assert 'RedirectResponse("/apps/council/", status_code=302)' in factory
    assert 'Route(COUNCILLOR_REDIRECT_PATH, councillor_redirect, methods=["GET"])' in factory


def test_the_councillor_prototype_site_is_untouched() -> None:
    prototype = ROOT.parent.parent / "apps" / "councillor-prototype"
    assert (prototype / "static" / "miraen.json").is_file()
    assert (prototype / "static" / "app.js").is_file()


def test_the_council_connect_button_has_a_connectors_deep_link() -> None:
    app_js = APP_JS.read_text(encoding="utf-8")
    assert 'CONNECTORS_ROUTE_HASH = "#padiem-connectors"' in app_js
    assert "openConnectorsView()" in app_js.split("CONNECTORS_ROUTE_HASH", 1)[1]
    council = (ROOT.parent / "padiem-council-apps" / "static" / "council-app.js").read_text(encoding="utf-8")
    assert 'COMPUTER_CONNECT_HREF = "/#padiem-connectors"' in council
