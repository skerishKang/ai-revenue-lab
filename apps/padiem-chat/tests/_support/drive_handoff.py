"""Parsed views for the Google Drive connect-handoff contracts (#8060 30차).

Keeps the raw ``read_text`` calls out of the contract tests: the tests receive
the shipped markup parsed into attribute maps and the reviewed Control Plane
constants parsed out of their module-level assignments. The sheet paths stay
here.
"""
from __future__ import annotations

import re
from pathlib import Path

_CHAT = Path(__file__).resolve().parents[2]
_REPO = _CHAT.parents[1]


def index_html() -> str:
    return (_CHAT / "static/index.html").read_text(encoding="utf-8")


def app_js_text() -> str:
    return (_CHAT / "static/app.js").read_text(encoding="utf-8")


def connectors_module_text() -> str:
    return (_CHAT / "static/chat-connectors-module.js").read_text(encoding="utf-8")


def ticket_routes_text() -> str:
    return (_CHAT / "app/connector_ticket_routes.py").read_text(encoding="utf-8")


def durable_store_text() -> str:
    return (_REPO / "packages/padiem-control-plane/google_oauth_durable_store.py").read_text(encoding="utf-8")


def ingress_runtime_text() -> str:
    return (_REPO / "packages/padiem-control-plane/google_oauth_ingress_runtime.py").read_text(encoding="utf-8")


def drive_card() -> str:
    """The shipped google-drive capability card element."""
    match = re.search(
        r'<div class="capability-card" data-connector="google-drive".*?</div>',
        index_html(), re.DOTALL,
    )
    assert match, "the google-drive capability card is missing"
    return match.group(0)


def drive_card_attrs() -> dict[str, str]:
    """The Drive card's own attribute map (absent attribute → "")."""
    match = re.search(r'<div class="capability-card" data-connector="google-drive"([^>]*)>', drive_card())
    assert match
    attributes: dict[str, str] = {}
    for name, value in re.findall(r'([A-Za-z-]+)(?:="([^"]*)")?', match.group(1)):
        attributes[name] = value if value is not None else ""
    return attributes


def drive_connect_button_attrs() -> dict[str, str]:
    """The reviewed Drive connect button's attribute map (absent attr → "")."""
    button = re.search(r'<button([^>]*)>', drive_card())
    assert button, "the drive connect button is missing"
    attributes: dict[str, str] = {}
    for name, value in re.findall(r'([A-Za-z-]+)(?:="([^"]*)")?', button.group(1)):
        attributes[name] = value if value is not None else ""
    return attributes


def drive_card_connect_action_count() -> int:
    """How many connect actions the whole Drive card markup declares."""
    return drive_card().count("data-google-connector-connect")


def ticket_connect_url() -> str:
    """The reviewed Control Plane connect URL, parsed from its assignment."""
    match = re.search(r'GOOGLE_OAUTH_CONNECT_URL = "([^"]+)"', ticket_routes_text())
    assert match, "GOOGLE_OAUTH_CONNECT_URL assignment missing"
    return match.group(1)


def reviewed_oauth_start_connectors() -> set[str]:
    """The reviewed OAuth-start connector allowlist, parsed from the frozenset."""
    match = re.search(r"_OAUTH_START_REVIEWED_CONNECTORS = frozenset\(\{([^}]*)\}\)", ticket_routes_text())
    assert match, "the reviewed connector frozenset is missing"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def durable_scope_constant(name: str) -> str:
    """One scope constant's URL, parsed from the durable store assignment."""
    match = re.search(rf'{name} = "([^"]+)"', durable_store_text())
    assert match, f"{name} assignment missing"
    return match.group(1)


def ingress_scope_constants() -> dict[str, tuple[str, ...]]:
    """The ingress scope map parsed into connector → scope-constant names."""
    text = ingress_runtime_text()
    mapping: dict[str, tuple[str, ...]] = {}
    for connector, constants in re.findall(r'"([a-z\-]+)": \(([A-Z_,\s]+?)\),', text):
        names = tuple(name.strip() for name in constants.split(",") if name.strip())
        mapping[connector] = names
    return mapping
