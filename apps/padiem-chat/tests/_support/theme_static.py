"""Parsed facts from the shipped theme surface for UI contracts (#8060 6차).

The raw ``read_text`` calls live here so a contract test can assert on parsed
values instead of pinning source spelling. No runtime file or route changes.
"""
from __future__ import annotations

import re
from pathlib import Path

from css_rules import declaration, find_rules_with_selector, rules_for_sheet
from _support.html_tags import tags_for_page

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "static"


def index_tags():
    return tags_for_page("index.html")


def script_srcs(tags):
    return [attrs.get("src") for _tag, attrs in tags
            if attrs.get("src") and attrs["src"].endswith(".js")]


def stylesheet_hrefs(tags):
    return [attrs.get("href") for _tag, attrs in tags
            if attrs.get("href") and attrs["href"].endswith(".css")]


def has_inline_script(tags):
    return any(tag == "script" and not attrs.get("src") for tag, attrs in tags)


def theme_js():
    return (STATIC / "theme.js").read_text(encoding="utf-8")


def theme_init_js():
    return (STATIC / "theme-init.js").read_text(encoding="utf-8")


def identifiers(source):
    """Every identifier token in a JS source (for API-presence contracts)."""
    return set(re.findall(r"[A-Za-z_$][\w$]*", source))


def array_literal(source, name):
    """The string entries of ``const/var NAME=[...]`` in a JS source."""
    match = re.search(r"(?:const|var)\s+" + re.escape(name) + r"\s*=\s*\[([^\]]*)\]", source)
    if match is None:
        return []
    return [a or b for a, b in
            re.findall(r'"([^"]+)"|\'([^\']+)\'', match.group(1))]


def theme_rules():
    return rules_for_sheet("padiem-themes.css")


def settings_rules():
    return rules_for_sheet("padiem-settings.css")


def glass_rules():
    return rules_for_sheet("padiem-glass-portrait.css")


def editorial_rules():
    return rules_for_sheet("padiem-editorial.css")


def surfaces_rules():
    return rules_for_sheet("padiem-surfaces.css")


def token_rules():
    return rules_for_sheet("padiem-tokens.css")


def selectors(rules):
    return [selector for rule in rules for selector in rule.selectors]


def declarations_for(rules, selector):
    return [rule.declarations for rule in find_rules_with_selector(rules, selector)]


def theme_token_blocks():
    """theme name -> {token name: value} from the token sheet's theme blocks."""
    blocks = {}
    for rule in token_rules():
        for selector in rule.selectors:
            match = re.fullmatch(r'html\[data-theme="([^"]+)"\]', selector.strip())
            if match:
                blocks.setdefault(match.group(1), {}).update(rule.declarations)
    return blocks


def asset_order(tags):
    """Ordered (src|href) values of script/link tags in document order."""
    out = []
    for tag, attrs in tags:
        if tag in ("script", "link"):
            value = attrs.get("src") or attrs.get("href")
            if value:
                out.append(value)
    return out


def js_constants(source):
    """identifier -> {key: value} for simple object-literal JS constants."""
    out = {}
    for match in re.finditer(r"(?:const|var)\s+(\w+)\s*=\s*\{([^}]*)\}", source):
        name, body = match.group(1), match.group(2)
        entries = {}
        for key, value in re.findall(r'([\w-]+)\s*:\s*"([^"]*)"', body):
            entries[key] = value
        out[name] = entries
    return out


def num_constants(source):
    """identifier -> int for ``const/var NAME=123`` numeric constants."""
    return {m.group(1): int(m.group(2))
            for m in re.finditer(r"(?:const|var)\s+(\w+)\s*=\s*(\d+)", source)}


def css_hex_values(declarations_list):
    """All hex colour values found in a list of declaration dicts."""
    found = []
    for decls in declarations_list:
        for value in decls.values():
            found.extend(re.findall(r"#[0-9a-fA-F]{3,8}", str(value)))
    return found


def declaration_is_important(rules, selector, prop):
    """True when the selector's declaration for prop carries !important."""
    return any(
        str(value).endswith("!important")
        for decls in declarations_for(rules, selector)
        for key, value in decls.items()
        if key.strip().lstrip("-") == prop.strip().lstrip("-")
    )


def init_fallback(source):
    """The s=<theme> fallback value in the no-URL branch of theme-init."""
    match = re.search(r'\bs\s*=\s*"([^"]+)"', source)
    return match.group(1) if match else None


def has_member(source, object_name, member):
    """True when ``object.member`` appears as a member expression."""
    return re.search(r"\b" + re.escape(object_name) + r"\s*\.\s*" + re.escape(member) + r"\b",
                     source) is not None


def css_custom_properties(source):
    """Custom property names defined or referenced in a stylesheet."""
    return set(re.findall(r"--[A-Za-z][\w-]*", source))


def media_scopes(rules):
    """All @media condition strings used by the rules."""
    return [str(rule.media) for rule in rules if getattr(rule, "media", None)]
