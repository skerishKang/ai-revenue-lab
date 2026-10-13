"""#4139: PC enrollment consent surface — real Chromium browser contracts (LOCAL1).

This is the explicit consent UI the CENTRAL #4476 contract document defers
("there is no new UI/consent checkbox yet"). The consent is NOT an execution
approval: these tests assert the ready state sends nothing, that a target or
product that cannot be confirmed blocks progress, that a stored consent never
reads as ONLINE, and that no server string becomes markup.

The only network path is a verified server port on
``window.__padiemPcEnrollmentConsentPort``. These tests install a spy port; no
real enrollment route, credential or pairing is ever exercised.
"""
from __future__ import annotations

import http.server
import json
import threading
from pathlib import Path

import pytest

# Full B62 core runners intentionally do not install Playwright. Skip this
# optional browser suite there instead of aborting pytest collection.
sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

ROOT = Path(__file__).resolve().parents[1] / "static"
CONSENT_VERSION = "pc-enrollment-consent-v1"


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, *_args):
        pass


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True


@pytest.fixture(scope="module")
def server():
    with Server(("127.0.0.1", 0), Handler) as web:
        t = threading.Thread(target=web.serve_forever, daemon=True)
        t.start()
        yield f"http://127.0.0.1:{web.server_address[1]}/index.html"
        web.shutdown()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        yield b
        b.close()


def open_claw(browser, server, width=1280):
    page = browser.new_page(viewport={"width": width, "height": 900})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(server, wait_until="domcontentloaded")
    page.locator("#clawPcConsentToggle").wait_for(state="attached")
    assert page.locator("#clawPcEnrollmentConsent").is_hidden()
    # Simulate the Claw presentation state without invoking authenticated
    # backend activation; app.js owns actual navigation and session gates.
    page.evaluate("""() => {
      document.querySelector(".app-shell").setAttribute("data-state", "claw");
      document.getElementById("clawWorkspace").hidden = false;
    }""")
    page.locator("#clawWorkspace").wait_for(state="visible", timeout=5000)
    page.locator("#clawPcConsentToggle").wait_for(state="visible", timeout=10000)
    return page, errors


def install_port(page, *, device_id="pc1", device_name="집 컴퓨터",
                 product_id="b54-padiem-claw", feature_activated=True,
                 defer=False, grant_result=None):
    """Install the only network path. Records every body sent to the server."""
    page.evaluate(
        """(cfg) => {
          window.__consentCalls = [];
          window.__padiemPcEnrollmentConsentPort = {
            describeTarget: () => ({
              deviceId: cfg.deviceId,
              deviceName: cfg.deviceName,
              productId: cfg.productId,
              featureActivated: cfg.featureActivated,
            }),
            grantConsent: (body) => {
              window.__consentCalls.push({ op: "grant", body });
              if (cfg.defer) {
                return new Promise((resolve) => { window.__resolveGrant = resolve; });
              }
              return Promise.resolve(cfg.grantResult);
            },
            revokeConsent: (body) => {
              window.__consentCalls.push({ op: "revoke", body });
              return Promise.resolve(cfg.revokeResult);
            },
          };
        }""",
        {
            "deviceId": device_id,
            "deviceName": device_name,
            "productId": product_id,
            "featureActivated": feature_activated,
            "defer": defer,
            "grantResult": grant_result,
        },
    )


def grant_ok(device_id="pc1"):
    return {"ok": True, "consent": {"device_id": device_id, "consent_id": "consent-1", "dispatch_authorized": False}}


def open_panel(page):
    page.locator("#clawPcConsentToggle").click()
    page.locator("#clawPcConsentPanel").wait_for(state="visible")


def calls(page):
    return page.evaluate("window.__consentCalls")


# --- 1. default OFF ---------------------------------------------------------


@pytest.mark.parametrize("width", [390, 873, 1280])
def test_default_consent_is_off_and_ready_state_sends_nothing(browser, server, width):
    page, errors = open_claw(browser, server, width)
    install_port(page)
    open_panel(page)
    assert page.locator("#clawPcConsentAck").is_checked() is False
    assert page.locator("#clawPcConsentConfirm").is_disabled()
    # The ready state must not have issued a single request.
    assert calls(page) == []
    assert not errors, errors
    page.close()


# --- 2. cancel sends no request ---------------------------------------------


