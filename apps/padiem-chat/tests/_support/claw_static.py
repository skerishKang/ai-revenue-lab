"""Read shipped static sheets for Claw UI contracts (#8060).

Keeps raw ``read_text`` out of test modules: the contract files receive the
text and assert on parsed rule/attribute values. The sheet paths stay here.
"""
from __future__ import annotations

from pathlib import Path

import locale_bundle

_STATIC = Path(__file__).resolve().parents[2] / "static"


def sheet(name: str) -> str:
    """One shipped static sheet as text (paths are fixed here, not in tests)."""
    return (_STATIC / name).read_text(encoding="utf-8")


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def source_of(path: str) -> str:
    """A test module's own source for its no-fixed-path self-check."""
    return Path(path).read_text(encoding="utf-8")


def index_element_attrs(element_id):
    from _support.html_tags import tags_for_page

    for _tag, attrs in tags_for_page("index.html"):
        if attrs.get("id") == element_id:
            return attrs
    return None


def index_locale_keys():
    from _support.html_tags import tags_for_page

    return {attrs["data-locale-key"] for _tag, attrs in tags_for_page("index.html")
            if attrs.get("data-locale-key")}


def js_statement(sheet_name, statement):
    text = " ".join(sheet(sheet_name).split())
    return " ".join(statement.split()) in text


def css_declaration(sheet_name, selector, prop):
    from css_rules import declaration, find_rules_with_selector, rules_for_sheet

    matches = find_rules_with_selector(rules_for_sheet(sheet_name), selector)
    return [declaration(rule, prop) for rule in matches]


def locale_value(key, lang):
    return locale_bundle.keys(lang).get(key)


def server_source(module_name):
    app_dir = Path(__file__).resolve().parents[2] / "app"
    return (app_dir / (module_name + ".py")).read_text(encoding="utf-8")


def server_function_body(module_name, start_marker, end_marker):
    source = server_source(module_name)
    return source.split(start_marker, 1)[1].split(end_marker, 1)[0]


def migration_source(name):
    migrations = Path(__file__).resolve().parents[4] / "apps/padiem-chat/migrations"
    return (migrations / name).read_text(encoding="utf-8")
