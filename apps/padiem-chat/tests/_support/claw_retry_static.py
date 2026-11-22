"""#8060 — shipped Claw retry assets, read once here and exposed as parsed facts."""
from __future__ import annotations

from pathlib import Path

from css_rules import rules_for_sheet
from _support.html_tags import tags_for_page

STATIC = Path(__file__).resolve().parents[2] / "static"
ROOT = STATIC.parent


def text(name: str) -> str:
    path = ROOT / name if name.endswith(".py") else STATIC / name
    return path.read_text(encoding="utf-8")


def app_source() -> str:
    return text("app.js")


def run_module_source() -> str:
    return text("chat-claw-run-module.js")


def form_module_source() -> str:
    return text("chat-claw-form-module.js")


def claw_routes_source() -> str:
    return text("app/claw_routes.py")


def workspace_css() -> str:
    return text("claw-workspace.css")


def locale_source() -> str:
    from locale_bundle import SOURCE
    return SOURCE.read_text(encoding="utf-8")


def index_tags() -> list[tuple[str, dict[str, str | None]]]:
    return tags_for_page("index.html")


def element(id_value: str) -> tuple[str, dict[str, str | None]] | None:
    return next(((tag, attrs) for tag, attrs in index_tags()
                 if attrs.get("id") == id_value), None)


def workspace_rules():
    return rules_for_sheet("claw-workspace.css")


def rules_for(selector: str):
    return [rule for rule in workspace_rules() if selector in rule.selectors]


def recovery_rules():
    """Rules owned by the #2760 recovery slice, not the rest of the sheet."""
    names = (".claw-recovery-hint", ".claw-retry", ".claw-retry-copy",
             ".claw-retry-button")
    return [rule for rule in workspace_rules()
            if any(selector.startswith(names) for selector in rule.selectors)]


def locale_keys(lang: str) -> set[str]:
    import json
    import re
    source = locale_source()
    block = source.split("en: {", 1)[0 if lang == "ko" else 1]
    return set(re.findall(r'"([A-Za-z0-9_-]+)"\s*:', block))
