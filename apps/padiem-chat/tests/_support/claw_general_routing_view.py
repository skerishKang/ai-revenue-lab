"""Parsed views of the #3531 Claw general-routing static contracts (#8060 58차).

Every shipped-source read lives here (reusing claw_static, html_tags and
css_rules); the test receives named facts — parsed selectors, counts, symbol
presence and absence lists — and asserts on those instead of raw source text.
"""
from __future__ import annotations

import locale_bundle
from _r5_function_source import definition_source, function_body
from _support.claw_static import sheet
from _support.html_tags import tags_for_page
from css_rules import rules_for_sheet


# ── shipped source readers (this module only) ──────────────────────────────


def app_js() -> str:
    return sheet("app.js")


def nav_js() -> str:
    return sheet("chat-nav-module.js")


def claw_form() -> str:
    return sheet("chat-claw-form-module.js")


def claw_run() -> str:
    return sheet("chat-claw-run-module.js")


def stream_js() -> str:
    return sheet("chat-streaming-module.js")


def transport_js() -> str:
    return sheet("chat-transport.js")


def session_js() -> str:
    return sheet("claw-session.js")


def memory_module() -> str:
    return sheet("chat-memory-module.js")


def workspace_css() -> str:
    return sheet("claw-workspace.css")


def styles_css() -> str:
    return sheet("styles.css")


def index_html() -> str:
    return sheet("index.html")


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def _index_meta() -> tuple[set[str], set[str]]:
    tags = tags_for_page("index.html")
    return (
        {attrs["id"] for _tag, attrs in tags if attrs.get("id")},
        {attrs["data-locale-key"] for _tag, attrs in tags if attrs.get("data-locale-key")},
    )


# ── facts: composer submit and quotation workflow ──────────────────────────


def composer_submit_facts() -> dict:
    source = app_js()
    start = source.index('form.addEventListener("submit"')
    end = source.index("\n  });", start)
    handler = source[start:end]
    return {
        "submits_prompt": "submitPrompt(input.value)" in handler,
        "forbidden": [token for token in ("clawManualForm", "dataset.state", "requestSubmit") if token in handler],
    }


def static_diversion_tokens() -> list[str]:
    source = app_js()
    return [token for token in ("clawManualForm.requestSubmit()",) if token in source]


def manual_workflow_facts() -> dict:
    form = claw_form()
    run = claw_run()
    html = index_html()
    return {
        "form_submit_listener": 'clawManualForm.addEventListener("submit"' in form,
        "preview_fetch": 'fetch("/api/claw/manual-intake/preview"' in form,
        "execute_fetch": 'fetch("/api/claw/manual-intake/execute"' in run,
        "action_value": "clawAction?.value" in form,
        "missing_actions": [action for action in ('"quote"', '"order"', '"reply"', '"summary"') if action not in html],
    }


def transport_facts() -> dict:
    transport = transport_js()
    app = app_js()
    stream = stream_js()
    return {
        "stream_fetch": 'fetch("/api/chat/stream"' in transport,
        "chat_fetch": 'fetch("/api/chat"' in transport,
        "app_request_answer_absent": "async function requestAnswer(" not in app,
        "streaming_provided": 'app.provide("streaming",' in app,
        "request_answer_in_stream": "async function requestAnswer(" in stream,
        "streaming_answer_call": "deps.requestStreamingAnswer(\n        article,\n        payload," in stream,
        "submit_prompt_definition": "async function submitPrompt(text, selectedSkill)" in definition_source(
            "submitPrompt", prefix="async function "
        ),
    }


# ── facts: workspace views and entry controls ──────────────────────────────


