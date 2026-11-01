"""Browser PC wire: one owned capture and a narrowly bound conversational answer."""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import pytest

from kagent import pc_browser_child
from kagent.pc_browser_tools import (
    BROWSER_ACT_TOOL_ID, BROWSER_OPEN_TOOL_ID, MAX_INLINE_TEXT, PcBrowserError, PcBrowserSession,
    confirmation_question, store_text, validate_arguments,
)

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1sAAAAASUVORK5CYII=")
URL = "https://example.com/after"


class Browser:
    def __init__(self, *, target="Send", url=URL, title="Example", image=PNG):
        self.target, self.url, self.title, self.image = target, url, title, image
        self.calls = []
        self.fail_snapshot = False

    def call_tool(self, name, arguments=None):
        self.calls.append((name, dict(arguments or {})))
        if name == "browser_snapshot":
            if self.fail_snapshot:
                return {"isError": True, "content": [{"type": "text", "text": "unavailable"}]}
            return {"content": [{"type": "text", "text":
                f'- Page URL: {self.url}\n- Page Title: {self.title}\n'
                f'- button "{self.target}" [ref=e2]\n'}]}
        if name == "browser_take_screenshot":
            Path(arguments["filename"]).write_bytes(self.image)
        return {"content": [{"type": "text", "text": "done"}]}

    def close(self):
        pass


@pytest.fixture(autouse=True)
def owned_output(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))


def test_capture_transports_exact_owned_png_and_digest():
    session = PcBrowserSession(Browser())
    session.open("https://example.com")
    shot = session.screenshot()
    assert shot["state"] == "captured" and shot["screenshots"] == "1"
    assert shot["url"] == URL
    capture = shot["capture"]
    assert capture == {"mime_type": "image/png", "data": base64.b64encode(PNG).decode("ascii"),
                       "sha256": hashlib.sha256(PNG).hexdigest(), "bytes": len(PNG)}
    assert Path(shot["path"]).read_bytes() == PNG


def test_capture_refuses_non_png_result():
    session = PcBrowserSession(Browser(image=b"not a screenshot"))
    session.open("https://example.com")
    with pytest.raises(PcBrowserError, match="verified"):
        session.screenshot()


def test_capture_never_reads_an_outside_symlink(tmp_path):
    outside = tmp_path / "outside.png"
    outside.write_bytes(PNG)
    browser = Browser()
    original = browser.call_tool
    def call(name, arguments=None):
        if name == "browser_take_screenshot":
            Path(arguments["filename"]).symlink_to(outside)
            return {"content": []}
        return original(name, arguments)
    browser.call_tool = call
    session = PcBrowserSession(browser)
    session.open("https://example.com")
    with pytest.raises(PcBrowserError, match="saved"):
        session.screenshot()


def test_question_is_plain_and_binds_the_observed_page_target_and_action():
    browser = Browser()
    session = PcBrowserSession(browser)
    opened = session.open("https://example.com")
    assert opened["url"] == URL  # Observed redirect, not the requested URL.
    result = session.act(action="click", name="Send")
    assert result["state"] == "needs_confirmation"
    assert result["question"] == confirmation_question("Send", action="click", url=URL)
    assert URL in result["question"] and "Send" in result["question"]
    assert not any(name == "browser_click" for name, _ in browser.calls)


@pytest.mark.parametrize("url,title", [
    ("https://example.com/checkout", "Example"),
    ("https://example.com/login", "Example"),
    (URL, "결제 확인"),
    (URL, "Sign in"),
])
def test_neutral_target_on_observed_sensitive_page_asks_before_action(url, title):
    browser = Browser(target="Continue", url=url, title=title)
    session = PcBrowserSession(browser)
    session.open("https://example.com")
    result = session.act(action="click", name="Continue")
    assert result["state"] == "needs_confirmation"
    assert result["question"] == confirmation_question("Continue", action="click", url=url)
    assert not any(name == "browser_click" for name, _ in browser.calls)
    confirmed = session.act(action="click", name="Continue", confirmation={
        "action": "click", "target": "Continue", "url": url})
    assert confirmed["state"] == "acted"
    assert [name for name, _ in browser.calls].count("browser_click") == 1


