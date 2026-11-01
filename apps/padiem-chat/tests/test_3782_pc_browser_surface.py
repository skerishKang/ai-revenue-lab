"""Real DOM display of owner-scoped PNGs and existing PC progress lifecycle."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import zlib

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"
SOURCE = STATIC / "pc-browser-progress.js"
DISPATCH = "dsp_" + "a" * 32
OTHER = "dsp_" + "b" * 32
MARKER = "[pc-browser-capture:" + DISPATCH + "]"


def _chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


PNG = (b"\x89PNG\r\n\x1a\n"
       + _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
       + _chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\xff"))
       + _chunk(b"IEND", b""))
SHA = hashlib.sha256(PNG).hexdigest()
HTML = """<!doctype html><html lang=ko><body><div id=messageList>
<article data-lifecycle=streaming><span data-runtime-label></span>
<div class=assistant-content><p id=answer></p></div></article></div></body></html>"""


def test_run_identity_comes_from_response_header_not_progress_frame():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the shipped JS contract")
    script = r"""
const api=require(process.argv[1]);
const response=value=>({headers:{get:name=>name==='X-Padiem-Claw-Run-Id'?value:null}});
const valid='run_'+'a'.repeat(24), payload={pc_run_id:'chat_pcq_'+'b'.repeat(32)};
process.stdout.write(JSON.stringify([
 api.runIdForProgress(response(valid),payload,true),
 api.runIdForProgress(response('run_'+ 'a'.repeat(24)+'/other'),payload,true),
 api.runIdForProgress(response(null),payload,true),
 api.runIdForProgress(response(valid),payload,false)]));
