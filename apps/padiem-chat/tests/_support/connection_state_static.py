"""#8060 — shipped connection-state assets, read once here for parsed facts."""
from __future__ import annotations

from pathlib import Path

from _support.html_tags import tags_for_page
from css_rules import rules_for_sheet

STATIC = Path(__file__).resolve().parents[2] / "static"


def text(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def state_js() -> str:
    return text("claw-connection-state.js")


def composer_js() -> str:
    return text("claw-composer-connection-status.js")


def home_js() -> str:
    return text("claw-home-choices.js")


def device_manager_js() -> str:
    return text("claw-device-manager.js")


def connector_management_js() -> str:
    return text("claw-connector-management.js")


def script_sources() -> list[str]:
    return [attrs["src"] for tag, attrs in tags_for_page("index.html")
            if tag == "script" and attrs.get("src")]


def selectors(sheet: str) -> set[str]:
    return {selector for rule in rules_for_sheet(sheet) for selector in rule.selectors}


def declaration_values(sheet: str) -> set[str]:
    return {value for rule in rules_for_sheet(sheet)
            for value in rule.declarations.values()}