@pytest.mark.parametrize("mismatch", [{"action": "type"}, {"target": "Other"},
                                     {"url": "https://other.example/"}, {"extra": "yes"}])
def test_confirmation_cannot_change_page_target_or_action(mismatch):
    browser = Browser()
    session = PcBrowserSession(browser)
    session.open("https://example.com")
    receipt = {"action": "click", "target": "Send", "url": URL, **mismatch}
    result = session.act(action="click", name="Send", confirmation=receipt)
    assert result["state"] == "needs_confirmation"
    assert not any(name == "browser_click" for name, _ in browser.calls)


def test_child_passes_private_confirmation_and_observes_after_click():
    browser = Browser()
    result = pc_browser_child.run({
        "tool_id": BROWSER_ACT_TOOL_ID,
        "arguments": {"action": "click", "name": "Send"}, "url": URL,
        "confirmation": {"action": "click", "target": "Send", "url": URL},
    }, session=PcBrowserSession(browser))
    assert result["ok"] == "true" and result["result"]["state"] == "acted"
    assert result["result"]["verified"] is True
    assert result["result"]["observation"] == {"url": URL, "title": "Example", "elements": 1}
    assert [name for name, _ in browser.calls][-2:] == ["browser_click", "browser_snapshot"]


def test_model_argument_cannot_claim_confirmation():
    with pytest.raises(PcBrowserError):
        validate_arguments(BROWSER_ACT_TOOL_ID, {
            "action": "click", "name": "Send", "confirmation": {"action": "click", "target": "Send", "url": URL}})


def test_type_confirmation_binds_the_value_before_one_actual_input():
    browser = Browser(target="Publish message")
    session = PcBrowserSession(browser)
    session.open("https://example.com")
    original = "승인할 문장"
    question = session.act(action="type", name="Publish message", value=original)
    assert question["state"] == "needs_confirmation"
    assert original in question["question"]
    confirmation = {"action": "type", "target": "Publish message", "url": URL, "value": original}
    refused = session.act(action="type", name="Publish message", value="바뀐 문장", confirmation=confirmation)
    assert refused["state"] == "needs_confirmation"
    assert not any(name == "browser_type" for name, _ in browser.calls)
    result = session.act(action="type", name="Publish message", value=original, confirmation=confirmation)
    assert result["state"] == "acted"
    assert [name for name, _ in browser.calls].count("browser_type") == 1


@pytest.mark.parametrize("target", ["Password", "세션 쿠키", "Access token", "Session token", "API key", "API 키"])
def test_confirmation_formatter_never_echoes_a_secret_field_value(target):
    from kagent.pc_browser_tools import is_secret_target
    assert is_secret_target(target)
    text = confirmation_question(target, action="type", url=URL, value="synthetic-do-not-echo")
    assert "synthetic-do-not-echo" not in text
    assert "입력할 수 없습니다" in text


@pytest.mark.parametrize("target", ["Password", "비밀번호", "Session cookie", "Access token", "Session token", "API key"])
def test_secret_field_is_not_typable_even_with_a_confirmation(target):
    browser = Browser(target=target)
    session = PcBrowserSession(browser)
    session.open("https://example.com")
    with pytest.raises(PcBrowserError, match="Credential"):
        session.act(action="type", name=target, value="synthetic-value", confirmation={
            "action": "type", "target": target, "url": URL})
    assert not any(name == "browser_type" for name, _ in browser.calls)


def test_failed_observation_does_not_report_a_verified_action():
    browser = Browser(target="Next")
    original = browser.call_tool
    def call(name, arguments=None):
        result = original(name, arguments)
        if name == "browser_click":
            browser.fail_snapshot = True
        return result
    browser.call_tool = call
    session = PcBrowserSession(browser)
    session.open("https://example.com")
    with pytest.raises(PcBrowserError, match="observed"):
        session.act(action="click", name="Next")


