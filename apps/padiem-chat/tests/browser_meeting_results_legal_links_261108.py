"""대표 결정 2026-11-08: meeting results show only when they exist, the help
copy rides the shared chip tooltip, and the legal links live in the sidebar
bottom (never under the starter cards) with the login-dialog consent line.

Browser-level because every assertion here is about what a real page shows:
hidden vs disabled, the mode switch, the elapsed timer, and the guest vs
signed-in sidebar. The static sheets are byte-pinned elsewhere.
"""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import threading
import unittest

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"

SIGNED_IN_STATUS = {
    "ok": True, "authenticated": True, "ready": True,
    "user": {"name": "홍대표", "email": "rep@example.com"},
}
GUEST_STATUS = {"ok": True, "authenticated": False, "ready": True}

FAKE_CAPTURE = """
  const fakeStream = { getTracks: () => [{ stop() {} }] };
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true, value: { getUserMedia: async () => fakeStream }
  });
  class FakeRecorder {
    static isTypeSupported() { return true; }
    constructor(stream) { this.state = "inactive"; }
    start() { this.state = "recording"; }
    stop() {
      this.state = "inactive";
      this.ondataavailable?.({ data: new Blob(["fake-audio"], { type: "audio/webm" }) });
      this.onstop?.({});
    }
  }
  window.MediaRecorder = FakeRecorder;
  // Headless Chromium ships no webkitSpeechRecognition; the fake recognizer
  // commits one final line the moment it starts, the same shape the live
  // SpeechRecognition events carry.
  class FakeRecognition {
    constructor() { this.continuous = false; this.interimResults = false; this.lang = ""; }
    start() {
      this.onresult?.({
        resultIndex: 0,
        results: [ { 0: { transcript: "운영 회의 결정사항 정리" }, isFinal: true, length: 1 } ],
      });
    }
    stop() { this.onend?.(); }
    abort() { this.onend?.(); }
  }
  window.SpeechRecognition = FakeRecognition;
  window.webkitSpeechRecognition = FakeRecognition;
"""


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *args) -> None:
        pass


def serve() -> tuple[ThreadingHTTPServer, int]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


