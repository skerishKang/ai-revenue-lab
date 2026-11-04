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
    capability_index = html.index('<script src="./product-capabilities.js"></script>')
    search_index = html.index('<script src="./search-sources.js"></script>')
    rich_index = html.index('<script src="./rich-response.js"></script>')
    outputs_index = html.index('<script src="./outputs.js"></script>')
    assert app_index < capability_index < search_index < rich_index < outputs_index


def test_search_and_research_controls_are_removed_from_the_ui():
    root, html, js, _, app = sources()
    capabilities = (root / "static/product-capabilities.js").read_text(encoding="utf-8")
    preview = (root / "static/attachments.css").read_text(encoding="utf-8")
    voice = (root / "static/voice-composer.css").read_text(encoding="utf-8")
    for identifier in ("webSearchButton", "deepResearchButton", "webSearchStarterButton"):
        assert f'id="{identifier}"' not in html
        assert identifier not in js
        assert identifier not in capabilities
        assert identifier not in voice
    assert "#composerForm .composer-tools #webSearchButton[hidden]" not in preview
    assert "width: 116px" in preview
    assert "payload.web_search" not in app
    assert "window.fetch =" not in js
    assert "payload.tool =" not in js
    assert "setActiveTool" not in js
    assert "aria-pressed" not in js


def test_manual_search_tool_controls_and_request_interception_are_absent():
    root, html, js, _, app = sources()
    capabilities = (root / "static/product-capabilities.js").read_text(encoding="utf-8")
    for identifier in ("webSearchButton", "deepResearchButton", "webSearchStarterButton"):
        assert identifier not in html
        assert identifier not in js
        assert identifier not in capabilities
    assert "window.fetch =" not in js
    assert "activeTool" not in js
    assert "payload.web_search" not in app
    assert "payload.tool =" not in js
    assert "window.PadiemSearchSources = Object.freeze({ render: renderSources });" in js
    assert "function renderSources(article, evidence, research = null)" in js

def test_search_sources_does_not_intercept_chat_streaming():
    _, _, js, _, app = sources()
    assert "streamingChatRequest" not in js
    assert "completedJsonAsPublicSse" not in js
    assert "nativeFetch" not in js
    assert "window.fetch =" not in js
    assert 'fetch("/api/chat/stream"' not in js
    assert "payload.web_search" not in app

def test_search_renderer_is_a_read_only_result_surface():
    _, _, js, _, _ = sources()
    assert "function renderSources(article, evidence, research = null)" in js
    assert "function renderResearchSummary(content, research)" in js
    assert "function publicSourceUrl(value)" in js
    assert 'setAttribute("aria-pressed"' not in js
    assert 'addEventListener("click"' not in js
    assert "window.fetch =" not in js

def test_model_selected_search_evidence_uses_the_existing_result_renderer():
    # #6776 chooses tools on the server. Keep its browser result contract while
    # removing the former client-side button and request-selection path.
    _, _, js, _, app = sources()
    assert "function renderSources(article, evidence, research = null)" in js
    assert "window.PadiemSearchSources = Object.freeze({ render: renderSources });" in js
    assert "window.PadiemSearchSources?.render?.(article, data.evidence);" in app
    assert 'if (Array.isArray(data.evidence) && data.evidence.length)' in app
    assert 'data.tool.id === "web_search"' in app
    assert "payload.web_search" not in app


def test_streaming_chat_is_not_rewritten_by_the_removed_search_modes():
    _, _, js, _, app = sources()
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

    root, html, js, _, app = sources()
    assert 'id="attachmentButton"' in html
    assert 'id="attachmentFileInput"' in html
    assert "activeTool" not in js
    assert "imageSelected" not in js
    assert "payload.web_search" not in app



def test_visible_sources_are_text_only_numbered_and_public_http_links():
    _, _, js, css, _ = sources()
    assert "Array.isArray(evidence)" in js
    assert "item && entry.url" in js
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
    assert "payload.tool =" not in js
    assert 'payload.tool = "web_search"' not in app_js
    assert 'payload.tool = "deep_research"' not in app_js
    assert "window.fetch =" not in js
    from style_contract import assert_phase1_styles_match
    assert_phase1_styles_match(
        root / "static/styles.css",
        repo / "reference/business-62-padiem-chat-v1/styles.css",
    )


def test_search_sources_javascript_syntax():
    root, _, _, _, _ = sources()
    node = shutil.which("node")
    assert node is not None
    result = subprocess.run(
        [node, "--check", str(root / "static/search-sources.js")],
        capture_output=True,
        text=True, encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
