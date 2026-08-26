from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


def sources():
    root = Path(__file__).resolve().parents[1]
    return (
        root,
        (root / "static/index.html").read_text(encoding="utf-8"),
        (root / "static/search-sources.js").read_text(encoding="utf-8"),
        (root / "static/search-sources.css").read_text(encoding="utf-8"),
        (root / "static/app.js").read_text(encoding="utf-8"),
    )


def compatibility_helpers(js: str) -> str:
    start = js.index("  function requestPath(inputValue) {")
    end = js.index("  function currentAssistantArticle() {")
    return js[start:end]


def test_search_assets_are_additive_and_ordered():
    _, html, _, _, _ = sources()
    assert '<link rel="stylesheet" href="./search-sources.css" />' in html
    app_index = html.index('<script src="./app.js"></script>')
    search_index = html.index('<script src="./search-sources.js"></script>')
    rich_index = html.index('<script src="./rich-response.js"></script>')
    outputs_index = html.index('<script src="./outputs.js"></script>')
    assert app_index < search_index < rich_index < outputs_index


def test_web_and_research_start_fail_closed_and_are_health_gated():
    _, html, js, _, _ = sources()
    assert "웹 검색 · 준비 중" in html
    assert 'id="deepResearchButton" disabled' in html
    assert 'nativeFetch("/health"' in js
    assert 'data.web_tools_ready === true' in js
    assert 'data.deep_research_ready === true' in js
    assert 'deepResearchButton.disabled = researchUnavailable' in js
    assert 'setAttribute("aria-pressed"' in js
    assert 'setActiveTool("web_search"' in js
    assert 'setActiveTool("deep_research"' in js
    assert "activeTool = next ? toolId : null" in js


def test_tools_are_one_request_only_mutually_exclusive_and_retryable():
    _, _, js, _, _ = sources()
    assert "payload.tool = toolId" in js
    assert "const requestedTool = isChat ? activeTool : null" in js
    assert "activeTool = null" in js
    assert "toolInFlight = requestedTool" in js
    assert 'closest(".retry-button")' in js
    assert "activeTool = retryTool" in js
    assert "retryOverride = true" in js
    assert 'toolId === "web_search"' in js
    assert 'toolId === "deep_research"' in js


def test_streaming_chat_with_active_tool_is_adapted_to_completed_json_once():
    _, _, js, _, _ = sources()
    assert 'streamingChatRequest(inputValue)' in js
    assert 'const isChat = chatRequest(inputValue) || streamingChatRequest(inputValue);' in js
    assert 'inputValue: "/api/chat"' in js
    assert 'headers.set("Accept", "application/json")' in js
    assert 'const response = await nativeFetch(nextInput, nextInit);' in js
    assert 'completedJsonAsPublicSse(data)' in js
    assert 'nativeFetch("/api/chat/stream"' not in js

    helpers = compatibility_helpers(js)
    script = helpers + r'''
global.window = { location: { href: "https://chat.example.test/" } };
const init = {
  method: "POST",
  headers: { "Content-Type": "application/json", "Accept": "text/event-stream" },
  body: JSON.stringify({ messages: [{ role: "user", content: "질문" }], mode: "auto", skill: "auto" }),
};
const adapted = adaptToolRequest("/api/chat/stream", init, "web_search");
const direct = adaptToolRequest("/api/chat", init, "deep_research");
(async () => {
  const facade = completedJsonAsPublicSse({
    answer: "검색 결과입니다.",
    conversation_id: "conv-1",
    project_id: "project-1",
    project: { id: "project-1", name: "프로젝트" },
    project_files_used: 2,
  });
  console.log(JSON.stringify({
    adaptedInput: adapted.inputValue,
    adaptedAccept: adapted.init.headers.get("Accept"),
    adaptedPayload: JSON.parse(adapted.init.body),
    adaptedFromStream: adapted.adaptedFromStream,
    directInput: direct.inputValue,
    directPayload: JSON.parse(direct.init.body),
    directFromStream: direct.adaptedFromStream,
    facadeType: facade.headers.get("content-type"),
    facadeBody: await facade.text(),
  }));
})().catch((error) => { console.error(error); process.exit(1); });
'''
    result = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)

    assert data["adaptedInput"] == "/api/chat"
    assert data["adaptedAccept"] == "application/json"
    assert data["adaptedPayload"]["tool"] == "web_search"
    assert data["adaptedFromStream"] is True
    assert data["directInput"] == "/api/chat"
    assert data["directPayload"]["tool"] == "deep_research"
    assert data["directFromStream"] is False
    assert data["facadeType"].startswith("text/event-stream")
    assert 'event: delta\ndata: {"delta":"검색 결과입니다."}' in data["facadeBody"]
    assert 'event: done\ndata: {"done":true,"conversation_id":"conv-1","project_id":"project-1"' in data["facadeBody"]
    assert '"project_files_used":2' in data["facadeBody"]


