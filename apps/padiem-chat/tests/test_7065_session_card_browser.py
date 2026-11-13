"""Real Chromium mask checks in a fresh, signed-out local profile."""
import html
import json
import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"


def capture_fixture(command, tmp_path, *, timeout=40):
    """Wait for the fixture report, then close only this test's process tree.

    Chromium can dump the completed DOM and leave its process/pipes open on
    CI. Its shutdown is not the browser assertion: the explicit report is.
    File streams also keep inherited pipe handles from blocking collection.
    """
    output = tmp_path / "browser-output.txt"
    with output.open("w", encoding="utf-8") as stdout:
        process = subprocess.Popen(command, stdout=stdout, stderr=subprocess.DEVNULL,
                                   start_new_session=os.name != "nt")
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
        '<script src="' + (STATIC / name).as_uri() + '"></script>'
        for name in ("chat-transport.js", "chat-pc-session-module.js")
    )
    exercise = r"""
document.addEventListener('DOMContentLoaded', async () => {
  const check = (condition) => { if (!condition) throw new Error('browser contract failed'); };
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
    document.getElementById('report').textContent = JSON.stringify({ok:true,supported});
  } catch (_) { document.getElementById('report').textContent = JSON.stringify({ok:false}); }
});
""".replace("__SUPPORTED__", json.dumps(supported))
    fixture = tmp_path / "session.html"
    fixture.write_text('<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="'
                       + (STATIC / "chat-pc-session.css").as_uri() + '">'
                       '<section id="chatPcSessionPanel" hidden></section>'
                       '<pre id="report"></pre><script>' + setup + '</script>' + scripts
                       + '<script>' + exercise + '</script>', encoding="utf-8")
    report = capture_fixture([
        chromium(), "--headless", "--disable-gpu", "--disable-background-networking",
        # Match Playwright's isolated test launch on CI hosts without user
        # namespaces or a large /dev/shm. This profile contains only fixtures.
        "--no-sandbox", "--disable-dev-shm-usage",
        "--disable-component-update", "--disable-sync", "--no-first-run", "--no-default-browser-check",
        "--user-data-dir=" + str(tmp_path / "fresh-profile"), "--virtual-time-budget=3000",
        "--dump-dom", fixture.as_uri(),
    ], tmp_path)
    assert report == {"ok": True, "supported": supported}
