"""Parsed views for the #4647 latest-sidebar integration (#8060).

Raw served sheets stay behind this helper (via ``claw_static``, the shared
HTML/JS parsers and ``css_rules``). Contract tests receive parsed element order,
JS calls/assignments, CSS declarations and server AST facts, and assert on those
instead of pinning shipped source spelling. No runtime file is changed.
"""
from __future__ import annotations

import ast
import re
from collections import Counter
from html.parser import HTMLParser

from css_rules import rules_for_sheet
from _support.claw_static import server_source, sheet
from _support.conversation_search_4471 import _balanced_block, _executable, _string_literals
from _support.owner_setup_page import js_facts as _base_js_facts


_CHAIN = r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*"
_ASSIGN_RX = re.compile(rf"\b({_CHAIN})\s*=(?!=)\s*([^;\n]+);")
_OPTIONAL_STATE_RX = re.compile(r"shell\?\.dataset\.state\s*!==\s*\"claw\"")


class _Node:
    def __init__(self, tag: str, attrs: dict):
        self.tag = tag
        self.attrs = attrs
        self.children: list[_Node] = []


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.roots: list[_Node] = []
        self.stack: list[_Node] = []
        self.order: list[_Node] = []

    def _add(self, tag, attrs):
        node = _Node(tag, dict(attrs))
        (self.stack[-1].children if self.stack else self.roots).append(node)
        self.order.append(node)
        return node

    def handle_starttag(self, tag, attrs):
        node = self._add(tag, attrs)
        if tag not in {"br", "hr", "img", "input", "link", "meta", "source", "wbr"}:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self._add(tag, attrs)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return


def _walk(nodes):
    for node in nodes:
        yield node
        yield from _walk(node.children)


def index_view() -> dict:
    """Parsed id/class/script facts and document order for index.html."""
    tree = _Tree()
    tree.feed(sheet("index.html"))
    tree.close()
    elements = list(_walk(tree.roots))
    return {
        "ids": [node.attrs["id"] for node in elements if node.attrs.get("id")],
        "id_counts": Counter(node.attrs["id"] for node in elements if node.attrs.get("id")),
        "class_counts": Counter(
            token for node in elements for token in node.attrs.get("class", "").split()
        ),
        "script_srcs": [
            node.attrs["src"] for node in elements
            if node.tag == "script" and node.attrs.get("src")
        ],
        "position": {
            token: index
            for index, node in enumerate(elements)
            for token in (
                ([node.attrs["id"]] if node.attrs.get("id") else [])
                + node.attrs.get("class", "").split()
            )
        },
        "in_main_panel": {
            node.attrs["id"]: any(
                ancestor.attrs.get("class") == "main-panel"
                for ancestor in _ancestors(tree.roots, node)
            )
            for node in elements if node.attrs.get("id")
        },
    }


def _ancestors(nodes, target):
    for node in nodes:
        if node is target:
            return []
        if target in _walk(node.children):
            return [node, *_ancestors(node.children, target)]
    return []


def js_view(sheet_name: str) -> dict:
    text = _executable(sheet_name)
    facts = _base_js_facts(text)
    facts["string_literals"] = set(_string_literals(text))
    facts["assignments_full"] = {
        target: " ".join(rhs.split()) for target, rhs in _ASSIGN_RX.findall(text)
    }
    facts["optional_state_gate"] = bool(_OPTIONAL_STATE_RX.search(text))
    return facts


def handler_view(sheet_name: str, marker: str) -> dict:
    """Parsed facts for one event-handler block in an executable JS sheet."""
    text = _executable(sheet_name)
    start = text.index(marker)
    open_index = text.index("{", start)
    block = _balanced_block(text, open_index)
    facts = _base_js_facts(block)
    facts["member_chains"] = set(facts["member_chains"])
    return facts


def css_media_view(sheet_name: str) -> dict:
    """CSS rules grouped by their @media condition."""
    result: dict[str, list] = {}
    for rule in rules_for_sheet(sheet_name):
        result.setdefault(rule.media or "", []).append(rule)
    return result


def css_facts(sheet_name: str) -> dict:
    rules = rules_for_sheet(sheet_name)
    return {
        "selectors": {selector for rule in rules for selector in rule.selectors},
        "declarations": {
            (prop, value) for rule in rules for prop, value in rule.declarations.items()
        },
    }


def function_param_defaults(module_name: str) -> dict[tuple[str, str], str]:
    """Default-value source for each named function parameter in a server module."""
    source = server_source(module_name)
    tree = ast.parse(source)
    result: dict[tuple[str, str], str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        args = node.args
        for arg, default in zip(args.args[-len(args.defaults):] if args.defaults else [], args.defaults):
            rendered = " ".join((ast.get_source_segment(source, default) or "").split())
            result[(node.name, arg.arg)] = rendered
    return result