def test_cancel_sends_no_request_and_returns_to_default_off(browser, server):
    page, errors = open_claw(browser, server)
    install_port(page)
    open_panel(page)
    page.locator("#clawPcConsentAck").check()
    assert page.locator("#clawPcConsentConfirm").is_enabled()
    page.locator("#clawPcConsentCancel").click()
    assert page.locator("#clawPcConsentPanel").is_hidden()
    assert page.locator("#clawPcConsentToggle").get_attribute("aria-expanded") == "false"
    assert calls(page) == []
    # Re-opening shows the acknowledgement reset to OFF.
    open_panel(page)
    assert page.locator("#clawPcConsentAck").is_checked() is False
    assert page.locator("#clawPcConsentConfirm").is_disabled()
    assert not errors, errors
    page.close()


def test_escape_closes_without_side_effect(browser, server):
    page, errors = open_claw(browser, server)
    install_port(page)
    open_panel(page)
    page.locator("#clawPcConsentAck").check()
    page.locator("#clawPcConsentToggle").press("Escape")
    assert page.locator("#clawPcConsentPanel").is_hidden()
    assert calls(page) == []
    assert not errors, errors
    page.close()


# --- 3. both explicit approval AND verified activation required --------------


def test_progress_requires_acknowledgement_and_verified_activation(browser, server):
    page, errors = open_claw(browser, server)
    # Verified server feature is NOT active: acknowledgement alone cannot proceed.
    install_port(page, feature_activated=False)
    open_panel(page)
    page.locator("#clawPcConsentAck").check()
    assert page.locator("#clawPcConsentConfirm").is_disabled()
    assert "준비되지 않았습니다" in page.locator("#clawPcConsentStatus").inner_text()
    assert calls(page) == []
    # Feature active but NOT acknowledged: still blocked.
    install_port(page, feature_activated=True)
    page.locator("#clawPcConsentAck").uncheck()
    assert page.locator("#clawPcConsentConfirm").is_disabled()
    page.locator("#clawPcConsentAck").check()
    assert page.locator("#clawPcConsentConfirm").is_enabled()
    assert calls(page) == []
    assert not errors, errors
    page.close()


# --- 4. wrong target / product blocked --------------------------------------


def test_unknown_target_or_product_blocks_progress(browser, server):
    page, errors = open_claw(browser, server)
    # No target confirmed at all.
    install_port(page, device_id=None, device_name=None)
    open_panel(page)
    page.locator("#clawPcConsentAck").check()
    assert page.locator("#clawPcConsentConfirm").is_disabled()
    assert "PC를 선택" in page.locator("#clawPcConsentStatus").inner_text()
    # A B66 quote account is a separate product with separate PC authority.
    install_port(page, product_id="b66-quote")
    page.locator("#clawPcConsentAck").uncheck()
    page.locator("#clawPcConsentAck").check()
    assert page.locator("#clawPcConsentConfirm").is_disabled()
    assert "다른 서비스" in page.locator("#clawPcConsentStatus").inner_text()
    assert "B66" not in page.locator("#clawPcConsentStatus").inner_text()
    # An unknown product is also blocked.
    install_port(page, product_id="")
    page.locator("#clawPcConsentAck").uncheck()
    page.locator("#clawPcConsentAck").check()
    assert page.locator("#clawPcConsentConfirm").is_disabled()
    assert calls(page) == []
    assert not errors, errors
    page.close()


# --- 5. duplicate submit prevented ------------------------------------------


def test_double_click_sends_exactly_one_request(browser, server):
    page, errors = open_claw(browser, server)
    install_port(page, defer=True)
    open_panel(page)
    page.locator("#clawPcConsentAck").check()
    page.locator("#clawPcConsentConfirm").click()
    page.wait_for_function("window.__consentCalls.length === 1")
    # Second click while the first is in flight must be ignored.
    page.locator("#clawPcConsentConfirm").click(force=True)
    page.wait_for_timeout(60)
    assert len(calls(page)) == 1
    body = calls(page)[0]["body"]
    assert body == {"device_id": "pc1", "confirmed": True, "confirmation_version": CONSENT_VERSION}
    page.evaluate("window.__resolveGrant({ok:true,consent:{device_id:'pc1',consent_id:'consent-1',dispatch_authorized:false}})")
    page.wait_for_function("document.querySelector('#clawPcConsentStatus').textContent.includes('동의가 저장되었습니다')")
    assert not errors, errors
    page.close()


