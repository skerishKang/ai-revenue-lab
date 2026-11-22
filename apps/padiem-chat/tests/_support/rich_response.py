"""#8060 parsed facts for the rich-response static assets.

Raw reads of the shipped static files stay here. Contract tests assert parsed
markup, parsed declarations and parsed source values, so a spelling-only edit
in a static file does not break them.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

from css_rules import declaration, rules_for_sheet

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "static"

STRUCTURE_CONSTANTS = (
    "HEADING_PATTERN", "UNORDERED_PATTERN", "ORDERED_PATTERN", "QUOTE_PATTERN",
    "FENCE_PATTERN", "FENCE_CLOSE_PATTERN", "TABLE_SEPARATOR_CELL", "tableAt",
    "INLINE_PATTERN", "INLINE_LINK_PATTERN", "appendInline", "safeInlineLink",
    "NON_ANSWER_PARAGRAPH_CLASSES",
)
UNSAFE_SINKS = (
    "innerHTML", "insertAdjacentHTML", "eval(", "new Function",
    'setAttribute("onclick"', "fetch(", "WebSocket", "EventSource",
)
LEGACY_CLIPBOARD = ("navigator.clipboard", "document.execCommand")


def static_root() -> Path:
    return ROOT


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


class _Head(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stylesheets: list[str] = []
        self.scripts: list[str] = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "link" and values.get("rel") == "stylesheet":
            self.stylesheets.append(values.get("href", ""))
        if tag == "script" and "src" in values:
            self.scripts.append(values["src"])


def markup_facts() -> dict:
    parser = _Head()
    parser.feed(_read("index.html"))
    parser.close()
    return {"stylesheets": tuple(parser.stylesheets), "scripts": tuple(parser.scripts)}


def _string_assignment(source: str, name: str) -> tuple[str, ...]:
    return tuple(re.findall(re.escape(name) + r'\s*=\s*"([^"]*)"', source))


def js_facts() -> dict:
    source = _read("rich-response.js")
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.MULTILINE)
    blob = re.search(r'new Blob\((\[[^\]]*\]), \{ type: "([^"]+)" \}\)', code)
    return {
        "create_element_tags": tuple(sorted(set(re.findall(
            r'createElement\("([a-z]+)"\)', code)))),
        "text_node_used": "document.createTextNode" in code,
        "text_content_assignments": code.count(".textContent ="),
        "unsafe_sinks": tuple(sink for sink in UNSAFE_SINKS if sink in code),
        "structure_constants": tuple(name for name in STRUCTURE_CONSTANTS if name in code),
        "copy_button_text": _string_assignment(code, "copy.textContent"),
        "download_button_text": _string_assignment(code, "download.textContent"),
        "copy_api_fallback": tuple(re.findall(
            r"const api = (window\.PadiemAnswerCopy \|\| window\.SharedAnswerCopy);", code)),
        "legacy_clipboard": tuple(name for name in LEGACY_CLIPBOARD if name in code),
        "blob_arguments": (blob.group(1), blob.group(2)) if blob else (),
        "object_url_apis": tuple(name for name in
                                ("URL.createObjectURL", "URL.revokeObjectURL") if name in code),
        "link_protocol_guard": bool(re.search(
            r'parsed\.protocol !== "http:" && parsed\.protocol !== "https:"', code)),
        "anchor_target": _string_assignment(code, "anchor.target"),
        "anchor_rel": _string_assignment(code, "anchor.rel"),
        "template_created": 'createElement("template")' in code,
        "source_text_node": ("source.content.appendChild("
                             "document.createTextNode(rawParagraph.textContent))" in code),
        "raw_replaced": "rawParagraph.replaceWith(source, rich)" in code,
        "retired_hidden_source": tuple(name for name in
                                       ("rawParagraph.hidden = true",
                                        'rawParagraph.classList.add("rich-response-source")')
                                       if name in code),
    }


def css_facts() -> dict:
    rules = rules_for_sheet("rich-response.css")
    selectors = tuple(selector for rule in rules for selector in rule.selectors)
    classes = tuple(sorted(set(re.findall(r"\.([a-z][a-z0-9-]+)", " ".join(selectors)))))
    overflow = tuple(value for rule in rules
                     if (value := declaration(rule, "overflow-x")) is not None)
    return {"selectors": selectors, "classes": classes, "overflow_x": overflow}


def outputs_facts() -> dict:
    source = _read("outputs.js")
    return {
        "find_paragraph": bool(re.search(
            r'Array\.from\(content\.children\)\.find\(\(node\) => node\.tagName === "P"\)',
            source)),
        "template_query": "template.rich-response-source" in source,
        "text_content_copy": "outputContent.textContent = activeOutput.content" in source,
    }