def view_facts() -> dict:
    nav = nav_js()
    app = app_js()
    session = session_js()
    general = function_body("openClawWorkspace")
    manual = function_body("openClawManual")
    return {
        "general_view_set": 'clawWorkspace.dataset.view = "general"' in general,
        "general_manual_hidden": "if (deps.clawManualForm) deps.clawManualForm.hidden = true;" in general,
        "manual_view_set": 'clawWorkspace.dataset.view = "manual"' in manual,
        "manual_visible": "if (deps.clawManualForm) deps.clawManualForm.hidden = false;" in manual,
        "nav_general_count": nav.count('clawWorkspace.dataset.view = "general"'),
        "session_bind": "window.PadiemClawSession.bind({" in app,
        "general_reset_count": (
            nav.count('workspace.dataset.view = "general"')
            + session.count('workspace.dataset.view = "general"')
        ),
        "auth_guard_before_reset": (
            session.index("if (authenticated) return;")
            < session.index('workspace.dataset.view = "general"')
        ),
        "nav_manual_count": nav.count('clawWorkspace.dataset.view = "manual"'),
    }


def manual_entry_facts() -> dict:
    ids, locale_keys = _index_meta()
    html = index_html()
    wrap = html.split('class="composer-wrap"', 1)[1]
    return {
        "entry_bar_id": "clawManualEntryBar" in ids,
        "entry_button_id": "clawManualEntryButton" in ids,
        "locale_key": "claw-manual-entry" in locale_keys,
        "bar_in_wrap": 'id="clawManualEntryBar"' in wrap,
        "click_listener": 'clawManualEntryButton.addEventListener("click", openClawManual)' in nav_js(),
        "wire_call": 'navModuleInstance.wireNavEntryListeners();' in app_js(),
        "workspace_title": "clawWorkspaceTitle" in ids,
        "entry_bar_lookup_in_nav": 'document.getElementById("clawManualEntryBar")' in nav_js(),
    }


# ── facts: CSS surface ────────────────────────────────────────────────────


def workspace_selectors() -> list[str]:
    return [selector for rule in rules_for_sheet("claw-workspace.css") for selector in rule.selectors]


def workspace_selector_has(needle: str) -> bool:
    """Whether a parsed workspace selector contains the reviewed component."""
    return any(needle in selector for selector in workspace_selectors())


def styles_facts() -> dict:
    styles = styles_css()
    return {
        "position_fixed": "position: fixed" in styles,
        "bottom_zero": "bottom: 0" in styles,
        "overflow_y_auto": "overflow-y: auto" in workspace_css(),
    }


def conversation_facts() -> dict:
    block = workspace_css().split('.app-shell[data-state="claw"] .conversation {', 1)[1].split("}", 1)[0]
    return {
        "calc_padding": "padding-bottom: calc(" in block,
        "clearance_fallback": "var(--padiem-composer-clearance, 280px)" in block,
        "keyboard_inset": "var(--padiem-visual-keyboard-inset, 0px)" in block,
        "no_fixed_280": "padding-bottom: 280px" not in block,
    }


# ── facts: copy, memory, sticky reserve ────────────────────────────────────


def locale_facts() -> dict:
    source = locale_source()
    return {
        "old_ko_absent": "견적서·발주서·답장 초안을 준비하는" not in source,
        "old_en_absent": "to prepare quote, order, and reply drafts" not in source,
        "new_ko": "Padiem AI 작업공간" in source,
        "new_en": "Padiem AI workspace" in source,
        "manual_entry_keys": source.count('"claw-manual-entry": "'),
    }


def memory_facts() -> dict:
    lines = index_html().splitlines()
    module = memory_module()
    app = app_js()
    form = claw_form()
    hidden_by_id = {}
    for element_id in ("clawMemoryReview", "clawApprovedMemory"):
        matching = [line for line in lines if f'id="{element_id}"' in line]
        hidden_by_id[element_id] = bool(matching) and all("hidden" in line for line in matching)
    return {
        "hidden_by_id": hidden_by_id,
        "definition_count": module.count("function renderMemoryProposalReview("),
        "app_call_count": (app + form).count("app.renderMemoryProposalReview("),
        "total_count": (app + module + form).count("renderMemoryProposalReview("),
    }