# --- 6. revoke / expiry honest states ---------------------------------------


@pytest.mark.parametrize("code,expected", [
    ("connector_enrollment_explicit_consent_required", "거부"),
    ("enrollment_consent_withdrawn", "철회"),
    ("enrollment_consent_expired", "만료"),
])
def test_server_refusals_map_to_honest_states(browser, server, code, expected):
    page, errors = open_claw(browser, server)
    install_port(page, grant_result={"ok": False, "status": 403, "error": {"code": code}})
    open_panel(page)
    page.locator("#clawPcConsentAck").check()
    page.locator("#clawPcConsentConfirm").click()
    page.wait_for_function(
        "document.querySelector('#clawPcConsentStatus').textContent.includes(" + json.dumps(expected) + ")"
    )
    # A refusal is never shown as a stored consent or an online PC.
    text = page.locator("#clawPcConsentStatus").inner_text()
    assert "저장되었습니다" not in text
    assert "온라인" not in text
    assert not errors, errors
    page.close()


# --- 7. HTML injection / secret leakage prevented ---------------------------


def test_server_markup_and_secrets_are_never_rendered(browser, server):
    page, errors = open_claw(browser, server)
    name = '<img src=x onerror="window.pwned=true">'
    secret = "do-not-render-secret"
    install_port(page, device_name=name)
    open_panel(page)
    assert page.locator("#clawPcConsentPanel img").count() == 0
    assert page.locator("#clawPcConsentTarget").inner_text() == name
    assert page.evaluate("window.pwned === true") is False
    # A server-supplied secret in the receipt is never surfaced.
    page.evaluate("""() => {
      window.__consentCalls = [];
      window.__padiemPcEnrollmentConsentPort.grantConsent = (body) =>
        Promise.resolve({ok:true, consent:{device_id:"pc1", consent_id:"consent-1", dispatch_authorized:false,
          token: arguments0, credential: arguments0}});
    }""".replace("arguments0", json.dumps(secret)))
    page.locator("#clawPcConsentAck").check()
    page.locator("#clawPcConsentConfirm").click()
    page.wait_for_function("document.querySelector('#clawPcConsentStatus').textContent.length > 0")
    assert secret not in page.locator("#clawPcConsentPanel").inner_text()
    assert not errors, errors
    page.close()


# --- 8. no automatic P01 READ/WRITE approval --------------------------------


def test_stored_consent_is_never_online_or_execution_approval(browser, server):
    page, errors = open_claw(browser, server)
    install_port(page, grant_result=grant_ok())
    open_panel(page)
    page.locator("#clawPcConsentAck").check()
    page.locator("#clawPcConsentConfirm").click()
    page.wait_for_function("document.querySelector('#clawPcConsentStatus').textContent.includes('동의가 저장되었습니다')")
    text = page.locator("#clawPcConsentPanel").inner_text()
    # The honest disclaimer is present and no positive connection claim is made.
    assert "온라인 상태를 뜻하지 않습니다" in text
    assert "연결되었습니다" not in text
    assert "승인되었습니다" not in text
    # A receipt claiming execution authority is refused, not displayed as success.
    # A fresh panel session is required: the stored consent seals the current one.
    page.locator("#clawPcConsentCancel").click()
    install_port(page, grant_result={"ok": True, "consent": {"device_id": "pc1", "dispatch_authorized": True}})
    open_panel(page)
    page.locator("#clawPcConsentAck").check()
    page.locator("#clawPcConsentConfirm").click()
    page.wait_for_function("document.querySelector('#clawPcConsentStatus').textContent.includes('저장하지 못했습니다')")
    assert not errors, errors
    page.close()


def test_grant_without_canonical_consent_id_fails_closed(browser, server):
    """A receipt that cannot be correlated or revoked is not a stored consent."""
    page, errors = open_claw(browser, server)
    install_port(page, grant_result={"ok": True, "consent": {
        "device_id": "pc1", "dispatch_authorized": False,
    }})
    open_panel(page)
    page.locator("#clawPcConsentAck").check()
    page.locator("#clawPcConsentConfirm").click()
    page.wait_for_function(
        "document.querySelector('#clawPcConsentStatus').textContent.includes('저장하지 못했습니다')"
    )
    assert "저장되었습니다" not in page.locator("#clawPcConsentStatus").inner_text()
    assert len(calls(page)) == 1
    assert not errors, errors
    page.close()


