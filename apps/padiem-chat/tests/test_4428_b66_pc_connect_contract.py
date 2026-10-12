"""#4428 B66 Connect: static, security and no-premature-activation contract."""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"


def test_b66_pc_view_reuses_canonical_claw_projection_without_execution():
    js = (STATIC / "b66-quote-runtime.js").read_text(encoding="utf-8")
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert '"b66QuotePcToggle"' in js
    assert '"b66QuotePcPanel"' in js
    assert '"b66QuotePcStatus"' in js
    assert '"b66QuotePcList"' in js
    assert '"b66QuotePcRefresh"' in js
    assert 'PC_DIRECTORY_PATH = "/api/b66/connect/devices"' in js
    assert "window.PadiemClawLocalHandoff?.deriveDeviceDirectory" in js
    assert html.index('./claw-local-handoff.js') < html.index('./b66-quote-runtime.js')
    assert 'credentials: "same-origin"' in js
    assert 'MAX_PC_DIRECTORY_BYTES = 32768' in js
    loader = js.split("async function loadPcDirectory() {", 1)[1].split(
        "function closeDialog()", 1
    )[0]
    assert 'method: "GET"' in loader
    assert "nativeFetch(PC_DIRECTORY_PATH" in loader
    assert "directory.devices" in loader
    for forbidden in (
        'method: "POST"', 'method: "PUT"', 'method: "DELETE"',
        "localStorage", "sessionStorage", "postMessage", "new WebSocket",
        "document.cookie", "pairingToken", "fetch('/api/command",
    ):
        assert forbidden not in loader
    assert "device.online" in loader
    assert "device.revoked" in loader
    assert "pcDirectoryEnabled: data.pc_device_list_enabled === true" in js
    assert "pcSection.hidden = true" in js
    assert "runtime?.pcDirectoryEnabled === true" in js
    assert "if (!pcEnabled) resetPcDirectory();" in js


def test_no_eager_request_and_logout_discards_stale_pc_results():
    js = (STATIC / "b66-quote-runtime.js").read_text(encoding="utf-8")
    assert "pcPanel.hidden = true;" in js
    assert "void loadPcDirectory();" in js
    assert "pcQuerySequence += 1" in js
    assert "current === pcQuerySequence && !section.hidden" in js
    assert "resetPcDirectory();" in js
    assert '["padiem:auth-state", "padiem:auth-changed", "padiem:account-changed"]' in js
    assert 'if (auth && auth.authenticated === true) refresh();' in js
    assert "resetPcDirectory();\n      runtime = null;" in js
    assert 'pcUnavailable: "PC 연결 서비스가 아직 준비되지 않았습니다.' in js
    assert "PADIEM Connect installation and same-account sign-in are not ready yet" in js
    assert "https://github.com/" not in js.split("async function loadPcDirectory()", 1)[1].split("function closeDialog()", 1)[0]


def test_b66_pc_directory_is_default_off_without_product_entitlement():
    """No B66 product permission adapter is live yet; do not leak Claw devices."""
    source = (STATIC / "b66-quote-runtime.js").read_text(encoding="utf-8")
    server = (STATIC.parent / "app" / "b66_quote_routes.py").read_text(encoding="utf-8")
    assert "pcDirectoryEnabled: data.pc_device_list_enabled === true" in source
    assert "pcSection.hidden = true;" in source
    assert "runtime?.pcDirectoryEnabled === true" in source
    assert "if (pcSection) pcSection.hidden = !pcEnabled;" in source
    # Future permission may only come from a reviewed authenticated server
    # product-policy adapter, never from B66 product data or a browser flag.
    assert "pc_device_list_enabled" not in server
