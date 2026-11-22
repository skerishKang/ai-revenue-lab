"""Parsed views for the #4471 conversation-search contracts (#8060 33차).

Raw file access stays here (via the shared ``claw_static`` sheet/server
helpers and the CSS rule parser); the contract tests receive parsed values —
JS identifiers/calls/comparisons, AST route facts and CSS declarations — and
assert on those values instead of pinning shipped source spelling. No
runtime file is changed.
"""
from __future__ import annotations

import ast
import re

from _support.claw_static import server_source, sheet

_IDENT = r"[A-Za-z_$][\w$]*"
_CHAIN = rf"{_IDENT}(?:\.{_IDENT})*"
_CALL_RX = re.compile(rf"({_CHAIN})\s*\(")
_COMPARE_RX = re.compile(
    rf"({_CHAIN})\s*(!==|===|!=|==)\s*({_CHAIN}|true|false|null)"
)
_ASSIGN_RX = re.compile(
    rf"({_CHAIN})\s*=(?!=)\s*(\"[^\"]*\"|'[^']*'|true|false|null|{_CHAIN}|\d+)"
)
_INCREMENT_RX = re.compile(
    rf"\+\+\s*({_IDENT})|({_IDENT})\s*\+=\s*(\d+)|({_IDENT})\s*\+\+"
)
_STRING_RX = re.compile(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`(?:\\.|[^`\\])*`", re.S)
_MEMBER_RX = re.compile(rf"{_CHAIN}(?:\.{_IDENT})+")
_KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "typeof", "new"}


def _strip_js_comments(text: str) -> str:
    """Drop // and block comments outside strings, keeping newlines."""
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


def _balanced_paren(text: str, open_index: int) -> str:
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
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[open_index + 1:i]
        i += 1
    return text[open_index + 1:]


def _calls_with_pos(text: str) -> list[tuple[int, str]]:
    calls: list[tuple[int, str]] = []
    for match in _CALL_RX.finditer(text):
        callee = match.group(1)
        if callee in _KEYWORDS:
            continue
        before = text[max(0, match.start() - 12):match.start()]
        if re.search(r"\bfunction\s*$", before):
            continue
        calls.append((match.start(), callee))
    return calls


def _call_details(text: str) -> list[tuple[int, str, str]]:
    details: list[tuple[int, str, str]] = []
    for match in _CALL_RX.finditer(text):
        callee = match.group(1)
        if callee in _KEYWORDS:
            continue
        before = text[max(0, match.start() - 12):match.start()]
        if re.search(r"\bfunction\s*$", before):
            continue
        args = _balanced_paren(text, match.end() - 1)
        details.append((match.start(), callee, " ".join(args.split())))
    return details


_IF_RX = re.compile(rf"\bif\s*\(\s*(!)?\s*({_CHAIN})\s*\)")
_LISTENER_RX = re.compile(rf"({_CHAIN})\.addEventListener\(\s*[\"']([^\"']+)[\"']")


def _if_conditions_with_pos(text: str) -> list[tuple[int, str]]:
    return [
        (m.start(), f"if:{'!' if m.group(1) else ''}{m.group(2)}")
        for m in _IF_RX.finditer(text)
    ]


def _comparisons_with_pos(text: str) -> list[tuple[int, str, str, str]]:
    return [
        (m.start(), m.group(1), m.group(2), m.group(3))
        for m in _COMPARE_RX.finditer(text)
    ]


def _assignments_with_pos(text: str) -> list[tuple[int, str, str]]:
    return [(m.start(), m.group(1), m.group(2)) for m in _ASSIGN_RX.finditer(text)]


def _increments_with_pos(text: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for m in _INCREMENT_RX.finditer(text):
        if m.group(1):
            out.append((m.start(), f"++{m.group(1)}"))
        elif m.group(2):
            out.append((m.start(), f"{m.group(2)}+={m.group(3)}"))
        elif m.group(4):
            out.append((m.start(), f"{m.group(4)}++"))
    return out


def _events(text: str) -> list[str]:
    items: list[tuple[int, str]] = []
    items.extend((pos, callee) for pos, callee in _calls_with_pos(text))
    items.extend(
        (pos, f"{left}{op}{right}")
        for pos, left, op, right in _comparisons_with_pos(text)
    )
    items.extend((pos, f"assign:{target}={value}") for pos, target, value in _assignments_with_pos(text))
    items.extend(_increments_with_pos(text))
    items.extend(_if_conditions_with_pos(text))
    items.sort(key=lambda item: item[0])
    return [label for _pos, label in items]


def _facts(text: str) -> dict:
    return {
        "calls": [callee for _pos, callee in _calls_with_pos(text)],
        "call_args": [(callee, args) for _pos, callee, args in _call_details(text)],
        "comparisons": [
            f"{left}{op}{right}" for _pos, left, op, right in _comparisons_with_pos(text)
        ],
        "assignments": {target: value for _pos, target, value in _assignments_with_pos(text)},
        "if_conditions": [label for _pos, label in _if_conditions_with_pos(text)],
        "event_listeners": [(t, e) for t, e in _LISTENER_RX.findall(text)],
        "events": _events(text),
        "identifiers": set(re.findall(rf"{_IDENT}", text)),
        "member_chains": {
            prefix
            for chain in _MEMBER_RX.findall(text)
            for prefix in (".".join(chain.split(".")[:i]) for i in range(1, len(chain.split(".")) + 1))
            if "." in prefix
        },
        "string_literals": set(_string_literals(text)),
    }


def _balanced_block(text: str, open_index: int) -> str:
    """Text from the brace at open_index through its match (string-aware)."""
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


def _function_block(text: str, name: str) -> str:
    match = re.search(rf"(?:async\s+)?function\s+{re.escape(name)}\s*\(", text)
    if match is None:
        raise AssertionError(f"{name} function not found in shipped JS")
    open_index = text.index("{", match.end())
    return _balanced_block(text, open_index)


def _listener_block(text: str, target: str, event: str) -> str:
    match = re.search(
        rf"{re.escape(target)}\.addEventListener\(\s*[\"']{re.escape(event)}[\"']",
        text,
    )
    if match is None:
        raise AssertionError(f"{target} {event} listener not found in shipped JS")
    open_index = text.index("{", match.end())
    return _balanced_block(text, open_index)


def search_module_facts() -> dict:
    """Parsed facts for conversation-search.js (comments stripped)."""
    text = _executable("conversation-search.js")
    facts = _facts(text)

    endpoint_match = re.search(rf"\bconst\s+SEARCH_ENDPOINT\s*=\s*\"([^\"]+)\"", text)
    facts["endpoint"] = endpoint_match.group(1) if endpoint_match else None

    available_match = re.search(rf"\blet\s+available\s*=\s*(true|false)\b", text)
    facts["available_initial"] = (
        available_match.group(1) == "true" if available_match else None
    )

    facts["auth_flags"] = {
        name: value == "true"
        for name, value in re.findall(
            r"\bauth\.(loaded|authenticated|historyReady)\s*===\s*(true|false)\b", text
        )
    }

    fetch_calls: list[dict] = []
    for match in re.finditer(rf"(?<![\w$.])fetch\s*\(", text):
        rest = text[match.end():].lstrip()
        target = ""
        if rest.startswith("`"):
            end = rest.find("`", 1)
            target = rest[:end + 1] if end != -1 else rest
        elif rest[:1] in "\"'":
            end = rest.find(rest[0], 1)
            target = rest[:end + 1] if end != -1 else rest
        before = text[max(0, match.start() - 12):match.start()]
        fetch_calls.append({"awaited": "await" in before, "target": target})
    facts["fetch_calls"] = fetch_calls

    facts["regex_tests"] = [
        (pattern, arg)
        for pattern, arg in re.findall(
            r"/((?:\\.|[^/\\])+)/[gimsuy]*\s*\.test\(\s*([A-Za-z_$][\w$]*)\s*\)", text
        )
    ]

    facts["event_listeners"] = [
        (target, event)
        for target, event in re.findall(
            rf"({_CHAIN})\.addEventListener\(\s*[\"']([^\"']+)[\"']", text
        )
    ]
    return facts