def test_completed_json_facade_rejects_missing_answer_instead_of_fabricating_success():
    _, _, js, _, _ = sources()
    helpers = compatibility_helpers(js)
    script = helpers + r'''
global.window = { location: { href: "https://chat.example.test/" } };
console.log(JSON.stringify({
  missing: completedJsonAsPublicSse({ done: true }) === null,
  empty: completedJsonAsPublicSse({ answer: "" }) === null,
}));
'''
    result = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"missing": True, "empty": True}


def test_photo_plus_web_tools_are_blocked_in_browser_too():
    _, _, js, _, _ = sources()
    assert "imageSelected()" in js
    assert "사진 첨부와 웹 검색·심층 리서치는 한 질문에서 함께 사용할 수 없습니다." in js
    assert 'attributeFilter: ["hidden", "src"]' in js


def test_visible_sources_are_text_only_numbered_and_public_http_links():
    _, _, js, css, _ = sources()
    assert 'data.answer_status === "answered_with_evidence"' in js
    assert 'data.tool.id === "web_search"' in js
    assert 'data.answer_status === "deep_research_answered"' in js
    assert 'data.tool.id === "deep_research"' in js
    assert ".slice(0, 10)" in js
    assert 'url.protocol !== "http:" && url.protocol !== "https:"' in js
    assert 'document.createElement("section")' in js
    assert 'document.createElement("ol")' in js
    assert 'document.createElement("a")' in js
    assert 'number.textContent = `[${index + 1}]`' in js
    assert 'anchor.target = "_blank"' in js
    assert 'anchor.rel = "noopener noreferrer"' in js
    assert "title.textContent =" in js
    assert "host.textContent = url.hostname" in js
    assert "innerHTML" not in js
    assert "insertAdjacentHTML" not in js
    assert "firecrawl" not in js.lower()
    assert "api_key" not in js.lower()
    assert "answer-sources" in css
    assert "answer-source-link" in css


def test_research_summary_is_compact_and_does_not_render_planner_or_provider_metadata():
    _, _, js, css, _ = sources()
    assert 'summary.className = "research-summary"' in js
    assert "research.searches_completed" in js
    assert "research.source_count" in js
    assert 'research.status === "partial"' in js
    assert "queries_planned" not in js
    assert ".provider" not in js
    assert "planner" not in js.lower()
    assert "research-summary" in css


def test_existing_app_and_phase1_style_contracts_remain_separate():
    root, _, js, _, app_js = sources()
    repo = root.parents[1]
    assert "payload.tool = toolId" in js
    assert 'payload.tool = "web_search"' not in app_js
    assert 'payload.tool = "deep_research"' not in app_js
    assert (root / "static/styles.css").read_bytes() == (
        repo / "reference/business-62-padiem-chat-v1/styles.css"
    ).read_bytes()


def test_search_sources_javascript_syntax():
    root, _, _, _, _ = sources()
    node = shutil.which("node")
    assert node is not None
    result = subprocess.run(
        [node, "--check", str(root / "static/search-sources.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
