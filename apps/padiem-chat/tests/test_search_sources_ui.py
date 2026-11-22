from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

# #8060 36차: 시트 원문 읽기는 _support 헬퍼(claw_static·css_rules·html_tags)와
# _r5_function_source가 담당하고, 시험은 파싱 값(스크립트 순서·CSS 선언·함수
# 범위 소스)과 부재 금지 경계 계약(README §3 — 제거된 것은 소스에서만 증명할 수
# 있다)을 단언한다. 이 모듈은 원문 read를 갖지 않는다.
from _r5_function_source import definition_source
from _support import claw_static
from _support.html_tags import tags_for_page
from css_rules import declaration, rules_for_sheet

ROOT = Path(__file__).resolve().parents[1]


def _html() -> str:
    return claw_static.sheet("index.html")


def _js() -> str:
    return claw_static.sheet("search-sources.js")


def _app() -> str:
    return claw_static.sheet("app.js")


def _js_region(start_marker: str, end_marker: str) -> str:
    """One shipped function's source, bounded by the next function's head."""
    source = _js()
    start = source.index(start_marker)
    return source[start:source.index(end_marker, start)]


def test_search_assets_are_additive_and_ordered():
    links = [attrs.get("href") for tag, attrs in tags_for_page("index.html")
             if tag == "link" and attrs.get("rel") == "stylesheet"]
    assert "./search-sources.css" in links
    srcs = [attrs["src"] for _tag, attrs in tags_for_page("index.html") if attrs.get("src")]
    order = {src: position for position, src in enumerate(srcs)}
    assert order["./app.js"] < order["./product-capabilities.js"]
    assert order["./product-capabilities.js"] < order["./search-sources.js"]
    assert order["./search-sources.js"] < order["./rich-response.js"]
    assert order["./search-sources.js"] < order["./outputs.js"]


def test_search_and_research_controls_are_removed_from_the_ui():
    html, js = _html(), _js()
    capabilities = claw_static.sheet("product-capabilities.js")
    voice = claw_static.sheet("voice-composer.css")
    for identifier in ("webSearchButton", "deepResearchButton", "webSearchStarterButton"):
        assert identifier not in html
        assert identifier not in js
        assert identifier not in capabilities
        assert identifier not in voice
    # 제거된 강제 숨김 규칙은 시트에 다시 생기지 않는다(파싱 셀렉터로).
    preview = rules_for_sheet("attachments.css")
    assert not [rule for rule in preview
                if any(selector.strip() == "#composerForm .composer-tools "
                       "#webSearchButton[hidden]" for selector in rule.selectors)]
    assert any(declaration(rule, "width") == "116px" for rule in preview)
    assert "payload.web_search" not in _app()
    assert "window.fetch =" not in js
    assert "payload.tool =" not in js
    assert "setActiveTool" not in js
    assert "aria-pressed" not in js


def test_manual_search_tool_controls_and_request_interception_are_absent():
    html, js = _html(), _js()
    capabilities = claw_static.sheet("product-capabilities.js")
    for identifier in ("webSearchButton", "deepResearchButton", "webSearchStarterButton"):
        assert identifier not in html
        assert identifier not in js
        assert identifier not in capabilities
    assert "window.fetch =" not in js
    assert "activeTool" not in js
    assert "payload.web_search" not in _app()
    assert "payload.tool =" not in js
    assert "window.PadiemSearchSources = Object.freeze({ render: renderSources });" in js
    assert "function renderSources(article, evidence, research = null)" in js

def test_search_sources_does_not_intercept_chat_streaming():
    js, app = _js(), _app()
    assert "streamingChatRequest" not in js
    assert "completedJsonAsPublicSse" not in js
    assert "nativeFetch" not in js
    assert "window.fetch =" not in js
    assert 'fetch("/api/chat/stream"' not in js
    assert "payload.web_search" not in app

def test_search_renderer_is_a_read_only_result_surface():
    js = _js()
    assert "function renderSources(article, evidence, research = null)" in js
    assert "function renderResearchSummary(content, research)" in js
    assert "function publicSourceUrl(value)" in js
    assert 'setAttribute("aria-pressed"' not in js
    assert 'addEventListener("click"' not in js
    assert "window.fetch =" not in js

