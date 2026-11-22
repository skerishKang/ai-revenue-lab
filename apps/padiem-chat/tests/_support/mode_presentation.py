"""Parsed views for the #1815 mode-presentation contracts (#8060 41차).

Raw file access stays here (via the shared ``claw_static`` sheet/locale
helpers and the CSS rule parser); the contract tests receive parsed values —
JS literals/calls/objects, locale keys/bindings, CSS declarations, HTML
element facts and QA-script AST facts — and assert on those values instead
of pinning shipped source spelling. No runtime file is changed.
"""
from __future__ import annotations

import ast
import re
from html.parser import HTMLParser
from pathlib import Path

import locale_bundle

from _support.claw_static import locale_source, sheet

_IDENT = r"[A-Za-z_$][\w$]*"
_STRING_RX = re.compile(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`(?:\\.|[^`\\])*`", re.S)
_PAIR_RX = re.compile(rf"\"?({_IDENT})\"?\s*:\s*\"([^\"]+)\"")
_REPO = Path(__file__).resolve().parents[4]


def _strip_js_comments(text: str) -> str:
    out: list[str] = []
    i, n = 0, len(text)
    quote = ""
    while i < n:
        ch = text[i]
        if quote:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in "\"'`":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j == -1 else j
            out.append("".join(c if c == "\n" else " " for c in text[i:j]))
            i = j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j == -1 else j + 2
            out.append("".join(c if c == "\n" else " " for c in text[i:j]))
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _executable(sheet_name: str) -> str:
    return _strip_js_comments(sheet(sheet_name))


def _string_literals(text: str) -> list[str]:
    return [match.group(0)[1:-1] for match in _STRING_RX.finditer(text)]


def js_string_literals(sheet_name: str) -> set[str]:
    return set(_string_literals(_executable(sheet_name)))


def js_identifiers(sheet_name: str) -> set[str]:
    return set(re.findall(rf"{_IDENT}", _executable(sheet_name)))


def js_property_string_pairs(sheet_name: str) -> set[tuple[str, str]]:
    return set(_PAIR_RX.findall(_executable(sheet_name)))


def _balanced_block(text: str, open_index: int) -> str:
    depth = 0
    quote = ""
    i = open_index
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "\"'`":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[open_index:i + 1]
        i += 1
    raise AssertionError("unbalanced braces in shipped JS")


def create_mode_option_string_args() -> set[str]:
    text = _executable("product-capabilities.js")
    return set(re.findall(r"createModeOption\(\s*\"([^\"]+)\"", text))


def _tier_copy_block() -> str:
    text = _executable("product-capabilities.js")
    match = re.search(r"\bconst\s+TIER_COPY\s*=\s*Object\.freeze\(\s*\{", text)
    if match is None:
        raise AssertionError("TIER_COPY assignment not found in product-capabilities.js")
    return _balanced_block(text, text.index("{", match.end() - 1))


def tier_copy_literals() -> set[str]:
    """String literals inside the TIER_COPY object (keys and copy values)."""
    return set(_string_literals(_tier_copy_block()))


def tier_copy_facts() -> dict[str, set[str]]:
    """The TIER_COPY table's vocabulary — string literals and identifiers."""
    block = _tier_copy_block()
    return {
        "literals": set(_string_literals(block)),
        "identifiers": set(re.findall(rf"{_IDENT}", block)),
    }


def streaming_payload_entries() -> dict[str, str]:
    """The request payload object literal in chat-streaming-module.js."""
    text = _executable("chat-streaming-module.js")
    match = re.search(r"\bconst\s+payload\s*=\s*\{([^}]*)\}", text)
    if match is None:
        raise AssertionError("payload object not found in chat-streaming-module.js")
    entries: dict[str, str] = {}
    for part in match.group(1).split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            key, _, value = part.partition(":")
            entries[key.strip()] = " ".join(value.split())
        else:
            entries[part] = part
    return entries


def locale_keys(lang: str) -> dict[str, str]:
    return dict(locale_bundle.keys(lang))


def locale_bindings() -> set[tuple[str, str, str]]:
    return set(re.findall(r"\[\"([^\"]+)\",\s*\"([^\"]+)\",\s*\"([^\"]+)\"\]", locale_source()))


_ARRAY_RX = re.compile(r"\[\s*((?:\"(?:[^\"\\]|\\.)*\"\s*,?\s*)+)\]")


