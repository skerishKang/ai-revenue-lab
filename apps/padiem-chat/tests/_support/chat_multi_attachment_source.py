"""Parsed facts for the #261102 Chat multi-attachment frontend contract.

Raw shipped-source reads live here (reusing claw_static and html_tags); the
contract test asserts on parsed DOM attributes, parsed CSS selectors and named
locale facts instead of raw source text. Runtime behavior stays in the test.
"""
from __future__ import annotations

import locale_bundle
from _support.claw_static import sheet
from _support.html_tags import tags_for_page
from css_rules import rules_for_sheet


def frontend_facts() -> dict:
    ids = {attrs["id"] for _tag, attrs in tags_for_page("index.html") if attrs.get("id")}
    file_inputs = [
        attrs for _tag, attrs in tags_for_page("index.html")
        if attrs.get("id") == "attachmentFileInput"
    ]
    selectors = [selector for rule in rules_for_sheet("attachments.css") for selector in rule.selectors]
    app = sheet("app.js") + sheet("chat-conversation-module.js")
    file_input = file_inputs[0] if file_inputs else {}
    return {
        "multiple_file_input": (
            file_input.get("type") == "file" and "multiple" in file_input
        ),
        "chip_list_id": "attachmentChipList" in ids,
        "drop_listener": 'composerForm.addEventListener("drop"' in app,
        "dragover_listener": 'composerForm.addEventListener("dragover"' in app,
        "missing_chip_selectors": [
            selector for selector in (".attachment-chip", ".attachment-chip-invalid")
            if selector not in selectors
        ],
        "legacy_ids": [element_id for element_id in ("attachmentThumb", "removeAttachment") if element_id in ids],
        "no_inner_html": "innerHTML" not in app,
    }


def locale_facts() -> dict:
    source = locale_bundle.SOURCE.read_text(encoding="utf-8")
    return {
        "missing": [
            token for token in (
                "attachment-count-limit",
                "attachment-raw-single",
                "메시지 하나에는 파일을 최대 {count}개",
                "사진·원본 문서는 한 번에 하나만",
            ) if token not in source
        ]
    }
