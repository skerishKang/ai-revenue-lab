"""Real Chromium mask checks in a fresh, signed-out local profile."""
import html
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"

# The loopback harness rewrites this placeholder to the serving origin, so the
# fixture can reference its CSS and modules without file:// (a page served
# over http:// cannot load file:// subresources).
FIXTURE_BASE_PLACEHOLDER = "__FIXTURE_BASE__"


def _terminate(process):
    if os.name == "nt":
        if process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=10, check=False)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=10)


def capture_fixture(command, tmp_path, *, timeout=40, fixture_file=None, static_root=None):
    """Wait for the fixture report, then close only this test's process tree.

    Chromium can dump the completed DOM and leave its process/pipes open on
    CI. Its shutdown is not the browser assertion: the explicit report is.
    File streams also keep inherited pipe handles from blocking collection.

    With `fixture_file` the page is served from a loopback HTTP server and the
    page itself posts the finished report to the same server, so completion is
    a real readiness signal that arrives while the browser is still running.
    The fixed deadline then only guards a hung browser, never a slow one, and
    the report no longer depends on --dump-dom flushing or process exit.

    Without `fixture_file` the raw `--dump-dom` stdout protocol is kept, and
    where the Playwright Python package is present the report is awaited
    through a live DOM condition instead of the fixed wall-clock deadline.
    """
    if fixture_file is not None:
        return _capture_over_loopback(command, tmp_path, timeout=timeout,
                                      fixture_file=fixture_file, static_root=static_root)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return _capture_with_subprocess(command, tmp_path, timeout=timeout,
                                        output=tmp_path / "browser-output.txt")
    fixture_url = command[-1]
    executable = command[0]
    args = [arg for arg in command[1:-1]
            if arg != "--dump-dom"
            and not arg.startswith("--virtual-time-budget")
            and not arg.startswith("--user-data-dir")]
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True, executable_path=executable, args=args)
        try:
            page = browser.new_page()
            page.goto(fixture_url, wait_until="domcontentloaded", timeout=timeout * 1000)
            page.wait_for_function(
                "() => { const el = document.getElementById('report');"
                " return Boolean(el && el.textContent.trim()); }",
                timeout=timeout * 1000,
            )
            raw = page.evaluate("() => document.getElementById('report').textContent")
        finally:
            browser.close()
    try:
        report = json.loads(html.unescape(raw))
    except (ValueError, TypeError):
        report = None
    if not (isinstance(report, dict) and type(report.get("ok")) is bool):
        raise AssertionError("The isolated fixture exited without a completed report")
    return report


class _LoopbackReportServer(ThreadingHTTPServer):
    daemon_threads = True


def _capture_over_loopback(command, tmp_path, *, timeout, fixture_file, static_root):
    """Serve the fixture over loopback and wait for the page's own report.

    The page posts its finished report to the same origin (navigator
    sendBeacon), so the harness learns the outcome while Chromium is still
    running and then closes only this test's process tree. A process that dies
    without reporting fails fast; a hung process hits the fixed deadline,
    which is a hang guard, not the completion mechanism.
    """
    captured = {}
    completed = threading.Event()
    serving = {"base": ""}

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep the test's own stdout clean
            pass

        def _reply(self, code, body, ctype):
            self.send_response(code)
            if ctype:
                self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/session.html":
                body = fixture_file.read_bytes().replace(
                    FIXTURE_BASE_PLACEHOLDER.encode("ascii"), serving["base"].encode("ascii"))
                self._reply(200, body, "text/html")
                return
            name = path.strip("/")
            if static_root is not None and name and "/" not in name and ".." not in name:
                candidate = static_root / name
                if candidate.is_file():
                    ctype = "text/css" if name.endswith(".css") else "application/javascript"
                    self._reply(200, candidate.read_bytes(), ctype)
                    return
            self._reply(404, b"missing", "text/plain")

        def do_POST(self):
            if self.path.split("?", 1)[0] != "/report":
                self._reply(404, b"missing", "text/plain")
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length)
            try:
                report = json.loads(raw.decode("utf-8", "replace"))
            except (ValueError, TypeError):
                report = None
            if isinstance(report, dict) and type(report.get("ok")) is bool:
                captured["report"] = report
                completed.set()
            self._reply(204, b"", None)

    server = _LoopbackReportServer(("127.0.0.1", 0), _Handler)
    serving["base"] = f"http://127.0.0.1:{server.server_address[1]}"
    rewritten = list(command)
    rewritten[-1] = serving["base"] + "/session.html"
    rewritten = [arg for arg in rewritten
                 if arg != "--dump-dom" and not arg.startswith("--virtual-time-budget")]
    output = tmp_path / "browser-output.txt"
    # Start serving before the browser exists: the report endpoint must be
    # listening when the page loads. Spawning Chromium first left a window
    # where an early page request raced the server thread start and the beacon
    # was lost, turning a correct page into a deadline failure under load.
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    with output.open("w", encoding="utf-8") as stdout:
        process = subprocess.Popen(rewritten, stdout=stdout,
                                   stderr=subprocess.DEVNULL, start_new_session=os.name != "nt")
        try:
            reported = False
            exited = False
            deadline = time.monotonic() + timeout
            while True:
                if completed.wait(timeout=0.05):
                    reported = True
                    break
                if process.poll() is not None:
                    exited = True
                    break
                if time.monotonic() >= deadline:
                    break
        finally:
            server.shutdown()
            _terminate(process)
            server.server_close()
    if reported:
        return captured["report"]
    if exited:
        raise AssertionError("The isolated fixture exited without a completed report")
    raise AssertionError("The isolated fixture did not complete before its deadline")


