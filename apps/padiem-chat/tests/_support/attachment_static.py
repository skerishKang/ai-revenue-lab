"""#8060 — shipped attachment assets, read once here for parsed contracts."""
from __future__ import annotations

from pathlib import Path

from _support.html_tags import tags_for_page

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "static"
REPO = ROOT.parents[1]


def text(name: str) -> str:
    path = REPO / name if name.startswith("apps/") else STATIC / name
    return path.read_text(encoding="utf-8")


def app_source() -> str:
    return text("app.js") + "\n" + text("chat-claw-run-module.js")


def capabilities_source() -> str:
    return text("attachment-capabilities.js")


def core_module_source() -> str:
    return text("chat-core-module.js")


def licenses_page_source() -> str:
    return text("third-party-licenses.html")


def renderer_notice_source() -> str:
    return text("apps/b66-pdf-renderer/THIRD_PARTY_LICENSES.md")


def index_tags() -> list[tuple[str, dict[str, str | None]]]:
    return tags_for_page("index.html")


def page_text(page: str = "index.html") -> str:
    from html.parser import HTMLParser

    class _Text(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.parts: list[str] = []

        def handle_data(self, data):
            self.parts.append(data)

    parser = _Text()
    path = STATIC / page
    parser.feed(path.read_text(encoding="utf-8"))
    return "\n".join(parser.parts)


def has_script(src: str) -> bool:
    return any(tag == "script" and attrs.get("src") == src
               for tag, attrs in index_tags())


def has_stylesheet(href: str) -> bool:
    return any(tag == "link" and attrs.get("rel") == "stylesheet"
               and attrs.get("href") == href for tag, attrs in index_tags())


def has_link(href: str) -> bool:
    return any(tag == "a" and attrs.get("href") == href
               for tag, attrs in index_tags())


def has_element_id(id_value: str) -> bool:
    return any(attrs.get("id") == id_value for _tag, attrs in index_tags())


def renderer_links() -> list[str]:
    return [attrs["href"] for tag, attrs in tags_for_page("third-party-licenses.html")
            if tag == "a" and attrs.get("href")]
