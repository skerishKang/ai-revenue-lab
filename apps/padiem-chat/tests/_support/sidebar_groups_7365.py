"""#8060: raw reads and parsed facts for the #7365 sidebar-groups contracts.

The shipped static files are opened here, never in the contract test. Each
helper returns parsed ids, attribute values, positions, counts or copy values,
so a test asserts computed facts instead of raw source text. Helper bodies are
verbatim moves of the slices the test used to make inline.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import locale_bundle

from _r5_function_source import function_body

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "static"

_ID = re.compile(r'id="([^"]+)"')
_CLASS = re.compile(r'class="([^"]+)"')
_LOCALE_ATTR = re.compile(r'data-locale-[a-z-]+="([^"]+)"')


@lru_cache(maxsize=1)
def index_html() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def app_js() -> str:
    return (STATIC / "app.js").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def util_app() -> str:
    return (STATIC / "util-app.js").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def history_module() -> str:
    return (STATIC / "chat-history-module.js").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def connectors_module() -> str:
    return (STATIC / "chat-connectors-module.js").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def history_css() -> str:
    return (STATIC / "history.css").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def locale_value(key: str, lang: str) -> str:
    return locale_bundle.keys(lang).get(key, "")


def ids(source: str) -> list[str]:
    return _ID.findall(source)


def classes(source: str) -> list[str]:
    return _CLASS.findall(source)


def _positions(source: str, markers: tuple[str, ...]) -> dict[str, int]:
    return {marker: source.index(marker) for marker in markers}


def _named_positions(source: str, markers: tuple[str, ...]) -> dict[str, int]:
    found = _positions(source, markers)
    return {marker.strip('"').split('="')[-1]: pos for marker, pos in found.items()}


def _sidebar() -> str:
    html = index_html()
    return html.split('<aside class="sidebar"', 1)[1].split("</aside>", 1)[0]


def _bottom() -> str:
    sidebar = _sidebar()
    tools = sidebar.split('class="sidebar-bottom-tools"', 1)[1].split('class="sidebar-bottom"', 1)[0]
    pinned = sidebar.split('class="sidebar-bottom"', 1)[1]
    return tools + pinned


def _menu() -> str:
    return _bottom().split('id="profileMenu"', 1)[1].split("</div>", 1)[0]


def chat_group_ids() -> list[str]:
    group = _sidebar().split('class="sidebar-chat-claw-group"', 1)[1].split('id="workspaceNav"', 1)[0]
    return ids(group)


def tool_nav_ids() -> list[str]:
    nav = _sidebar().split('id="workspaceNav"', 1)[1].split("</nav>", 1)[0]
    return ids(nav)


def tool_nav_positions() -> dict[str, int]:
    nav = _sidebar().split('id="workspaceNav"', 1)[1].split("</nav>", 1)[0]
    keys = ("utilNavButton", "calendarNavButton", "automationNavButton", "filesNavButton")
    return _positions(nav, tuple('id="%s"' % key for key in keys))


def sidebar_section_positions() -> dict[str, int]:
    return _named_positions(_sidebar(), ('id="projectsSection"', 'id="historySection"'))


def bottom_positions() -> dict[str, int]:
    markers = (
        'id="newsButton"', 'id="feedbackButton"', 'id="helpNavLink"',
        'class="sidebar-account account-controls"', 'id="profileMenu"',
        'class="sidebar-legal"',
    )
    return _named_positions(_bottom(), markers)


def bottom_ids() -> list[str]:
    return ids(_bottom())


def bottom_classes() -> list[str]:
    return classes(_bottom())


def menu_positions() -> dict[str, int]:
    return _named_positions(_menu(), ('id="settingsButton"', 'id="connectorsNavButton"', 'class="home-link"'))


def menu_classes() -> list[str]:
    return classes(_menu())


def menu_locale_keys() -> list[str]:
    return _LOCALE_ATTR.findall(_menu())


def util_button_glyphs() -> list[str]:
    button = index_html().split('id="utilNavButton"', 1)[1].split("</button>", 1)[0]
    return re.findall(r'<span class="side-icon"[^>]*>([^<]*)</span>', button)


def settings_button_hidden() -> bool:
    menu = _bottom().split('id="profileMenu"', 1)[1]
    marker = 'id="settingsButton"'
    start = menu.rindex("<button", 0, menu.index(marker))
    return " hidden" in menu[start:menu.index(marker)]


def clear_project_assignments() -> list[str]:
    block = function_body("clearProjectsUI", end="\n      }")
    return re.findall(r"\w+\.hidden\s*=\s*[^;]+;", block)


def tools_menu_binding() -> dict:
    tag = re.search(r'<[^>]*data-locale-aria-label="tools-menu"[^>]*>', index_html()).group(0)
    aria = re.search(r'(?<![\w-])aria-label="([^"]+)"', tag).group(1)
    triples = re.findall(r'\["([^"]+)",\s*"([^"]+)",\s*"([^"]+)"\]', locale_source())
    triple = next((list(item) for item in triples if item[2] == "tools-menu"), [])
    return {
        "aria_label": aria,
        "ko": locale_value("tools-menu", "ko"),
        "en": locale_value("tools-menu", "en"),
        "aria_binding": triple,
    }


def meeting_trigger() -> dict:
    html = index_html()
    host = html.split('id="meetingCaptureHost"', 1)[1].split("</div>", 1)[0]
    return {
        "id_count": html.count('id="meetingNavButton"'),
        "host_hidden": 'id="meetingCaptureHost" hidden' in html,
        "host_after_util": html.index('id="meetingCaptureHost"') > html.index('id="utilAppRoot"'),
        "entry_classes": classes(host),
        "aria_controls": re.search(r'aria-controls="([^"]+)"', host).group(1),
        "locale_keys": _LOCALE_ATTR.findall(host),
    }


def meeting_park_facts() -> dict:
    util = util_app()
    return {
        "looked_up_ids": re.findall(r'getElementById\("([^"]+)"\)', util),
        "dispatched_ids": re.findall(r'parsed\.id\s*===\s*"([^"]+)"', util),
        "park_calls": util.count("parkMeetingCaptureEntry();"),
    }


def moved_bottom_facts() -> dict:
    href = re.search(r'id="helpNavLink"\s+href="([^"]+)"', index_html())
    return {
        "connector_listener": 'connectorsNavButton.addEventListener("click", openConnectorsView);' in connectors_module(),
        "wire_calls": app_js().count("connectorsModule().wireConnectorsListeners();"),
        "help_href": href.group(1) if href else "",
    }


def hash_facts() -> dict:
    app = app_js()
    return {
        "hash_assignments": re.findall(r'window\.location\.hash\s*=\s*"([^"]+)"', app),
        "padiem_meeting_literal": '"#padiem-meeting"' in app,
        "meeting_route_hash_count": app.count("MEETING_ROUTE_HASH"),
        "connectors_dispatch": "window.location.hash === CONNECTORS_ROUTE_HASH) connectors.openConnectorsView();" in app,
    }


def util_script_facts() -> list[tuple[str, bool]]:
    return [
        (src, "defer" in tail)
        for src, tail in re.findall(r'<script\s+src="([^"]+)"([^>]*)>', index_html())
    ]


def history_group_facts() -> dict:
    history = history_module()
    literal = re.search(r'const TOOL_REQUEST_PREFIX\s*=\s*"([^"]+)"', history).group(1)
    empty = re.findall(r"deps\.historyEmpty\.hidden\s*=\s*([^;]+);", history)
    return {
        "tool_request_prefix": literal.encode("utf-8").decode("unicode_escape"),
        "details_created": history.count('document.createElement("details")'),
        "has_summary": "history-tool-requests-summary" in history,
        "ui_t_keys": re.findall(r'uiT\("([^"]+)"\)', history),
        "history_empty_condition": empty[-1] if empty else "",
        "copy_ko": locale_value("history-tool-request-group", "ko"),
        "copy_en": locale_value("history-tool-request-group", "en"),
    }


def history_css_selectors() -> set[str]:
    return set(re.findall(r"[.#][A-Za-z0-9_-]+", history_css()))


__all__ = [
    "STATIC", "index_html", "app_js", "util_app", "history_module",
    "connectors_module", "history_css", "locale_source", "locale_value",
    "chat_group_ids", "tool_nav_ids", "tool_nav_positions",
    "sidebar_section_positions", "bottom_positions", "bottom_ids",
    "bottom_classes", "menu_positions", "menu_classes", "menu_locale_keys",
    "util_button_glyphs", "settings_button_hidden", "clear_project_assignments",
    "tools_menu_binding", "meeting_trigger", "meeting_park_facts",
    "moved_bottom_facts", "hash_facts", "util_script_facts",
    "history_group_facts", "history_css_selectors",
]
