"""#8060 parsed CSS facts for Claw theme inheritance.

Raw static reads stay here; the contract asserts parsed declarations, parsed
theme blocks and token/alias presence instead of source spelling.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "static"

THEMES = ("light", "dark", "cinematic", "padiem-home", "padiem-glass")
FALLBACK_TOKENS = (
    "var(--text,", "var(--muted,", "var(--accent,", "var(--line,", "var(--card-bg,",
)
REQUIRED_TOKENS = (
    "var(--text)", "var(--muted)", "var(--line)", "var(--card-bg)",
    "var(--accent)", "var(--accent-soft)", "var(--accent-contrast)",
)
LEGACY_ALIASES = ("var(--ink", "var(--text-muted")
FORBIDDEN_COLORS = ("color: #1a6b3a;", "color: #8a1a1a;")
SURFACE_DECLARATIONS = (
    ("background", "var(--success-surface)"),
    ("border", "1px solid var(--success-border)"),
    ("background", "var(--danger-surface)"),
    ("border", "1px solid var(--danger-border)"),
)


def read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _declarations(text: str) -> frozenset[tuple[str, str]]:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return frozenset((prop.strip(), value.strip())
                     for prop, value in re.findall(r"([-a-z]+)\s*:\s*([^;{}]+);", text))


def _theme_blocks(tokens: str) -> dict[str, frozenset[tuple[str, str]]]:
    blocks = {}
    for theme in THEMES:
        match = re.search(rf'html\[data-theme="{re.escape(theme)}"\]\s*\{{(.*?)\n\}}',
                          tokens, re.DOTALL)
        if match:
            blocks[theme] = _declarations(match.group(1))
    return blocks


def facts() -> dict:
    workspace = read("claw-workspace.css")
    manual = read("claw-manual-intake.css")
    tokens = read("padiem-tokens.css")
    capability = read("capability-nav.css")
    result_blocks = {}
    for selector in (".claw-result-note", ".claw-result-empty"):
        match = re.search(rf"(?m)^{re.escape(selector)}\s*\{{(.*?)\n\}}", workspace, re.DOTALL)
        if match:
            result_blocks[selector] = _declarations(match.group(1))
    hint = re.search(r"\.claw-result-hint,\s*\n\.claw-execute-hint\s*\{(.*?)\n\}", workspace, re.DOTALL)
    return {
        "fallback_tokens": tuple(token for token in FALLBACK_TOKENS
                                 if token in workspace or token in manual),
        "required_tokens": tuple(token for token in REQUIRED_TOKENS if token in workspace),
        "glass_rules": re.findall(
            r'html\[data-theme="padiem-glass"\][^{]*\.claw[^{]*\{', workspace),
        "theme_blocks": _theme_blocks(tokens),
        "legacy_aliases": tuple(alias for alias in LEGACY_ALIASES
                                if alias in workspace or alias in manual or alias in capability),
        "forbidden_colors": tuple(color for color in FORBIDDEN_COLORS if color in workspace),
        "workspace_declarations": _declarations(workspace),
        "workspace_selectors": tuple(sel.strip() for sel in re.findall(r"([^{}]+)\{", workspace)),
        "token_declarations": _declarations(tokens),
        "success_count": tokens.count("--success:"),
        "capability_declarations": _declarations(capability),
        "result_blocks": result_blocks,
        "hint_block": _declarations(hint.group(1)) if hint else frozenset(),
    }