def _capture_with_subprocess(command, tmp_path, *, timeout, output):
    with output.open("w", encoding="utf-8") as stdout:
        process = subprocess.Popen(command, stdout=stdout,
                                   stderr=subprocess.DEVNULL, start_new_session=os.name != "nt")
        try:
            deadline = time.monotonic() + timeout
            while True:
                exit_code = process.poll()
                rendered = output.read_text(encoding="utf-8", errors="replace")
                if exit_code not in (None, 0):
                    raise AssertionError("The isolated fixture process failed")
                match = re.search(r'<pre id="report">(.*?)</pre>', rendered, re.S)
                if match:
                    try:
                        report = json.loads(html.unescape(match[1]))
                    except (ValueError, TypeError):
                        report = None
                    if isinstance(report, dict) and type(report.get("ok")) is bool:
                        return report
                if exit_code is not None:
                    raise AssertionError("The isolated fixture exited without a completed report")
                if time.monotonic() >= deadline:
                    raise AssertionError("The isolated fixture did not complete before its deadline")
                time.sleep(.02)
        finally:
            _terminate(process)


def chromium():
    configured = os.environ.get("PADIEM_TEST_CHROMIUM")
    if configured and Path(configured).is_file():
        return configured
    for name in ("chromium", "chromium-browser", "google-chrome"):
        if found := shutil.which(name):
            return found
    cache = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    candidates = sorted(cache.glob("chromium-*/chrome-win*/chrome.exe"), reverse=True)
    if candidates:
        return str(candidates[0])
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as runtime:
            path = runtime.chromium.executable_path
            if Path(path).is_file():
                return path
    except ImportError:
        pass
    pytest.skip("A local Chromium binary is required for the mask integration test")