def search_function_facts(name: str) -> dict:
    """Parsed facts for one named function in conversation-search.js."""
    return _facts(_function_block(_executable("conversation-search.js"), name))


def search_listener_facts(target: str, event: str) -> dict:
    """Parsed facts for one addEventListener callback body."""
    return _facts(_listener_block(_executable("conversation-search.js"), target, event))


def app_opener_facts() -> dict:
    """The canonical opener app.js publishes, parsed from its assignment."""
    text = _executable("app.js")
    match = re.search(r"window\.PadiemChatConversationOpener\s*=\s*Object\.freeze\(\s*\{", text)
    if match is None:
        raise AssertionError("PadiemChatConversationOpener assignment not found in app.js")
    block = _balanced_block(text, text.index("{", match.start() + len("window.PadiemChatConversationOpener")))
    open_match = re.search(
        rf"\bopen\s*:\s*\(([^)]*)\)\s*=>\s*({_IDENT})\s*\(([^)]*)\)", block
    )
    facts = _facts(block)
    facts["open_param"] = open_match.group(1).strip() if open_match else None
    facts["open_callee"] = open_match.group(2) if open_match else None
    facts["open_arg"] = open_match.group(3).strip() if open_match else None
    facts["frozen"] = "Object.freeze" in text[match.start():match.end() + 1]
    facts["data_conversation_id_literals"] = {
        value for value in _string_literals(text) if value == "data-conversation-id"
    }
    return facts


