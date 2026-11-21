"""#8060 38차: parsed views of the theme sheets for test_padiem_themes.

The raw sheet reads live here; the contract tests receive the structure audit
tool's own parsed rules (selector → declarations), per-theme token values and
the parsed index tag order, and assert on those — never on source text inside
the test module. CSS parsing reuses the audit tool's parser, so the rule shape
is the one the structure ratchet already speaks.
"""
from __future__ import annotations

import importlib.util
from functools import lru_cache
from pathlib import Path

from _support import html_tags
from _support.claw_static import sheet

ROOT = Path(__file__).resolve().parents[4]
_TOOL = ROOT / "tools" / "chat_structure_audit.py"


def _audit():
    spec = importlib.util.spec_from_file_location("chat_structure_audit_for_themes", _TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=None)
def _parsed(sheet_name: str):
    return _audit().parse_css(sheet(sheet_name))


def rules(sheet_name: str):
    """The audit tool's parsed rules for one shipped sheet."""
    return _parsed(sheet_name)


def rules_with_selector(sheet_name: str, needle: str):
    """Parsed rules whose selector text contains ``needle`` as written."""
    return [rule for rule in rules(sheet_name) if needle in rule.selector]


def decl_map(rule) -> dict[str, str]:
    """prop → value for one parsed rule."""
    return {decl.prop: decl.value for decl in rule.decls}


def any_declaration(sheet_name: str, prop: str, value: str) -> bool:
    for rule in rules(sheet_name):
        for decl in rule.decls:
            if decl.prop == prop and decl.value == value:
                return True
    return False


def token_value(theme: str, prop: str) -> str | None:
    """The value one theme's block in padiem-tokens.css gives ``prop``."""
    selector = f'html[data-theme="{theme}"]'
    for rule in rules("padiem-tokens.css"):
        if rule.selector.strip() == selector:
            for decl in rule.decls:
                if decl.prop == prop:
                    return decl.value
    return None


def page_html() -> str:
    """index.html as text; the read lives here, not in tests."""
    return sheet("index.html")


def index_tags():
    return html_tags.tags_for_page("index.html")


def index_resources():
    """(kind, basename) for every script/link tag with a target, in document
    order — the no-flash load order the theme contracts bind."""
    out = []
    for tag, attrs in index_tags():
        if tag == "script" and attrs.get("src"):
            out.append(("script", attrs["src"].rsplit("/", 1)[-1]))
        elif tag == "link" and attrs.get("href"):
            out.append(("link", attrs["href"].rsplit("/", 1)[-1]))
    return out


def index_scripts():
    return [value for kind, value in index_resources() if kind == "script"]


def index_links():
    return [value for kind, value in index_resources() if kind == "link"]


def theme_js() -> str:
    return sheet("theme.js")


def theme_init_js() -> str:
    return sheet("theme-init.js")
