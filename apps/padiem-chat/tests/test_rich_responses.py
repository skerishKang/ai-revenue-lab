from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def sources():
    root = Path(__file__).resolve().parents[1]
    return (
        root,
        (root / "static/index.html").read_text(encoding="utf-8"),
        (root / "static/rich-response.js").read_text(encoding="utf-8"),
        (root / "static/rich-response.css").read_text(encoding="utf-8"),
        (root / "static/app.js").read_text(encoding="utf-8"),
        (root / "static/outputs.js").read_text(encoding="utf-8"),
    )


def test_rich_response_assets_are_additive_and_ordered():
    _, html, _, _, _, _ = sources()
    assert '<link rel="stylesheet" href="./rich-response.css" />' in html
    app_index = html.index('<script src="./app.js"></script>')
    rich_index = html.index('<script src="./rich-response.js"></script>')
    outputs_index = html.index('<script src="./outputs.js"></script>')
    assert app_index < rich_index < outputs_index


def test_rich_renderer_is_dom_safe_and_has_no_execution_path():
    _, _, js, _, _, _ = sources()
    assert "document.createElement" in js
    assert "document.createTextNode" in js
    assert ".textContent =" in js
    assert "innerHTML" not in js
    assert "insertAdjacentHTML" not in js
    assert "eval(" not in js
    assert "new Function" not in js
    assert "setAttribute(\"onclick\"" not in js
    assert "fetch(" not in js
    assert "WebSocket" not in js
    assert "EventSource" not in js


def test_supported_structures_and_local_actions_are_present():
    _, _, js, css, _, _ = sources()
    assert "HEADING_PATTERN" in js
    assert "UNORDERED_PATTERN" in js and "ORDERED_PATTERN" in js
    assert "QUOTE_PATTERN" in js
    assert "FENCE_PATTERN" in js and "FENCE_CLOSE_PATTERN" in js
    assert "TABLE_SEPARATOR_CELL" in js and "tableAt(" in js
    assert 'document.createElement("blockquote")' in js
    assert 'document.createElement("table")' in js
    assert 'document.createElement("code")' in js
    assert 'copy.textContent = "복사"' in js
    assert 'download.textContent = "CSV 다운로드"' in js
    assert "navigator.clipboard" in js and "document.execCommand" in js
    assert 'new Blob(["\\uFEFF", csv], { type: "text/csv;charset=utf-8" })' in js
    assert "URL.createObjectURL" in js and "URL.revokeObjectURL" in js
    assert "rich-code-block" in css and "rich-table-block" in css
    assert "overflow-x: auto" in css


def test_raw_answer_remains_phase12_source_after_visual_enhancement():
    _, _, js, _, app_js, outputs_js = sources()
    insert_at = js.index('rawParagraph.insertAdjacentElement("afterend", rich)')
    hide_at = js.index("rawParagraph.hidden = true")
    assert insert_at < hide_at
    assert 'rawParagraph.classList.add("rich-response-source")' in js
    assert 'paragraph.textContent = result.answer' in app_js
    assert 'Array.from(content.children).find((node) => node.tagName === "P")' in outputs_js
    assert 'paragraph.textContent.trim()' in outputs_js
    assert "outputContent.textContent = activeOutput.content" in outputs_js


def test_inline_markdown_is_supported_without_unsafe_html_or_links():
    _, _, js, _, _, _ = sources()
    assert "INLINE_PATTERN" in js
    assert "INLINE_LINK_PATTERN" in js
    assert "appendInline(" in js
    assert 'document.createElement("strong")' in js
    assert 'document.createElement("em")' in js
    assert 'document.createElement("code")' in js
    assert 'document.createElement("a")' in js
    assert "safeInlineLink(" in js
    assert 'parsed.protocol !== "http:" && parsed.protocol !== "https:"' in js
    assert 'anchor.target = "_blank"' in js
    assert 'anchor.rel = "noopener noreferrer"' in js
    assert "innerHTML" not in js
    assert "insertAdjacentHTML" not in js


def test_phase1_styles_remain_byte_identical():
    root, _, _, _, _, _ = sources()
    repo = root.parents[1]
    assert (root / "static/styles.css").read_bytes() == (
        repo / "reference/business-62-padiem-chat-v1/styles.css"
    ).read_bytes()


def test_rich_response_javascript_syntax():
    root, _, _, _, _, _ = sources()
    node = shutil.which("node")
    assert node is not None
    result = subprocess.run(
        [node, "--check", str(root / "static/rich-response.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
