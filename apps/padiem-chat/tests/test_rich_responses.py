from __future__ import annotations

import shutil
import subprocess

from _support.rich_response import (
    STRUCTURE_CONSTANTS,
    css_facts,
    js_facts,
    markup_facts,
    outputs_facts,
    static_root,
)


def test_rich_response_assets_are_additive_and_ordered():
    facts = markup_facts()
    assert "./rich-response.css" in facts["stylesheets"]
    scripts = facts["scripts"]
    assert scripts.index("./app.js") < scripts.index("./rich-response.js") < scripts.index("./outputs.js")


def test_rich_renderer_is_dom_safe_and_has_no_execution_path():
    facts = js_facts()
    assert facts["create_element_tags"]
    assert facts["text_node_used"] is True
    assert facts["text_content_assignments"] > 0
    assert facts["unsafe_sinks"] == ()


def test_supported_structures_and_local_actions_are_present():
    js = js_facts()
    assert set(js["structure_constants"]) == set(STRUCTURE_CONSTANTS)
    assert {"blockquote", "table", "code"}.issubset(js["create_element_tags"])
    assert js["copy_button_text"] == ("복사",)
    assert js["download_button_text"] == ("CSV 다운로드",)
    assert js["copy_api_fallback"] == ("window.PadiemAnswerCopy || window.SharedAnswerCopy",)
    assert js["legacy_clipboard"] == ()
    assert "\\uFEFF" in js["blob_arguments"][0]
    assert js["blob_arguments"][1] == "text/csv;charset=utf-8"
    assert set(js["object_url_apis"]) == {"URL.createObjectURL", "URL.revokeObjectURL"}
    css = css_facts()
    assert {"rich-code-block", "rich-table-block"}.issubset(css["classes"])
    assert "auto" in css["overflow_x"]


def test_raw_answer_is_kept_once_in_an_inert_source_after_visual_enhancement():
    # The completed answer text exists exactly once in the DOM: the visible
    # rich blocks. The raw markdown source lives in an inert <template> that
    # is never rendered, announced, or selected by copy/scan queries — the
    # retired hidden-paragraph contract duplicated the text for the DOM.
    js = js_facts()
    assert js["template_created"] is True
    assert js["source_text_node"] is True
    assert js["raw_replaced"] is True
    assert js["retired_hidden_source"] == ()
    assert "NON_ANSWER_PARAGRAPH_CLASSES" in js["structure_constants"]
    node = shutil.which("node")
    if node is not None:
        static_dir = static_root() / "static"
        script = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const staticDir = process.argv[1];
const modSrc = fs.readFileSync(path.join(staticDir, "chat-pc-run-module.js"), "utf8");
const appended = [];
const ctx = vm.createContext({
  document: { createElement: (tag) => ({ tagName: tag.toUpperCase(), textContent: "" }) },
  window: { PadiemChatLifecycle: {} },
  PadiemChatLifecycle: { set() {} },
});
vm.runInContext(modSrc, ctx, { filename: "chat-pc-run-module.js" });
const mod = ctx.window.PadiemChatPcRunModule.create({
  MESSAGE_LIFECYCLE: { COMPLETED: "completed" },
  authState: { authenticated: false },
  conversationProduct: "chat",
  conversationState: { setProduct() {}, setConversationId() {}, commitAssistant() {} },
  loadRecentConversations() {},
});
const art = {
  querySelector: () => ({ replaceChildren() {}, appendChild: (el) => appended.push(el) }),
};
mod.renderStoredPcAnswer(art, { answer: "raw markdown **answer**" }, [], { product: "chat" });
assert.equal(appended.length, 1);
assert.equal(appended[0].tagName, "P");
assert.equal(appended[0].textContent, "raw markdown **answer**");
"""
        completed = subprocess.run(
            [node, "-e", script, str(static_dir)],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
    outputs = outputs_facts()
    assert outputs["find_paragraph"] is True
    assert outputs["template_query"] is True
    assert outputs["text_content_copy"] is True


def test_inline_markdown_is_supported_without_unsafe_html_or_links():
    js = js_facts()
    constants = set(js["structure_constants"])
    assert {"INLINE_PATTERN", "INLINE_LINK_PATTERN", "appendInline", "safeInlineLink"}.issubset(constants)
    assert {"strong", "em", "code", "a"}.issubset(js["create_element_tags"])
    assert js["link_protocol_guard"] is True
    assert js["anchor_target"] == ("_blank",)
    assert js["anchor_rel"] == ("noopener noreferrer",)
    assert js["unsafe_sinks"] == ()


def test_phase1_styles_remain_byte_identical():
    root = static_root()
    repo = root.parents[1]
    from style_contract import assert_phase1_styles_match
    assert_phase1_styles_match(
        root / "static/styles.css",
        repo / "reference/business-62-padiem-chat-v1/styles.css",
    )


def test_rich_response_javascript_syntax():
    node = shutil.which("node")
    assert node is not None
    result = subprocess.run(
        [node, "--check", str(static_root() / "static/rich-response.js")],
        capture_output=True,
        text=True, encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
