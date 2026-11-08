"""Static contracts for the 관리 PC admin-page toggle (#7147 UI lane).

The 관리 PC mark is administered from the 총관리자 page (admin.html), not from
the chat settings: the settings modal keeps 테마·언어·알림·로그아웃 only, the
advanced settings page carries 내 PC·연결된 AI·개발자·계정, and the admin hub
owns the per-device toggle against the two #7147 endpoints. Static and
network-free.
"""
from pathlib import Path
import re

REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / "apps" / "padiem-chat" / "static"


def test_admin_page_carries_the_managed_panel():
    html = (STATIC / "admin.html").read_text(encoding="utf-8")
    assert 'id="pcManagedPanel" hidden' in html
    assert 'id="pcManagedList"' in html
    assert 'id="pcManagedError"' in html
    # The reviewed one-line description, verbatim in the default (ko) markup.
    assert "관리 PC에서는 관리자가 SYSTEM 권한으로 명령을 실행할 수 있습니다." in html


def test_admin_page_gates_the_toggle_on_the_admin_session():
    js = (STATIC / "admin.js").read_text(encoding="utf-8")
    # The admin page already attests the role via /api/admin/session; the
    # managed rows render from the pairings fetch and the separate state GET
    # (the base link read never joins the migration 103 column).
    assert "/api/pc/pairings" in js
    assert '"/api/pc/devices/" + encodeURIComponent(link.link_id) + "/managed"' in js
    assert "async function loadManaged" in js
    assert "async function setManaged" in js
    # The toggle posts exactly the reviewed body.
    assert "body: JSON.stringify({ managed: !previous })" in js
    # 503 pc_pairing_not_ready: the notice shows and the row keeps its state.
    assert "pc_pairing_not_ready" in js


def test_chat_settings_do_not_render_the_managed_toggle():
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="pcManagedBlock"' not in index
    assert 'id="pcManagedList"' not in index
    app = (STATIC / "mcp-gateway-settings.js").read_text(encoding="utf-8")
    assert "pcManagedBlock" not in app
    assert "paintManaged" not in app
    advanced = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="advancedSettingsView"' in advanced


def test_managed_copy_exists_in_both_languages():
    locale = (STATIC / "locale.js").read_text(encoding="utf-8")
    for key, ko, en in (
        ("pc-managed-toggle", "관리 PC", "Managed PC"),
        ("pc-managed-note",
         "관리 PC에서는 관리자가 SYSTEM 권한으로 명령을 실행할 수 있습니다.",
         "On a managed PC the administrator can run commands with SYSTEM privileges."),
        ("pc-managed-not-ready",
         "관리 PC 표시를 아직 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.",
         "The managed PC mark is not ready yet. Please try again shortly."),
        ("pc-managed-forbidden",
         "관리 PC를 표시할 권한이 없습니다.",
         "You do not have permission to manage PCs."),
    ):
        assert f'"{key}": "{ko}"' in locale, key
        assert f'"{key}": "{en}"' in locale, key


def test_advanced_page_rows_reuse_the_settings_card_styles():
    js = (STATIC / "mcp-gateway-settings.js").read_text(encoding="utf-8")
    assert 'element("li", "mcp-settings-card")' in js
    css = (REPO / "apps" / "padiem-chat" / "static" / "padiem-chat-ui-polish.css").read_text(encoding="utf-8")
    assert "pc-managed" not in css