def search_route_facts() -> dict:
    """Route registration and handler guards, parsed with ast (not text)."""
    factory_tree = ast.parse(server_source("app_factory"))
    factory_routes: list[tuple[str, str, tuple[str, ...]]] = []
    for node in ast.walk(factory_tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Name) and func.id == "Route"):
            continue
        if len(node.args) < 2 or not isinstance(node.args[0], ast.Constant):
            continue
        handler = node.args[1].id if isinstance(node.args[1], ast.Name) else None
        methods: tuple[str, ...] = ()
        for keyword in node.keywords:
            if keyword.arg == "methods" and isinstance(keyword.value, (ast.List, ast.Tuple)):
                methods = tuple(
                    element.value for element in keyword.value.elts
                    if isinstance(element, ast.Constant)
                )
        if handler is not None:
            factory_routes.append((str(node.args[0].value), handler, methods))

    routes_tree = ast.parse(server_source("conversation_routes"))
    search_fn = next(
        node for node in ast.walk(routes_tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "api_conversation_search"
    )
    called_nodes: list[tuple[int, int, str, tuple[str, ...]]] = []
    status_nodes: list[tuple[int, int, int]] = []
    strings: set[str] = set()
    guard_nodes: list[tuple[int, int, str]] = []
    for node in ast.walk(search_fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            args = tuple(
                arg.id for arg in node.args if isinstance(arg, ast.Name)
            )
            called_nodes.append((node.lineno, node.col_offset, node.func.id, args))
            for keyword in node.keywords:
                if keyword.arg == "status_code" and isinstance(keyword.value, ast.Constant):
                    status_nodes.append((node.lineno, node.col_offset, int(keyword.value.value)))
        if isinstance(node, ast.If):
            test = node.test
            if isinstance(test, ast.UnaryOp) and isinstance(test.operand, ast.Call) and isinstance(test.operand.func, ast.Name):
                guard_nodes.append((node.lineno, node.col_offset, test.operand.func.id))
            elif isinstance(test, ast.Call) and isinstance(test.func, ast.Name):
                guard_nodes.append((node.lineno, node.col_offset, test.func.id))
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            strings.add(node.value)
    called_nodes.sort()
    status_nodes.sort()
    guard_nodes.sort()
    called = [(name, args) for _line, _col, name, args in called_nodes]
    status_codes = [code for _line, _col, code in status_nodes]
    guard_calls = [name for _line, _col, name in guard_nodes]
    search_routes = [route for route in factory_routes if route[0] == "/api/conversations/search"]
    return {
        "factory_search_routes": search_routes,
        "called": called,
        "status_codes": status_codes,
        "string_constants": strings,
        "guard_calls": guard_calls,
    }


def search_css_declarations(selector: str) -> dict[str, str]:
    """Declarations of the first rule for a selector in history.css."""
    from css_rules import find_rules_with_selector, rules_for_sheet

    rules = find_rules_with_selector(rules_for_sheet("history.css"), selector)
    return dict(rules[0].declarations) if rules else {}
