"""Parsed views of the Claw result-action contracts (#8060).

Raw reads live here. Tests receive parsed HTML attributes, locale copy,
JS call counts and registered route paths. The shared ``claw_static`` helper
is untouched.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import locale_bundle

import _r5_function_source as r5
from _support.html_tags import tags_for_page

_TESTS = Path(__file__).resolve().parents[1]
_STATIC = _TESTS.parent / "static"
_APP = _TESTS.parent / "app"
_LOCALE = locale_bundle.SOURCE

_CARD_MARKER = '<article class="claw-result-card" id="clawResultCard" hidden>'
_ACTIONS_MARKER = '<div class="claw-result-actions">'
_LOCALE_KEY_RX = re.compile(r'"([A-Za-z0-9_\-]+)":\s*"((?:[^"\\]|\\.)*)"')
_CLAW_ROUTE_RX = re.compile(r'Route\("(/api/claw[^"]*)"')
_ARTIFACT_PATH = "/api/claw/manual-intake/artifact/{document_id}"


class _Tags(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict[str, str]]] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)


def app_js_path() -> Path:
    return _STATIC / "app.js"


def index_html_path() -> Path:
    return _STATIC / "index.html"


def _sheet(sheet: str) -> str:
    return (_STATIC / sheet).read_text(encoding="utf-8")


def _locale_source() -> str:
    return _LOCALE.read_text(encoding="utf-8")


def _block(marker: str, closing: str) -> str:
    index = _sheet("index.html")
    if marker not in index:
        raise LookupError(f"index.html 의 {marker!r} 표식을 찾지 못했다")
    return index.split(marker, 1)[1].split(closing, 1)[0]


def card_block() -> str:
    return _block(_CARD_MARKER, "</article>")


def actions_block() -> str:
    return _block(_ACTIONS_MARKER, "</div>")


def _attrs(text: str) -> list[dict[str, str]]:
    parser = _Tags()
    parser.feed(text)
    parser.close()
    return [attrs for _tag, attrs in parser.tags]


def action_button_attrs() -> list[dict[str, str]]:
    parser = _Tags()
    parser.feed(actions_block())
    parser.close()
    return [attrs for tag, attrs in parser.tags if tag == "button"]


def action_locale_keys() -> list[str]:
    parser = _Tags()
    parser.feed(actions_block())
    parser.close()
    return [attrs["data-locale-key"] for _tag, attrs in parser.tags if "data-locale-key" in attrs]


def card_ids() -> set[str]:
    return {attrs["id"] for attrs in _attrs(card_block()) if "id" in attrs}


def card_locale_keys() -> set[str]:
    return {attrs["data-locale-key"] for attrs in _attrs(card_block()) if "data-locale-key" in attrs}


def card_text() -> str:
    return card_block()


def index_ids() -> set[str]:
    return {attrs["id"] for _tag, attrs in tags_for_page("index.html") if "id" in attrs}


def index_locale_keys() -> set[str]:
    return {attrs["data-locale-key"] for _tag, attrs in tags_for_page("index.html") if "data-locale-key" in attrs}


def index_fallback_copy(key: str) -> str:
    index = _sheet("index.html")
    marker = f'data-locale-key="{key}">'
    if marker not in index:
        raise LookupError(f"index.html 의 {key!r} 대체 문구를 찾지 못했다")
    return index.split(marker, 1)[1].split("</p>", 1)[0]


def locale_table() -> dict[str, dict[str, str]]:
    source = _locale_source()
    if "en: {" not in source:
        raise LookupError("locale.js 에 en: { 블록이 없다")

    def unescape(value: str) -> str:
        return value.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t").replace("\\\\", "\\")

    ko_part, en_part = source.split("en: {", 1)
    return {
        "ko": {key: unescape(value) for key, value in _LOCALE_KEY_RX.findall(ko_part)},
        "en": {key: unescape(value) for key, value in _LOCALE_KEY_RX.findall(en_part)},
    }


def sheet_count(sheet: str, needle: str) -> int:
    return _sheet(sheet).count(needle)


def sheet_has(sheet: str, needle: str) -> bool:
    return needle in _sheet(sheet)


def app_identifiers() -> set[str]:
    return set(re.findall(r"[A-Za-z_$][\w$]*", _sheet("app.js")))


def definition_count(name: str) -> int:
    return r5.definition_count(name)


def _factory_source() -> str:
    from _support.app_factory_modules import factory_area_source
    return factory_area_source()


def claw_routes() -> list[str]:
    return _CLAW_ROUTE_RX.findall(_factory_source())


def factory_count(needle: str) -> int:
    return _factory_source().count(needle)


def artifact_route_line() -> str:
    lines = [line for line in _factory_source().splitlines() if _ARTIFACT_PATH in line]
    if not lines:
        raise LookupError("아티팩트 경로 등록 줄이 없다")
    return lines[0]