@pytest.mark.parametrize("supported", [True, False])
def test_actual_mask_and_no_multiline_fallback_transformation(tmp_path, supported):
    setup = """
window.PadiemAuthSession = {get: () => ({authenticated: true, ownerKey: 'fixture'})};
window.PadiemChatConversationState = {getConversationId: () => 'fixture-conversation'};
window.__padiemLocale = {text: (key) => key};
let calls = [], resolveRequest;
window.fetch = (url, options) => { calls.push({url, options}); return new Promise((resolve) => {resolveRequest = resolve;}); };
"""
    if not supported:
        setup += "Object.defineProperty(CSS, 'supports', {value: () => false});\n"
    scripts = "".join(
        '<script src="' + FIXTURE_BASE_PLACEHOLDER + '/' + name + '"></script>'
        for name in ("chat-transport.js", "chat-pc-session-module.js")
    )
    exercise = r"""
document.addEventListener('DOMContentLoaded', async () => {
  const check = (condition) => { if (!condition) throw new Error('browser contract failed'); };
  const report = (payload) => {
    const el = document.getElementById('report');
    el.textContent = JSON.stringify(payload);
    // Loopback harness channel: same-origin beacon, untouched by the fetch
    // stub above, so the harness learns the outcome while we are still alive.
    if (navigator.sendBeacon) {
      navigator.sendBeacon('/report', new Blob([el.textContent], {type: 'text/plain'}));
    }
  };
  try {
    const api = window.PadiemChatPcSessionModule;
    const root = document.getElementById('chatPcSessionPanel');
    const job = 'dsp_' + 'a'.repeat(32);
    api.render({decision_status:'pc_session', conversation_id:'fixture-conversation',
      pc_session:{job_id:job, session:job.slice(4), alive:true, status:'completed'}}, api.captureScope());
    const field = root.querySelector('.pc-session-secret');
    for (const node of root.querySelectorAll('code, p, pre, label, button')) {
      check(parseFloat(getComputedStyle(node).fontSize) >= 14);
    }
    for (const node of root.querySelectorAll('button')) {
      const box = node.getBoundingClientRect();
      check(box.width >= 44 && box.height >= 44);
    }
    const supported = __SUPPORTED__;
    check(field.value === '');
    if (supported) {
      check(field.tagName === 'TEXTAREA');
      check(getComputedStyle(field).getPropertyValue('-webkit-text-security') === 'disc');
      // Use an actual line feed, as a pasted multiline value would contain.
      field.value = 'fixture-one' + String.fromCharCode(10) + 'fixture-two';
      const raw = field.value;
      check(raw.includes(String.fromCharCode(10)));
      check(!root.outerHTML.includes(raw) && !root.textContent.includes(raw));
      root.querySelector('[data-session-label="send-secret"]').click();
      check(field.value === ''); check(calls.length === 1);
      check(JSON.parse(calls[0].options.body).text === raw);
      check(JSON.parse(calls[0].options.body).secret === true);
      resolveRequest({ok:true,status:200,json:async()=>({conversation_id:'fixture-conversation',
        decision_status:'pc_session_confirm',pc_session:{job_id:job,status:'waiting_approval',confirmation_required:true}})});
      await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
      check(field.value === '' && !root.outerHTML.includes(raw));
    } else {
      check(field.tagName === 'INPUT' && field.type === 'password');
      field.value = 'old';
      const data = new DataTransfer(); data.setData('text/plain', 'first' + String.fromCharCode(10) + 'second');
      const event = new ClipboardEvent('paste', {clipboardData:data, bubbles:true, cancelable:true});
      field.dispatchEvent(event);
      check(event.defaultPrevented && field.value === '' && calls.length === 0);
      check(root.textContent.includes('pc-session-multiline-unavailable'));
    }
    report({ok:true,supported});
  } catch (_) { report({ok:false}); }
});
""".replace("__SUPPORTED__", json.dumps(supported))
    fixture = tmp_path / "session.html"
    fixture.write_text('<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="'
                       + FIXTURE_BASE_PLACEHOLDER + '/chat-pc-session.css">'
                       '<section id="chatPcSessionPanel" hidden></section>'
                       '<pre id="report"></pre><script>' + setup + '</script>' + scripts
                       + '<script>' + exercise + '</script>', encoding="utf-8")
    report = capture_fixture([
        chromium(), "--headless", "--disable-gpu", "--disable-background-networking",
        # Match Playwright's isolated test launch on CI hosts without user
        # namespaces or a large /dev/shm. This profile contains only fixtures.
        "--no-sandbox", "--disable-dev-shm-usage",
        "--disable-component-update", "--disable-sync", "--no-first-run", "--no-default-browser-check",
        "--user-data-dir=" + str(tmp_path / "fresh-profile"), fixture.as_uri(),
        # Completion is the beacon signal, which lands in 1-25s normally; the
        # deadline is only the hung-browser guard, so it is sized above the
        # slowest legitimate cold start measured on CI (38.4s under load).
    ], tmp_path, timeout=120, fixture_file=fixture, static_root=STATIC)
    assert report == {"ok": True, "supported": supported}
