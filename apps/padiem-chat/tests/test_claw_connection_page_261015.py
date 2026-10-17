"""#4139 dedicated PC connection page (LOCAL2): frozen contract checks.

The page reuses the reviewed server ports only. It must not invent a second
connector authority, endpoint, credential store, login step, or ONLINE claim.
"""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
PAGE_JS = (STATIC / "claw-connection-page.js").read_text(encoding="utf-8")
PAGE_CSS = (STATIC / "claw-connection-page.css").read_text(encoding="utf-8")


def test_page_assets_are_wired_before_the_legacy_guide():
    assert '<link rel="stylesheet" href="./claw-connection-page.css" />' in HTML
    assert '<script src="./claw-connection-page.js"></script>' in HTML
    assert HTML.index("claw-connection-page.js") < HTML.index("claw-connection-guide.js")
    assert HTML.index("claw-local-adapter.js") > HTML.index("claw-connection-page.js")


def test_page_reuses_only_the_reviewed_server_ports():
    assert '"/api/claw/local-access/devices"' in PAGE_JS
    assert '"/api/claw/connector/enrollments/consent/grant"' in PAGE_JS
    assert '"/api/claw/connector/enrollments/issue"' in PAGE_JS
    assert '"pc-enrollment-consent-v1"' in PAGE_JS
    assert "window.PadiemClawPcEnrollmentConsent" in PAGE_JS
    assert "window.__padiemPcEnrollmentConsentPort" in PAGE_JS
    assert "PadiemClawLocalHandoff" in PAGE_JS


def test_page_claims_no_second_authority_or_online_state():
    assert "localStorage." not in PAGE_JS
    assert "localStorage[" not in PAGE_JS
    assert "sessionStorage." not in PAGE_JS
    assert "https://" not in PAGE_JS
    assert "window.open(" not in PAGE_JS
    assert "wss://" not in PAGE_JS
    assert "websockets" not in PAGE_JS
    assert "dispatch_authorized !== false" in PAGE_JS
    assert "dispatch_authorized = true" not in PAGE_JS
    assert "dispatch_authorized:true" not in PAGE_JS


def test_native_launch_uses_only_the_exact_reviewed_os_link():
    assert PAGE_JS.count('"padiem-connector://start"') == 2
    assert "window.location.href = NATIVE_LAUNCH_LINK" in PAGE_JS
    assert "padiem-connector://start?" not in PAGE_JS
    assert "padiem-connector://start#" not in PAGE_JS
    assert "NATIVE_LAUNCH_LINK" in PAGE_JS


def test_manual_code_entry_lives_only_in_the_admin_area():
    assert "claw-connection-admin" in PAGE_JS
    assert "enroll " in PAGE_JS
    assert "--operator-wss-review" in PAGE_JS


def test_page_keeps_checked_consent_gating():
    assert "consentReadiness" in PAGE_JS
    assert "buildGrantBody" in PAGE_JS
    assert "projectGrantReceipt" in PAGE_JS
    assert "code_returned_once" in PAGE_JS
    assert "raw_device_credential" in PAGE_JS


def test_page_clears_one_time_codes_off_screen():
    assert "pagehide" in PAGE_JS
    assert "clearSecrets" in PAGE_JS
    assert "pairingCode = null" in PAGE_JS


def test_page_styles_use_theme_variables_only():
    assert "background: #" not in PAGE_CSS
    assert "border-color: #" not in PAGE_CSS
    assert "var(--accent" in PAGE_CSS
    assert "var(--panel" in PAGE_CSS
    assert "var(--text" in PAGE_CSS
    assert "var(--line" in PAGE_CSS
