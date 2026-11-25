#!/usr/bin/env python3
"""Assemble one page from the shared partials and its body fragment.

The source pages keep only their body. Page values (title, description, canonical,
og metadata, active tab and the small per-page footer/header/script variants) live
in partials/pages.json. No content is rendered here: build-dist runs prerender.inject
on the assembled HTML afterwards.
"""
from __future__ import annotations

import json
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
PARTIALS = APP_ROOT / "partials"
PAGES = json.loads((PARTIALS / "pages.json").read_text(encoding="utf-8"))
SHELL = {
    key: (PARTIALS / f"{key}.html").read_text(encoding="utf-8")
    for key in ("head", "header", "footer", "tabbar")
}
NAV = ("index", "about", "activity", "policy", "media")


def _fill(template: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    assert "{{" not in template, "unfilled partial placeholder"
    return template


def render(page: str) -> str:
    """Return the full source HTML for one page, without prerendered records."""
    meta = PAGES[page]
    values = {
        "TITLE": meta["title"],
        "DESCRIPTION": meta["description"],
        "CANONICAL": meta["canonical"],
        "ROBOTS": meta["robots"],
        "OG_TITLE": meta["ogTitle"],
        "OG_DESCRIPTION": meta["ogDescription"],
        "OG_URL": meta["ogUrl"],
        "THEME_SCRIPT": meta["themeScript"],
        "BOLD_PRELOAD": meta["boldPreload"],
        "SUBSET_PRELOADS": meta["subsetPreloads"],
        "TOP_ACTIONS": PAGES["_actions"][page],
        "FOOTER_TAIL": PAGES["_footerTails"][page],
    }
    active = {f"ACTIVE_{name.upper()}": ' class="active"' if page == f"{name}.html" else ""
              for name in NAV}
    values.update(active)
    fragment = (APP_ROOT / page).read_text(encoding="utf-8")
    body, tail = fragment.split("<!-- @tail -->\n", 1)
    scripts = PAGES["_scripts"][page]
    return (
        '<!doctype html>\n<html lang="ko" data-theme="light">\n'
        + _fill(SHELL["head"], values)
        + '\n<body>\n  <a class="skip-link" href="#main">본문으로 건너뛰기</a>'
        + PAGES["_headerLead"][page]
        + _fill(SHELL["header"], values)
        + body
        + _fill(SHELL["footer"], values)
        + PAGES["_tabLead"][page] + _fill(SHELL["tabbar"], values)
        + tail
        + scripts
        + "</body>\n</html>\n"
    )
