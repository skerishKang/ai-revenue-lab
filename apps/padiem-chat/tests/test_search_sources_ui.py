from __future__ import annotations

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
    assert "toolInFlight" in js


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