# --- 9. ko/en and mobile accessibility --------------------------------------


def test_locale_switch_and_mobile_touch_targets(browser, server):
    page, errors = open_claw(browser, server, width=390)
    install_port(page)
    open_panel(page)
    assert page.locator("#clawPcConsentToggle").inner_text().startswith("내 PC 등록 동의")
    # Disclosure starts collapsed; the detail copy is not rendered as visible text.
    assert page.locator(".claw-pc-consent-details").evaluate("el => el.open") is False
    page.evaluate("document.documentElement.lang = 'en'")
    page.wait_for_function("document.querySelector('#clawPcConsentToggle').textContent.startsWith('PC enrollment consent')")
    assert page.locator("#clawPcConsentTitle").inner_text() == "Connect this computer to Padiem"
    # Expanding the disclosure reveals the allowed/denied detail in the active locale.
    page.locator(".claw-pc-consent-details-summary").click()
    assert page.locator(".claw-pc-consent-details").evaluate("el => el.open") is True
    panel_text = page.locator("#clawPcConsentPanel").inner_text()
    assert "Allowed once connected" in panel_text
    assert "Not allowed by connecting" in panel_text
    assert "separate P01 approval" in panel_text
    # Touch-target floor of 44px on the interactive controls.
    for selector in ("#clawPcConsentToggle", "#clawPcConsentConfirm", "#clawPcConsentCancel",
                     ".claw-pc-consent-close", ".claw-pc-consent-ack"):
        box = page.locator(selector).bounding_box()
        assert box is not None and box["height"] >= 44, (selector, box)
    # Dialog-ish region is labelled and the toggle exposes expanded state.
    assert page.locator("#clawPcConsentPanel").get_attribute("aria-labelledby") == "clawPcConsentTitle"
    assert page.locator("#clawPcConsentToggle").get_attribute("aria-expanded") == "true"
    assert page.locator("#clawPcConsentStatus").get_attribute("aria-live") == "polite"
    assert not errors, errors
    page.close()


# --- 6b. revoke copy matches the reviewed #4476 contract --------------------


def test_revoke_copy_matches_the_reviewed_contract(browser, server):
    """#4476: withdrawal prevents outstanding/new enrollment but does NOT itself
    imply the bound device is offline/unpaired or that a live session ended."""
    page, errors = open_claw(browser, server)
    install_port(page)
    open_panel(page)
    page.locator(".claw-pc-consent-details-summary").click()
    ko = page.locator(".claw-pc-consent-revoke").inner_text()
    assert "별도의 검토된 해제 절차" in ko
    assert "즉시 끊기지는 않습니다" in ko
    # The old overclaim must be gone.
    assert "즉시 중단" not in ko
    assert "새 작업이 즉시" not in ko
    page.evaluate("document.documentElement.lang = 'en'")
    page.wait_for_function(
        "document.querySelector('.claw-pc-consent-revoke').textContent.includes('separate reviewed release path')"
    )
    en = page.locator(".claw-pc-consent-revoke").inner_text()
    assert "does not disconnect it immediately" in en
    assert "immediately stops" not in en
    assert not errors, errors
    page.close()


# --- 10. stale-response generation guard ------------------------------------


def test_stale_response_after_close_and_reopen_cannot_change_screen(browser, server):
    """A response from before a close/reopen must not settle the new panel."""
    page, errors = open_claw(browser, server)
    install_port(page, defer=True)
    open_panel(page)
    page.locator("#clawPcConsentAck").check()
    page.locator("#clawPcConsentConfirm").click()
    page.wait_for_function("window.__consentCalls.length === 1")
    page.locator("#clawPcConsentCancel").click()
    open_panel(page)
    assert page.locator("#clawPcConsentAck").is_checked() is False
    page.evaluate("window.__resolveGrant({ok:true,consent:{device_id:'pc1',consent_id:'consent-1',dispatch_authorized:false}})")
    page.wait_for_timeout(80)
    assert "저장되었습니다" not in page.locator("#clawPcConsentStatus").inner_text()
    assert page.locator("#clawPcConsentAck").is_checked() is False
    assert page.locator("#clawPcConsentConfirm").is_disabled()
    assert page.locator("#clawPcConsentPanel").get_attribute("aria-busy") is None
    assert not errors, errors
    page.close()