def test_model_selected_search_evidence_uses_the_existing_result_renderer():
    # #6776 chooses tools on the server. Keep its browser result contract while
    # removing the former client-side button and request-selection path.
    js = _js()
    assert "function renderSources(article, evidence, research = null)" in js
    assert "window.PadiemSearchSources = Object.freeze({ render: renderSources });" in js
    # 완료 응답의 증거 렌더는 applyStreamDone 함수 안에서 일어난다(함수 범위).
    stream_fn = definition_source("applyStreamDone")
    assert "window.PadiemSearchSources?.render?.(article, data.evidence);" in stream_fn
    assert 'if (Array.isArray(data.evidence) && data.evidence.length)' in stream_fn
    assert 'data.tool.id === "web_search"' in stream_fn
    assert "payload.web_search" not in _app()
    assert "payload.web_search" not in claw_static.sheet("chat-streaming-module.js")


def test_streaming_chat_is_not_rewritten_by_the_removed_search_modes():
    js, app = _js(), _app()
    assert "window.fetch =" not in js
    assert "nativeFetch" not in js
    assert "streamingChatRequest" not in js
    assert "completedJsonAsPublicSse" not in js
    assert "payload.web_search" not in app


def test_photo_and_search_tool_exclusion_stays_in_server_validation():
    import base64

    from app.request_contract import BrowserRequestError, _validate_payload

    raw = {
        "messages": [{"role": "user", "content": "찾아봐"}],
        "tool": "web_search",
        "attachments": [{
            "type": "image",
            "name": "photo.png",
            "media_type": "image/png",
            "base64": base64.b64encode(b"\x89PNG\r\n\x1a\nphase8").decode("ascii"),
        }],
    }
    try:
        _validate_payload(raw)
    except BrowserRequestError:
        pass
    else:
        raise AssertionError("the server must keep rejecting explicit search plus image requests")

    html, js = _html(), _js()
    assert 'id="attachmentButton"' in html
    assert 'id="attachmentFileInput"' in html
    assert "activeTool" not in js
    assert "imageSelected" not in js
    assert "payload.web_search" not in _app()



def test_visible_sources_are_text_only_numbered_and_public_http_links():
    js = _js()
    # 렌더기 본문(함수 범위)만이 이 DOM 구조를 만들고, 공개 주소 판정은
    # publicSourceUrl 함수 안에 산다.
    renderer = _js_region("  function renderSources(", "window.PadiemSearchSources")
    public = _js_region("  function publicSourceUrl(", "  function answerTextForSources(")
    for marker in (
        "Array.isArray(evidence)",
        "item && entry.url",
        ".slice(0, 10)",
        'document.createElement("section")',
        'document.createElement("ol")',
        'document.createElement("a")',
        'number.textContent = `[${index + 1}]`',
        'anchor.target = "_blank"',
        'anchor.rel = "noopener noreferrer"',
        "title.textContent =",
        "host.textContent = url.hostname",
    ):
        assert marker in renderer, marker
    assert 'url.protocol !== "http:" && url.protocol !== "https:"' in public
    for forbidden in ("innerHTML", "insertAdjacentHTML", "firecrawl", "api_key"):
        assert forbidden not in js.lower(), forbidden
    classes = [selector for rule in rules_for_sheet("search-sources.css")
               for selector in rule.selectors]
    assert any("answer-sources" in selector for selector in classes)
    assert any("answer-source-link" in selector for selector in classes)


def test_research_summary_is_compact_and_does_not_render_planner_or_provider_metadata():
    js = _js()
    summary = _js_region("  function renderResearchSummary(", "  function renderSources(")
    assert 'summary.className = "research-summary"' in summary
    assert "research.searches_completed" in summary
    assert "research.source_count" in summary
    assert 'research.status === "partial"' in summary
    assert "queries_planned" not in js
    assert ".provider" not in js
    assert "planner" not in js.lower()
    classes = [selector for rule in rules_for_sheet("search-sources.css")
               for selector in rule.selectors]
    assert any("research-summary" in selector for selector in classes)


def test_existing_app_and_phase1_style_contracts_remain_separate():
    js, app_js = _js(), _app()
    assert "payload.tool =" not in js
    assert 'payload.tool = "web_search"' not in app_js
    assert 'payload.tool = "deep_research"' not in app_js
    assert "window.fetch =" not in js
    from style_contract import assert_phase1_styles_match
    assert_phase1_styles_match(
        ROOT / "static/styles.css",
        ROOT.parents[1] / "reference/business-62-padiem-chat-v1/styles.css",
    )


def test_search_sources_javascript_syntax():
    node = shutil.which("node")
    assert node is not None
    result = subprocess.run(
        [node, "--check", str(ROOT / "static/search-sources.js")],
        capture_output=True,
        text=True, encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