class MeetingResultsAndLegalLinks(unittest.TestCase):
    def run_page(self, auth_status: dict, run_checks):
        httpd, port = serve()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                context = browser.new_context(viewport={"width": 1440, "height": 900})
                page = context.new_page()
                page.on("pageerror", lambda err: self.fail(f"page error: {err}"))

                def route_handler(route):
                    url = route.request.url
                    if url.endswith("/api/auth/status"):
                        route.fulfill(status=200, content_type="application/json",
                                      body=json.dumps(auth_status))
                    elif "/api/claw/meetings" in url and route.request.method == "GET":
                        route.fulfill(status=200, content_type="application/json",
                                      body=json.dumps({"ok": True, "meetings": []}))
                    elif "/api/claw/meeting/drive-upload-session" in url:
                        route.fulfill(status=503, content_type="application/json",
                                      body=json.dumps({"error": {"code": "drive_write_unavailable"}}))
                    elif "/api/" in url:
                        route.fulfill(status=404, content_type="application/json", body="{}")
                    else:
                        route.continue_()

                context.route("**/*", route_handler)
                context.add_init_script(FAKE_CAPTURE)
                page.goto(f"http://127.0.0.1:{port}/")
                page.wait_for_timeout(1200)
                run_checks(page)
                browser.close()
        finally:
            httpd.shutdown()

    def open_meeting(self, page):
        page.click("#meetingNavButton")
        page.wait_for_selector("#meetingView:not([hidden])")

    def test_guest_first_screen_shows_the_links_in_the_sidebar_only(self):
        def checks(page):
            links = page.locator(".sidebar-legal-links")
            assert links.is_visible(), "sidebar bottom carries the legal line"
            assert links.locator('a[href="./privacy.html"]').is_visible()
            assert links.locator('a[href="./terms.html"]').is_visible()
            # Above the account row (guest login button), not under the cards.
            account_top = page.locator(".sidebar-account").bounding_box()["y"]
            links_top = links.bounding_box()["y"]
            assert links_top < account_top
            assert page.locator(".guest-legal-links").count() == 0
            # The login dialog carries the one-line consent with both nouns linked.
            page.click("#loginButton")
            page.wait_for_selector("#authDialog[open]")
            consent = page.locator(".auth-legal-consent")
            assert consent.is_visible()
            assert "동의하는 것으로 봅니다" in consent.inner_text()
            assert consent.locator('a[href="./terms.html"]').is_visible()
            assert consent.locator('a[href="./privacy.html"]').is_visible()
        self.run_page(GUEST_STATUS, checks)

    def test_signed_in_sidebar_still_shows_the_links(self):
        def checks(page):
            assert page.locator(".sidebar-legal-links").is_visible()
            assert page.locator(".sidebar-account").is_visible()
        self.run_page(SIGNED_IN_STATUS, checks)

    def test_meeting_results_hidden_while_waiting_and_recording(self):
        def checks(page):
            self.open_meeting(page)
            exports = page.locator("#meetingExports")
            assert not exports.is_visible(), "no results before the meeting starts"
            assert not page.locator("#meetingUnsavedNote").is_visible()
            # record-only mode never shows the transcript panel.
            assert not page.locator("#meetingTranscriptBlock").is_visible()
            assert page.locator("#meetingStart").is_enabled()
            # The help copy lives on the ? chip, not as two loose paragraphs.
            assert page.locator(".meeting-help").count() == 0
            assert page.locator(".meeting-storage-note").count() == 0
            assert page.locator("#meetingHelpToggle").is_visible()

            page.click("#meetingStart")
            page.wait_for_timeout(1500)
            assert not exports.is_visible(), "results stay hidden while recording"
            assert not page.locator("#meetingTranscriptBlock").is_visible(), (
                "record-only mode never shows the transcript panel, even live")
            assert ":" in page.locator("#meetingElapsed").inner_text()
            elapsed = page.locator("#meetingElapsed")
            assert elapsed.is_visible(), "the status line ticks while recording"
            first = elapsed.inner_text()
            assert ":" in first, first
            page.wait_for_timeout(1600)
            assert elapsed.inner_text() != first, "the elapsed value advances"
        self.run_page(SIGNED_IN_STATUS, checks)

    def test_stopped_record_only_meeting_shows_only_audio_results(self):
        def checks(page):
            self.open_meeting(page)
            page.click("#meetingStart")
            page.wait_for_timeout(1500)
            page.click("#meetingStop")
            page.wait_for_timeout(600)
            exports = page.locator("#meetingExports")
            assert exports.is_visible(), "results appear after the meeting stops"
            assert page.locator("#meetingDownloadAudio").is_visible()
            assert page.locator("#meetingSaveAudioDrive").is_visible()
            assert page.locator("#meetingDownloadText").is_hidden()
            assert page.locator("#meetingSaveTextDrive").is_hidden()
            assert page.locator("#meetingDraftInClaw").is_hidden()
            assert page.locator("#meetingUnsavedNote").is_visible()
            assert not page.locator("#meetingTranscriptBlock").is_visible()
            # The Drive button stays visible without the write grant; pressing
            # it explains and links to the connection screen.
            page.click("#meetingSaveAudioDrive")
            page.wait_for_timeout(800)
            status_text = page.locator("#meetingStatusText").inner_text()
            assert "쓰기 권한" in status_text
            assert page.locator("#meetingStatusText a", has_text="연결 화면으로 이동").is_visible()
        self.run_page(SIGNED_IN_STATUS, checks)

    def test_stopped_transcribe_meeting_shows_only_text_results(self):
        def checks(page):
            self.open_meeting(page)
            page.check('input[name="meetingMode"][value="transcribe"]')
            # The transcript panel belongs to the transcription modes.
            assert page.locator("#meetingTranscriptBlock").is_visible()
            page.click("#meetingStart")
            page.wait_for_timeout(1200)
            page.click("#meetingStop")
            page.wait_for_timeout(600)
            exports = page.locator("#meetingExports")
            assert exports.is_visible()
            assert page.locator("#meetingDownloadText").is_visible()
            assert page.locator("#meetingSaveTextDrive").is_visible()
            assert page.locator("#meetingDraftInClaw").is_visible()
            assert page.locator("#meetingDownloadAudio").is_hidden()
            assert page.locator("#meetingSaveAudioDrive").is_hidden()
        self.run_page(SIGNED_IN_STATUS, checks)


if __name__ == "__main__":
    unittest.main()
