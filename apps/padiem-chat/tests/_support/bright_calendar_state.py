"""Parsed facts for the Connectors dialog brightness + Calendar READ UI contracts (#8060 37차).

Every raw ``read_text`` call for this contract lives here (reusing
``claw_static.sheet`` and ``css_rules.rules_for_sheet``); the contract test
receives parsed CSS declarations, parsed DOM attributes, a parsed locale table
and parsed connector-block facts (identifiers, assignments, calls, method
literals) and asserts on those values instead of pinning source spelling.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess

from _support.claw_static import sheet
from _support.connectors_surface import (
    app_js_text,
    calendar_module_text,
    connectors_module_text,
    index_html,
    locale_table,  # re-exported: parsed locale values, not locale source text
    strict_deps_text,
)
from _support.html_tags import tags_for_page
from css_rules import declaration, rule_selector_list_contains, rules_for_sheet

CAPABILITY_CSS = "capability-nav.css"
TOKENS_CSS = "padiem-tokens.css"
INDEX = "index.html"

DIALOG_ID = "connectorsDialog"
CALENDAR_CARD_ID = "connector:google:calendar@1"

CONNECTOR_MARKER = "// #3222 Web Claw connector truth."
CONNECTOR_END = "navModuleInstance.wireNavEntryListeners();"


# ── CSS: parsed rule declarations ───────────────────────────────────────────


def _rules() -> list:
    return rules_for_sheet(CAPABILITY_CSS)


def declarations_for(selector: str, *, with_property: str | None = None) -> dict[str, str] | None:
    """Declarations of the first authored rule matching ``selector`` exactly.

    When ``with_property`` is given, skip rules that do not declare it (several
    rules share a selector with different declarations in this sheet).
    """
    for rule in _rules():
        if rule_selector_list_contains(rule, selector):
            if with_property is None or declaration(rule, with_property) is not None:
                return dict(rule.declarations)
    return None


def all_selectors() -> list[str]:
    return [selector for rule in _rules() for selector in rule.selectors]


def select_count(selector: str) -> int:
    return sum(1 for rule in _rules() if rule_selector_list_contains(rule, selector))


def rgba(declarations: dict[str, str] | None, prop: str) -> tuple[float, float, float, float] | None:
    value = (declarations or {}).get(prop, "")
    match = re.search(
        r"rgba\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*\)",
        value,
    )
    return tuple(float(part) for part in match.groups()) if match else None  # type: ignore[return-value]


def blur_radius(value: str | None) -> float | None:
    match = re.search(r"blur\(\s*([\d.]+)\s*px\s*\)", value or "")
    return float(match.group(1)) if match else None


def inset_shadow_offsets(value: str | None) -> list[tuple[float, float, float]]:
    """Pixel offsets of every ``inset`` box-shadow layer, in authored order."""
    offsets: list[tuple[float, float, float]] = []
    for layer in (value or "").split(","):
        parts = layer.split()
        if not parts or parts[0] != "inset":
            continue
        lengths = [p for p in parts[1:] if re.fullmatch(r"-?[\d.]+(px|em|rem)?", p)]
        if len(lengths) >= 3:
            numbers = [float(re.sub(r"(px|em|rem)$", "", p)) for p in lengths[:3]]
            offsets.append((numbers[0], numbers[1], numbers[2]))
    return offsets


def token_value(name: str) -> str | None:
    for rule in rules_for_sheet(TOKENS_CSS):
        value = declaration(rule, name)
        if value is not None:
            return value
    return None


def reviewed_dialog_colors() -> dict[str, str]:
    """Color literals the dialog pins for small type and each READ state.

    Keys are ``small_type`` plus the closed READ-state vocabulary; values come
    from the shipped sheet, so a contrast check measures the shipped color.
    """
    colors: dict[str, str] = {}
    for rule in _rules():
        color = declaration(rule, "color")
        if not color or not color.startswith("#"):
            continue
        for selector in rule.selectors:
            if selector == "#connectorsDialog .capability-kicker":
                colors["small_type"] = color
            match = re.search(r'data-read-state="([a-z]+)"', selector)
            if "#connectorsDialog" in selector and match:
                colors[match.group(1)] = color
    return colors


# ── DOM: parsed attributes of the shipped connectors dialog ─────────────────


def _index_tags() -> list[tuple[str, dict[str, str | None]]]:
    return tags_for_page(INDEX)


def index_ids() -> set[str]:
    return {attrs["id"] for _tag, attrs in _index_tags() if attrs.get("id")}


def index_locale_keys() -> set[str]:
    return {attrs["data-locale-key"] for _tag, attrs in _index_tags() if attrs.get("data-locale-key")}


def dialog_card_attrs() -> dict[str, dict[str, str | None]]:
    """Attribute maps of every capability card, keyed by connector id."""
    cards: dict[str, dict[str, str | None]] = {}
    for _tag, attrs in _index_tags():
        connector_id = attrs.get("data-connector-id")
        if connector_id and "capability-card" in (attrs.get("class") or ""):
            cards[connector_id] = dict(attrs)
    return cards


def read_state_attrs() -> dict[str, str | None]:
    """Attributes of the single bounded READ-state line in the dialog."""
    found = [dict(attrs) for _tag, attrs in _index_tags() if "data-connector-read-state" in attrs]
    assert len(found) == 1, "exactly one connector READ-state line is expected"
    return found[0]


# ── JS: parsed facts from the connector block ──────────────────────────────


def connector_block_text() -> str:
    """The app.js connector block plus both modules, deps-stripped.

    This is the same reading the behavioral harnesses use. The returned text is
    only used by the forbidden-absence contracts, where absence itself is the
    reviewed invariant (R2 rule 3); the positive contracts use the parsed facts
    below.
    """
    app = app_js_text()
    assert CONNECTOR_MARKER in app and CONNECTOR_END in app
    return (
        app.split(CONNECTOR_MARKER, 1)[1].split(CONNECTOR_END, 1)[0]
        + "\n" + connectors_module_text().replace("deps.", "")
        + "\n" + calendar_module_text().replace("deps.", "")
    )


_IDENTIFIER = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")


def _code_without_comments_and_strings(text: str) -> str:
    code = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    code = re.sub(r"//[^\n]*", "", code)
    return re.sub(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|`(?:[^`\\]|\\.)*`', '""', code)


def connector_block_facts() -> dict:
    """Identifier/assignment/call/method views of the connector block."""
    text = connector_block_text()
    code = _code_without_comments_and_strings(text)
    return {
        "text": text,
        "identifiers": set(_IDENTIFIER.findall(code)),
        "method_values": re.findall(r'\bmethod\s*:\s*"([A-Za-z]+)"', text),
        "assignments": [
            (match.group(1), match.group(2).strip())
            for match in re.finditer(r"\b([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?![=>])([^;]+);", code)
        ],
        "awaited_calls": set(re.findall(r"\bawait\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(", code)),
        "calls": [
            (match.group(1), match.group(2).strip())
            for match in re.finditer(r"\b([A-Za-z_$][A-Za-z0-9_$]*)\s*\(\s*([^()]*)\s*\)", code)
        ],
    }


def app_js_hangul_lines() -> list[tuple[int, str]]:
    hangul = re.compile(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]")
    return [
        (index + 1, line.strip())
        for index, line in enumerate(app_js_text().splitlines())
        if hangul.search(line)
    ]


# ── Behavior: run the shipped Calendar module in Node ───────────────────────


def run_calendar_module(body: str) -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required"
    script = (
        "const window = {};\n"
        + calendar_module_text()
        + "\n"
        + strict_deps_text()
        + "\n(async () => {\n"
        + body
        + "\n})().catch((error) => { console.error(error); process.exit(1); });"
    )
    result = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=30
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])