def locale_array_bindings() -> set[tuple[str, ...]]:
    """Every all-string array literal in the locale bootstrap, as a tuple."""
    arrays: set[tuple[str, ...]] = set()
    for match in _ARRAY_RX.finditer(locale_source()):
        arrays.add(tuple(re.findall(r"\"((?:[^\"\\]|\\.)*)\"", match.group(1))))
    return arrays


def css_selectors(sheet_name: str) -> set[str]:
    from css_rules import rules_for_sheet

    return {selector for rule in rules_for_sheet(sheet_name) for selector in rule.selectors}


def css_declarations(sheet_name: str, selector: str) -> dict[str, str]:
    from css_rules import find_rules_with_selector, rules_for_sheet

    rules = find_rules_with_selector(rules_for_sheet(sheet_name), selector)
    return dict(rules[0].declarations) if rules else {}


def css_all_declaration_pairs(sheet_name: str) -> set[tuple[str, str]]:
    from css_rules import rules_for_sheet

    return {
        (prop, value)
        for rule in rules_for_sheet(sheet_name)
        for prop, value in rule.declarations.items()
    }


def css_media_conditions(sheet_name: str) -> set[str]:
    from css_rules import rules_for_sheet

    return {rule.media for rule in rules_for_sheet(sheet_name) if rule.media}


def css_rule_selector_lists(sheet_name: str, selector: str) -> list[list[str]]:
    from css_rules import find_rules_with_selector, rules_for_sheet

    return [list(rule.selectors) for rule in find_rules_with_selector(rules_for_sheet(sheet_name), selector)]


def css_custom_property(sheet_name: str, prop: str) -> str | None:
    from css_rules import rules_for_sheet

    for rule in rules_for_sheet(sheet_name):
        if prop in rule.declarations:
            return rule.declarations[prop]
    return None


class _Element:
    def __init__(self, tag: str, attrs: dict[str, str]):
        self.tag = tag
        self.attrs = attrs
        self.children: list[_Element] = []


_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.roots: list[_Element] = []
        self.stack: list[_Element] = []
        self.texts: list[str] = []

    def _add(self, tag: str, attrs) -> _Element:
        element = _Element(tag, dict(attrs))
        if self.stack:
            self.stack[-1].children.append(element)
        else:
            self.roots.append(element)
        return element

    def handle_starttag(self, tag, attrs):
        element = self._add(tag, attrs)
        if tag not in _VOID:
            self.stack.append(element)

    def handle_startendtag(self, tag, attrs):
        self._add(tag, attrs)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data):
        if data.strip():
            self.texts.append(data.strip())


def _walk(elements: list[_Element]):
    for element in elements:
        yield element
        yield from _walk(element.children)


def _class_tokens(element: _Element) -> set[str]:
    return set(element.attrs.get("class", "").split())


def index_facts() -> dict:
    parser = _Tree()
    parser.feed(sheet("index.html"))
    parser.close()
    all_elements = list(_walk(parser.roots))

    def descendants_with_class(tag: str, class_name: str) -> list[tuple[str, dict[str, str]]]:
        for element in all_elements:
            if element.tag == tag and class_name in _class_tokens(element):
                return [(item.tag, dict(item.attrs)) for item in _walk(element.children)]
        return []

    topbar = descendants_with_class("header", "topbar")
    composer_tools = descendants_with_class("div", "composer-tools")
    return {
        "topbar_elements": topbar,
        "topbar_class_tokens": [
            set(attrs.get("class", "").split()) for _tag, attrs in topbar
        ],
        "composer_tools_elements": composer_tools,
        "text_nodes": set(parser.texts),
        "all_class_tokens": set().union(*(_class_tokens(element) for element in all_elements)) if all_elements else set(),
        "data_locale_aria_label_values": {
            element.attrs["data-locale-aria-label"]
            for element in all_elements
            if "data-locale-aria-label" in element.attrs
        },
    }


def _cert_qa_tree() -> ast.Module:
    path = _REPO / ".github/scripts/b62_product_surface_certification_browser_qa.py"
    return ast.parse(path.read_text(encoding="utf-8"))


def cert_qa_string_constants() -> set[str]:
    return {
        node.value
        for node in ast.walk(_cert_qa_tree())
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def cert_qa_dict_pairs() -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for node in ast.walk(_cert_qa_tree()):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant) and isinstance(value, ast.Constant)
                    and isinstance(key.value, str) and isinstance(value.value, str)
                ):
                    pairs.add((key.value, value.value))
    return pairs