"""
    result = subprocess.run([node, "-e", script, str(SOURCE)], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == ["run_" + "a" * 24, None, None, "chat_pcq_" + "b" * 32]
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'recordPcProgress?.(article, value, pcProgressRunId)' in app
    assert 'if (!clawGeneralRequest && ["pc_progress"' not in app
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    assert index.index('./pc-browser-progress.js') < index.index('./app.js')


@pytest.fixture(scope="module")
def browser():
    sync = pytest.importorskip("playwright.sync_api")
    with sync.sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


@pytest.fixture
def page(browser):
    page = browser.new_page()
    page.route("http://localhost/", lambda route: route.fulfill(status=200, content_type="text/html", body=HTML))
    page.goto("http://localhost/")
    page.evaluate("""() => {
      window.captureRequests=[]; window.revoked=[];
      const original=window.fetch.bind(window);
      window.fetch=(url, options)=>{captureRequests.push({url,credentials:options.credentials,cache:options.cache});return original(url,options);};
      const revoke=URL.revokeObjectURL.bind(URL);
      URL.revokeObjectURL=url=>{revoked.push(url);revoke(url);};
    }""")
    yield page
    page.close()


def _reply(page, *, status=200, media_type="image/png", sha=SHA, body=PNG):
    page.route("http://localhost/api/claw/connector/browser-captures/**", lambda route: route.fulfill(
        status=status, content_type=media_type, headers={"X-Padiem-Browser-Capture-Sha256": sha}, body=body))


def test_capture_is_one_verified_same_origin_png_and_logout_revokes_it(page):
    _reply(page)
    page.locator("#answer").evaluate("(node,text)=>node.textContent=text", "Example Domain\n" + MARKER + "\n[pc-browser-capture:" + OTHER + "]")
    page.add_script_tag(path=str(SOURCE))
    page.wait_for_selector(".pc-browser-capture-image")
    assert page.locator(".pc-browser-capture-image").count() == 1
    assert page.locator(".pc-browser-capture-image").get_attribute("src").startswith("blob:http://localhost/")
    assert page.locator(".pc-browser-capture-image").get_attribute("alt") == "PC 브라우저 화면 캡처"
    assert MARKER not in page.locator("#answer").inner_text()
    assert page.evaluate("captureRequests") == [{"url": "/api/claw/connector/browser-captures/" + DISPATCH,
                                                "credentials": "same-origin", "cache": "no-store"}]
    page.evaluate("window.dispatchEvent(new CustomEvent('padiem:auth-state',{detail:{authenticated:false}}))")
    page.evaluate("() => new Promise(resolve=>setTimeout(resolve,50))")
    assert page.locator(".pc-browser-capture-image").count() == 0
    assert page.evaluate("revoked.length") == 1
    assert page.evaluate("captureRequests.length") == 1


@pytest.mark.parametrize("response", [
    {"status": 404}, {"media_type": "text/html"}, {"sha": "0" * 64},
    {"sha": ""}, {"body": b"<script>not an image</script>"},
])
def test_invalid_or_foreign_capture_stays_a_reference_not_an_error_screen(page, response):
    _reply(page, **response)
    page.locator("#answer").evaluate("(node,text)=>node.textContent=text", "Answer\n" + MARKER)
    page.add_script_tag(path=str(SOURCE))
    page.wait_for_function("captureRequests.length === 1")
    page.evaluate("() => new Promise(resolve=>setTimeout(resolve,50))")
    assert page.locator(".pc-browser-capture-image").count() == 0
    assert page.locator("#answer").text_content() == "Answer\n" + MARKER
    assert page.locator("article").get_attribute("data-lifecycle") == "streaming"
    # A later unrelated DOM mutation must not create a fetch/retry loop.
    page.locator("#answer").evaluate("node=>node.appendChild(document.createTextNode(' '))")
    assert page.evaluate("captureRequests.length") == 1


def test_model_urls_local_paths_and_user_messages_are_not_capture_authority(page):
    page.locator("#answer").evaluate("""node=>node.textContent=
      '[pc-browser-capture:https://example.com/image.png] [pc-browser-capture:file:///tmp/page.png]'
      +' [pc-browser-capture:dsp_'+'a'.repeat(32)+'/other]'""")
    page.evaluate("(marker)=>{const p=document.createElement('p');p.className='user-content';p.textContent=marker;document.getElementById('messageList').append(p);}", MARKER)
    page.add_script_tag(path=str(SOURCE))
    assert page.evaluate("captureRequests.length") == 0


def test_marker_arriving_in_stream_text_mutation_is_upgraded(page):
    _reply(page)
    page.add_script_tag(path=str(SOURCE))
    page.locator("#answer").evaluate("node=>node.textContent='Example Domain [pc-browser-capture:'")
    page.locator("#answer").evaluate("(node,suffix)=>node.firstChild.nodeValue+=suffix", DISPATCH + "]")
    page.wait_for_selector(".pc-browser-capture-image")
    assert page.locator(".pc-browser-capture-image").count() == 1


def test_detached_or_changed_account_never_paints_a_late_capture(page):
    page.evaluate("() => { window.fetch=()=>new Promise(resolve=>window.finishCapture=resolve); }")
    page.locator("#answer").evaluate("(node,text)=>node.textContent=text", MARKER)
    page.add_script_tag(path=str(SOURCE))
    page.wait_for_function("typeof finishCapture==='function'")
    page.evaluate("window.dispatchEvent(new Event('padiem:account-changed'))")
    page.evaluate("""({body,sha})=>finishCapture(new Response(new Uint8Array(body),{
      status:200,headers:{'content-type':'image/png','x-padiem-browser-capture-sha256':sha}}))""",
                  {"body": list(PNG), "sha": SHA})
    page.evaluate("() => new Promise(resolve=>setTimeout(resolve,50))")
    assert page.locator(".pc-browser-capture-image").count() == 0


def test_real_lifecycle_shows_claw_progress_elapsed_and_terminal_stop(page):
    page.add_script_tag(path=str(SOURCE))
    page.add_script_tag(path=str(STATIC / "message-lifecycle.js"))
    observed = page.evaluate("""() => {
      const article=document.querySelector('article'), api=PadiemChatLifecycle;
      const run='run_'+'a'.repeat(24);
      const expected=PadiemPcBrowserSurface.runIdForProgress(new Response(null,{headers:{'X-Padiem-Claw-Run-Id':run}}),{},true);
      api.startTurnClock(article);api.recordTaskEvent(article,'request_sent');api.renderTaskStatus(article);
      const value={pc_run_id:run,dispatch_id:'dsp_'+'a'.repeat(32),kind:'command',stage:'accepted',sequence:1,elapsed_ms:0};
      const foreign=api.recordPcProgress(article,{...value,pc_run_id:'run_'+'b'.repeat(24)},expected);
      const accepted=api.recordPcProgress(article,value,expected);
      api.recordPcProgress(article,{...value,stage:'executing',sequence:2,elapsed_ms:12000},expected);
      const during=article.querySelector('.capability-current').textContent;
      api.recordPcHeartbeat(article,{run_id:'engine_run',trace_id:'trace_run',elapsed_ms:13000});
      const heartbeat=article.querySelector('.capability-current').textContent;
      api.set(article,'completed');
      return {foreign,accepted,during,heartbeat,late:api.recordPcProgress(article,{...value,stage:'result',sequence:3,elapsed_ms:14000},expected),
       buttons:article.querySelectorAll('button').length};
    }""")
    assert observed == {"foreign": False, "accepted": True, "during": "PC 실행 중 · 12s",
                        "heartbeat": "PC 실행 중 · 13s", "late": False, "buttons": 0}
