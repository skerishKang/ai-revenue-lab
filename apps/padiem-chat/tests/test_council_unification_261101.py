"""2026-11-01 unification + #7173/#7460 in-app Util menu contract.

- The retired legacy councillor panels stay out of index.html / util-menu.css,
  the /councillor/ redirect to /apps/council/ stays active, the prototype site
  is untouched, and the #padiem-connectors deep link continues to work.
- #7173 + #7460: the sidebar Util submenu renders all six tools from
  static/util-manifest.js and opens each tool's dedicated in-app screen
  (#util/<id>) with zero external redirects.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
UTIL_MANIFEST = STATIC / "util-manifest.js"
UTIL_MENU = STATIC / "util-menu.js"
INDEX_HTML = STATIC / "index.html"
UTIL_CSS = STATIC / "util-menu.css"
APP_JS = STATIC / "app.js"
HARNESS = ROOT / "tests" / "_council_unify_harness.js"


def run_util_menu() -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the util-menu harness"
    completed = subprocess.run(
        [node, str(HARNESS), str(UTIL_MANIFEST), str(UTIL_MENU)],
        capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT), check=False,
    )
    assert completed.stdout.strip(), completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result["ok"] is True, result
    return result["observation"]


def test_util_submenu_renders_six_tools_from_manifest_and_navigates_in_app() -> None:
    observed = run_util_menu()
    assert observed["assigned"] == []
    assert observed["renderedIds"] == ["speech", "sns", "meeting", "pdfmd", "quote", "excel"]
    assert observed["navigated"] == [
        "#util/speech",
        "#util/sns",
        "#util/meeting",
        "#util/pdfmd",
        "#util/quote",
        "#util/excel",
    ]


def test_legacy_councillor_panels_stay_out_of_index_and_menu_bundle() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    js = UTIL_MENU.read_text(encoding="utf-8")
    css = UTIL_CSS.read_text(encoding="utf-8")
    for gone in ("utilSpeechPanel", "utilSnsPanel", "utilMeetingPanel",
                 "utilSpeechForm", "utilSpeechOutput", "councillor/util-entry-adapter.js"):
        assert gone not in html, gone
    for gone in ("utilSpeechForm", "utilSnsPanel", "buildSns", "buildMeeting",
                 "apiChat(", "PC_REF_COPY", "saveProjectFile", "location.assign"):
        assert gone not in js, gone
    for gone in ("#utilSpeechPanel", ".util-photo", ".util-sns-tab", ".util-pc-ref",
                 ".util-save-choice"):
        assert gone not in css, gone
    util_app = (STATIC / "util-app.js").read_text(encoding="utf-8")
    assert 'panel.id = "utilPdfmdPanel"' in util_app
    assert "mountPdfmdPanel" in util_app
    assert ".pdfmd-shell" in css


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
