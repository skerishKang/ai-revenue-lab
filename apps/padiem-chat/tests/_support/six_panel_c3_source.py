"""Parsed CSS sources and mutation specimens for the C3 six-panel contract."""
from css_rules import parse_rules
from _support.claw_static import sheet


def frame_rules():
    return parse_rules(sheet("shared-six-panel-frame.css"))


def tampered_token_sheet(mutation: str) -> str:
    source = sheet("padiem-tokens.css")
    name = "--shared-six-panel-frame-narrow-bg:"
    assert source.count(name) == 1
    if mutation == "delete":
        return source.replace(name, "", 1)
    if mutation == "rename":
        return source.replace(name, "--shared-six-panel-frame-narrow-bg-typo:", 1)
    raise ValueError(mutation)