def test_private_redirect_is_not_reused_or_reported_as_opened():
    session = PcBrowserSession(Browser(url="http://127.0.0.1/private"))
    with pytest.raises(PcBrowserError) as error:
        session.open("https://example.com")
    assert error.value.code == "browser_url_rejected"


@pytest.mark.parametrize("snapshot", ["", '- Page Title: Example\n- button "Next" [ref=e2]'])
def test_malformed_snapshot_cannot_report_the_previous_url_as_verified(snapshot):
    browser = Browser(target="Next")
    session = PcBrowserSession(browser)
    session.open("https://example.com")
    original = browser.call_tool
    def call(name, arguments=None):
        if name == "browser_snapshot":
            return {"content": [{"type": "text", "text": snapshot}]}
        return original(name, arguments)
    browser.call_tool = call
    with pytest.raises(PcBrowserError, match="observed"):
        session.act(action="click", name="Next")
    assert not any(name == "browser_click" for name, _ in browser.calls)


def test_utf8_preview_budget_is_bytes_and_handle_keeps_the_full_text():
    source = "가" * 10000
    result = store_text(source)
    assert result["truncated"] == "true"
    assert len(result["preview"].encode("utf-8")) <= MAX_INLINE_TEXT
    from kagent.pc_browser_tools import read_stored
    assert read_stored(result["handle"], 0, 65536)["text"] == source


def test_long_korean_paragraph_survives_snapshot_and_node_parsing_in_full():
    from kagent.pc_browser_tools import output_dir, parse_snapshot
    source = "가" * 420_000  # Also exceeds the old raw-snapshot character cut.
    snapshot = (f'- Page URL: {URL}\n- Page Title: Example\n'
                f'- paragraph [ref=e1]: {source}\n')
    browser = Browser()
    original = browser.call_tool
    def call(name, arguments=None):
        if name == "browser_snapshot":
            return {"content": [{"type": "text", "text": snapshot}]}
        return original(name, arguments)
    browser.call_tool = call
    session = PcBrowserSession(browser)
    session.open("https://example.com")
    result = session.read()
    encoded = source.encode("utf-8")
    assert result["handle"] == hashlib.sha256(encoded).hexdigest()
    assert int(result["bytes"]) == len(encoded)
    assert (output_dir() / "pages" / result["handle"]).read_bytes() == encoded
    assert len(result["preview"].encode("utf-8")) <= MAX_INLINE_TEXT
    assert len(parse_snapshot(snapshot)[0]["name"]) == 1024


@pytest.mark.parametrize("tool_id,arguments", [
    (BROWSER_OPEN_TOOL_ID, {}),
    (BROWSER_OPEN_TOOL_ID, {"url": None}),
    (BROWSER_OPEN_TOOL_ID, {"url": "http://127.0.0.1/private"}),
    (BROWSER_ACT_TOOL_ID, {"action": "click"}),
    (BROWSER_ACT_TOOL_ID, {"action": "click", "name": None}),
    (BROWSER_ACT_TOOL_ID, {"action": "click", "text": "  "}),
    (BROWSER_ACT_TOOL_ID, {"action": "type", "name": "Search"}),
    (BROWSER_ACT_TOOL_ID, {"action": "type", "name": "Search", "value": ""}),
])
def test_direct_native_validation_rejects_missing_or_invalid_fields(tool_id, arguments):
    with pytest.raises(PcBrowserError):
        validate_arguments(tool_id, arguments)


def test_private_stored_output_reader_survives_stricter_public_validation():
    stored = store_text("x" * 9000)
    result = pc_browser_child.run({"tool_id": "claw.pc.browser_read_output", "arguments": {
        "handle": stored["handle"], "offset": 0, "length": 100}}, session=PcBrowserSession(Browser()))
    assert result == {"ok": "true", "result": {"text": "x" * 100}}
    malformed = pc_browser_child.run({"tool_id": "claw.pc.browser_read_output", "arguments": []},
                                    session=PcBrowserSession(Browser()))
    assert malformed == {"ok": "false", "code": "browser_action_unsupported"}
