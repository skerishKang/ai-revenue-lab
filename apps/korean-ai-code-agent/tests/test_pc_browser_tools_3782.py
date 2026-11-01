"""#3782 step 1 — PC browser lane contracts (no network, no real browser)."""
from __future__ import annotations

import json

import pytest

from kagent import pc_browser_child
from kagent.pc_browser_tools import (
    BROWSER_ACT_TOOL_ID,
    BROWSER_OPEN_TOOL_ID,
    BROWSER_READ_TOOL_ID,
    BROWSER_SCREENSHOT_TOOL_ID,
    MAX_INLINE_TEXT,
    PcBrowserError,
    PcBrowserSession,
    needs_confirmation,
    page_title,
    parse_snapshot,
    read_stored,
    resolve_target,
    store_text,
    tool_specs,
    validate_arguments,
)

SNAPSHOT = """### Page
- Page URL: https://example.com/after
- Page Title: After page
### Snapshot
```yaml
- main [ref=e2]:
  - heading "공지사항" [level=1] [ref=e4]
  - paragraph [ref=e7]: 첫 번째 문단입니다.
  - link "Learn more" [ref=e13] [cursor=pointer]:
    - /url: https://example.org/notice
  - textbox "검색" [ref=e20]
```"""


class FakeClient:
    """Stands in for the pinned MCP child process."""

    def __init__(self, snapshot: str = SNAPSHOT, *, fail: bool = False) -> None:
        self.snapshot = snapshot
        self.fail = fail
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    def call_tool(self, name, arguments=None):
        self.calls.append((name, dict(arguments or {})))
        if self.fail:
            return {"isError": True, "content": []}
        if name == "browser_snapshot":
            return {"content": [{"type": "text", "text": self.snapshot}]}
        if name == "browser_navigate":
            return {"content": [{"type": "text", "text": "### Page\n- Page URL: " + arguments["url"]}]}
        return {"content": [{"type": "text", "text": "done"}]}

    def close(self):
        self.closed = True


def test_parse_snapshot_keeps_text_title_and_link_url():
    nodes = parse_snapshot(SNAPSHOT)
    assert page_title(SNAPSHOT) == "After page"
    assert {"role": "heading", "name": "공지사항", "ref": "e4", "url": ""} in nodes
    assert {"role": "paragraph", "name": "첫 번째 문단입니다.", "ref": "e7", "url": ""} in nodes
    assert {"role": "link", "name": "Learn more", "ref": "e13",
            "url": "https://example.org/notice"} in nodes


def test_open_rejects_private_and_invalid_addresses_before_the_browser_is_asked():
    client = FakeClient()
    session = PcBrowserSession(client)
    for url in ("http://127.0.0.1/x", "http://localhost:8080", "file:///C:/x.html", "javascript:alert(1)"):
        with pytest.raises(PcBrowserError) as excinfo:
            session.open(url)
        assert excinfo.value.code == "browser_url_rejected"
    assert client.calls == []


def test_open_uses_the_canonical_url_and_reports_the_page():
    client = FakeClient()
    result = PcBrowserSession(client).open("https://example.com")
    assert result["state"] == "opened"
    assert client.calls[0] == ("browser_navigate", {"url": "https://example.com/"})
    assert result["title"] == "After page"


def test_read_returns_body_and_links_but_no_form_values():
    session = PcBrowserSession(FakeClient())
    session.open("https://example.com")
    result = session.read()
    assert "첫 번째 문단입니다." in result["text"]
    assert result["links"] == [{"name": "Learn more", "url": "https://example.org/notice"}]
    assert "검색" not in result["text"]
    encoded = json.dumps(result, ensure_ascii=False)
    for forbidden in ("cookie", "password", "localStorage", "<html", "e7"):
        assert forbidden not in encoded


def test_long_page_text_is_stored_under_a_handle_and_read_back():
    long_text = "가" * (MAX_INLINE_TEXT + 64)
    stored = store_text(long_text)
    assert stored["truncated"] == "true"
    assert len(stored["handle"]) == 64
    chunk = read_stored(stored["handle"], 0, 4096)
    assert chunk["text"].startswith("가")


def test_confirmation_is_required_for_login_payment_post_send_and_delete():
    assert needs_confirmation("Sign in")
    assert needs_confirmation("로그인")
    assert needs_confirmation("결제하기")
    assert needs_confirmation("게시")
    assert needs_confirmation("Send")
    assert needs_confirmation("삭제")
    assert not needs_confirmation("다음")


