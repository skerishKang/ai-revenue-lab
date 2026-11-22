"""Parse shipped HTML into ordered tags and attribute maps for UI contracts."""
from html.parser import HTMLParser
from pathlib import Path


class _Tags(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)


def tags_for_page(name):
    static = Path(__file__).resolve().parents[2] / "static"
    parser = _Tags()
    parser.feed((static / name).read_text(encoding="utf-8"))
    parser.close()
    return parser.tags