def test_stale_response_after_escape_cannot_change_screen(browser, server):
    page, errors = open_claw(browser, server)
    install_port(page, defer=True)
    open_panel(page)
    page.locator("#clawPcConsentAck").check()
    page.locator("#clawPcConsentConfirm").click()
    page.wait_for_function("window.__consentCalls.length === 1")
    page.locator("#clawPcConsentToggle").press("Escape")
    assert page.locator("#clawPcConsentPanel").is_hidden()
    page.evaluate("window.__resolveGrant({ok:true,consent:{device_id:'pc1',consent_id:'consent-1',dispatch_authorized:false}})")
    page.wait_for_timeout(80)
    assert page.locator("#clawPcConsentPanel").is_hidden()
    open_panel(page)
    assert page.locator("#clawPcConsentAck").is_checked() is False
    assert page.locator("#clawPcConsentConfirm").is_disabled()
    assert not errors, errors
    page.close()


def test_stale_response_after_account_change_cannot_change_screen(browser, server):
    page, errors = open_claw(browser, server)
    install_port(page, defer=True)
    open_panel(page)
    page.locator("#clawPcConsentAck").check()
    page.locator("#clawPcConsentConfirm").click()
    page.wait_for_function("window.__consentCalls.length === 1")
    page.evaluate('window.dispatchEvent(new CustomEvent("padiem:account-changed"))')
    page.evaluate("window.__resolveGrant({ok:true,consent:{device_id:'pc1',consent_id:'consent-1',dispatch_authorized:false}})")
    page.wait_for_timeout(80)
    assert "저장되었습니다" not in page.locator("#clawPcConsentStatus").inner_text()
    assert page.locator("#clawPcConsentAck").is_checked() is False
    assert page.locator("#clawPcConsentConfirm").is_disabled()
    assert not errors, errors
    page.close()


def test_stale_response_after_leaving_claw_cannot_change_screen(browser, server):
    page, errors = open_claw(browser, server)
    install_port(page, defer=True)
    open_panel(page)
    page.locator("#clawPcConsentAck").check()
    page.locator("#clawPcConsentConfirm").click()
    page.wait_for_function("window.__consentCalls.length === 1")
    page.evaluate("document.querySelector('.app-shell').setAttribute('data-state', 'chat')")
    page.locator("#clawPcEnrollmentConsent").wait_for(state="hidden")
    page.evaluate("window.__resolveGrant({ok:true,consent:{device_id:'pc1',consent_id:'consent-1',dispatch_authorized:false}})")
    page.wait_for_timeout(80)
    assert page.locator("#clawPcConsentPanel").is_hidden()
    # Returning to Claw shows a clean default-OFF panel, never a stored consent.
    page.evaluate("document.querySelector('.app-shell').setAttribute('data-state', 'claw')")
    page.locator("#clawPcConsentToggle").wait_for(state="visible")
    open_panel(page)
    assert page.locator("#clawPcConsentAck").is_checked() is False
    assert page.locator("#clawPcConsentConfirm").is_disabled()
    assert "저장되었습니다" not in page.locator("#clawPcConsentStatus").inner_text()
    assert not errors, errors
    page.close()


def test_stored_consent_is_terminal_across_locale_change(browser, server):
    """A settled consent must not be re-armed (or re-sent) by a locale change."""
    page, errors = open_claw(browser, server)
    install_port(page, grant_result=grant_ok())
    open_panel(page)
    page.locator("#clawPcConsentAck").check()
    page.locator("#clawPcConsentConfirm").click()
    page.wait_for_function("document.querySelector('#clawPcConsentStatus').textContent.includes('동의가 저장되었습니다')")
    assert page.locator("#clawPcConsentConfirm").is_disabled()
    page.evaluate("document.documentElement.lang = 'en'")
    page.wait_for_function("document.querySelector('#clawPcConsentStatus').textContent.includes('Consent stored')")
    # The stored-consent status is re-rendered in the new locale, not replaced by
    # a readiness prompt, and the confirm stays disabled.
    assert "does not mean the PC is connected" in page.locator("#clawPcConsentStatus").inner_text()
    assert page.locator("#clawPcConsentConfirm").is_disabled()
    page.locator("#clawPcConsentConfirm").click(force=True)
    page.wait_for_timeout(80)
    assert len(calls(page)) == 1
    assert not errors, errors
    page.close()