def test_click_on_a_confirm_action_asks_instead_of_executing():
    snapshot = SNAPSHOT.replace(
        '- link "Learn more" [ref=e13] [cursor=pointer]:',
        '- link "Sign in" [ref=e13] [cursor=pointer]:')
    client = FakeClient(snapshot)
    session = PcBrowserSession(client)
    session.open("https://example.com")
    session.read()
    client.calls.clear()
    result = session.act(action="click", text="Sign in")
    assert result["state"] == "needs_confirmation"
    assert "실행할까요" in result["question"]
    assert [name for name, _ in client.calls] == ["browser_snapshot"]


def test_click_passes_target_ref_and_element_name_to_the_browser():
    client = FakeClient()
    session = PcBrowserSession(client)
    session.open("https://example.com")
    result = session.act(action="click", name="Learn more")
    assert result["state"] == "acted"
    assert ("browser_click", {"target": "e13", "element": "Learn more"}) in client.calls


def test_type_requires_a_value_and_sends_it():
    client = FakeClient()
    session = PcBrowserSession(client)
    session.open("https://example.com")
    with pytest.raises(PcBrowserError):
        session.act(action="type", name="검색")
    session.act(action="type", name="검색", value="공지")
    assert ("browser_type", {"target": "e20", "element": "검색", "text": "공지"}) in client.calls


def test_target_resolution_prefers_an_exact_name_and_refuses_ambiguity():
    nodes = [{"role": "link", "name": "더 보기", "ref": "e1", "url": ""},
             {"role": "link", "name": "더 보기 전체", "ref": "e2", "url": ""}]
    assert resolve_target(nodes, text="더 보기", role=None, name=None)["ref"] == "e1"
    with pytest.raises(PcBrowserError) as ambiguous:
        resolve_target([{"role": "link", "name": "같은 이름", "ref": "e1", "url": ""},
                        {"role": "link", "name": "같은 이름", "ref": "e2", "url": ""}],
                       text=None, role=None, name="같은 이름")
    assert ambiguous.value.code == "browser_target_ambiguous"
    with pytest.raises(PcBrowserError) as missing:
        resolve_target(nodes, text="없음", role=None, name=None)
    assert missing.value.code == "browser_target_not_found"


def test_argument_validation_is_a_closed_shape():
    assert validate_arguments(BROWSER_OPEN_TOOL_ID, {"url": "https://example.com"}) == {"url": "https://example.com"}
    for tool_id, arguments in (
        (BROWSER_READ_TOOL_ID, {"cookie": "x"}),
        (BROWSER_OPEN_TOOL_ID, {"url": "https://example.com", "javascript": "alert(1)"}),
        (BROWSER_ACT_TOOL_ID, {"action": "evaluate"}),
        (BROWSER_SCREENSHOT_TOOL_ID, {"fullPage": True}),
        ("claw.pc.read_file", {"path": "x"}),
    ):
        with pytest.raises(PcBrowserError):
            validate_arguments(tool_id, arguments)


def test_tool_specs_expose_only_the_four_bounded_tools():
    specs = {spec.id: spec for spec in tool_specs()}
    assert set(specs) == {BROWSER_OPEN_TOOL_ID, BROWSER_READ_TOOL_ID,
                          BROWSER_SCREENSHOT_TOOL_ID, BROWSER_ACT_TOOL_ID}
    assert specs[BROWSER_OPEN_TOOL_ID].approval_policy.name == "NOT_REQUIRED"
    assert specs[BROWSER_ACT_TOOL_ID].approval_policy.name == "EXTERNAL_AUTHORIZATION"


def test_child_answers_one_json_document(monkeypatch, capsys):
    monkeypatch.setattr(pc_browser_child, "PcBrowserSession", lambda: PcBrowserSession(FakeClient()))
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps(
        {"tool_id": BROWSER_OPEN_TOOL_ID, "arguments": {"url": "https://example.com"}})))
    assert pc_browser_child.main([]) == 0
    answer = json.loads(capsys.readouterr().out)
    assert answer["ok"] == "true"
    assert answer["result"]["state"] == "opened"
    assert len(answer["request_id"]) == 32


def test_child_refuses_a_private_url_without_a_traceback(monkeypatch, capsys):
    monkeypatch.setattr(pc_browser_child, "PcBrowserSession", lambda: PcBrowserSession(FakeClient()))
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps(
        {"tool_id": BROWSER_OPEN_TOOL_ID, "arguments": {"url": "http://127.0.0.1/"}})))
    assert pc_browser_child.main([]) == 1
    answer = json.loads(capsys.readouterr().out)
    assert answer == {**answer, "ok": "false", "code": "browser_url_rejected"}