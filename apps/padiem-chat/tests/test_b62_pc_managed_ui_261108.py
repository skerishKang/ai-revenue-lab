"""Static contracts for the 관리 PC settings toggle (#7147 UI lane).

The settings screen renders the per-device 관리 PC toggle only for the
server-attested platform administrator, talks to the two #7147 endpoints
(POST the mark, GET the state), degrades on 503 pc_pairing_not_ready, and
carries the reviewed ko/en copy. Static and network-free.
"""
from pathlib import Path
import re

STATIC = Path(__file__).resolve().parents[1] / "static"


def test_settings_markup_carries_the_managed_block():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="mcpGatewayManagedBlock" hidden' in html
    assert 'id="mcpGatewayManagedList"' in html
    assert 'id="mcpGatewayManagedNotReady"' in html
    assert 'data-locale-key="pc-managed-title"' in html
    # The reviewed one-line description, verbatim in the default (ko) markup.
    assert "관리 PC에서는 관리자가 SYSTEM 권한으로 명령을 실행할 수 있습니다." in html
    assert 'data-locale-key="pc-managed-note"' in html


def test_settings_module_gates_the_toggle_on_the_admin_flag():
    js = (STATIC / "mcp-gateway-settings.js").read_text(encoding="utf-8")
    # The pairings response carries one boolean; the module reads it.
    assert "state.admin = pairings?.status === 200 && pairings.body?.admin === true" in js
    # The rows render only for the administrator with ready links.
    assert "const visible = state.admin && state.ready && activeLinks().length > 0;" in js
    assert "nodes.managedblock.hidden = !visible;" in js
    # The separate state query (the base link read never joins the column).
    assert '"/api/pc/devices/" + encodeURIComponent(link.link_id) + "/managed"' in js
    # The toggle posts exactly the reviewed body.
    assert '"POST", { managed: box.checked }' in js
    # 503 pc_pairing_not_ready: the toggles disable and the notice shows.
    assert 'reply.body?.error?.code === "pc_pairing_not_ready"' in js
    assert "state.managedReady = false;" in js
    assert "nodes.managednotready.hidden = false;" in js
    # 403 drops the admin verdict and hides the block (fail-closed UI).
    assert "state.admin = false;" in js
    assert "nodes.managedblock.hidden = true;" in js


def test_managed_copy_exists_in_both_languages():
    locale = (STATIC / "locale.js").read_text(encoding="utf-8")
    for key, ko, en in (
        ("pc-managed-toggle", "관리 PC", "Managed PC"),
        ("pc-managed-title", "PC 연결", "PC connections"),
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


def test_toggle_rows_reuse_the_settings_card_styles():
    js = (STATIC / "mcp-gateway-settings.js").read_text(encoding="utf-8")
    # The rows reuse the existing settings card/field classes; no new sheet.
    assert 'element("li", "mcp-settings-card")' in js
    css = (STATIC / "padiem-chat-ui-polish.css").read_text(encoding="utf-8")
    assert "pc-managed" not in css
