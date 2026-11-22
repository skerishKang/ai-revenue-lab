"""#8060 parsed facts for locale URL authority and dynamic copy.

Raw reads of the locale bundle and static modules stay here; the contract
asserts parsed URL/projection expressions, parsed locale pairs and tokens.
"""
from __future__ import annotations

import re
from pathlib import Path

import locale_bundle

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "static"

URL_AUTHORITY = (
    'searchParams.get("lang")', 'searchParams.set("lang", lang)',
    "history.replaceState", 'window.addEventListener("popstate"',
    'apply(getUrlLocale() || "ko", false)',
)
URL_FORBIDDEN = ('apply("ko")', "localStorage", "sessionStorage", "document.cookie")
PROJECTION = ('document.documentElement.lang = locale', "padiem:localechange")
PROJECTION_FORBIDDEN = ("conversationState.reset", "location.reload", "window.location.assign")
GLASS_TOKENS = (
    'data-theme-value="padiem-glass"',
    'data-glass-variant-value="female"',
    'data-glass-variant-value="male"',
)
REQUIRED_LOCALE_PAIRS = (
    ("glass-a", "배경 A"), ("glass-a", "Background A"),
    ("glass-b", "배경 B"), ("glass-b", "Background B"),
    ("main-menu", "Main menu"), ("settings-close", "Close settings"),
    ("attachment-remove", "Remove attachment"), ("send", "Send message"),
    ("export-aria", "Export the current conversation as a text file"),
    ("project-delete", "Delete project"), ("manage", "Manage"), ("retry", "Try again"),
    ("timeout", "Response timed out"), ("connection-error", "Connection error"),
    ("answer-actions", "Answer actions"), ("csv-download", "Download CSV"),
    ("sources", "Sources"), ("export", "Export conversation"),
)
CAPABILITY_LABELS = (
    "JPEG", "PNG", "WebP", "TXT", "Markdown", "CSV", "JSON", "PDF", "DOCX", "PPTX", "XLSX",
)
ATTACHMENT_COPY = ("attachmentCapabilities.copy(lang)", "attachmentCapabilities.accept")
AUTH_FLAGS = (
    'button.dataset.authenticated = "true"',
    'button.dataset.authenticated = "false"',
)
LOCALE_SWITCH = ("persistLocale(locale)", "button.dataset.localeValue")
SWITCH_FORBIDDEN = ("selectedAttachment", "conversationEpoch", "activeProject =")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _present(tokens, source: str) -> tuple[str, ...]:
    return tuple(token for token in tokens if token in source)


def facts() -> dict:
    locale = locale_bundle.SOURCE.read_text(encoding="utf-8")
    outputs = _read(STATIC / "outputs.js")
    theme = _read(STATIC / "theme.js")
    capabilities = _read(STATIC / "attachment-capabilities.js")
    return {
        "url_authority": _present(URL_AUTHORITY, locale),
        "url_forbidden": _present(URL_FORBIDDEN, locale),
        "projection": _present(PROJECTION, locale),
        "projection_forbidden": _present(PROJECTION_FORBIDDEN, locale),
        "glass_tokens": _present(GLASS_TOKENS, locale),
        "glass_variants": tuple(re.findall(r"const GLASS_VARIANTS=\[([^\]]+)\]", theme)),
        "locale_pairs": set(re.findall(r'"([a-z0-9-]+)":\s*"([^"]*)"', locale)),
        "attachment_copy": _present(ATTACHMENT_COPY, locale),
        "capability_labels": tuple(sorted(set(re.findall(r'label: "([A-Za-z]+)"', capabilities)))),
        "auth_flags": _present(AUTH_FLAGS, locale),
        "outputs_auth": 'loginButton.dataset.authenticated === "true"' in outputs,
        "outputs_korean_button": 'textContent.trim() === "로그아웃"' in outputs,
        "locale_switch": _present(LOCALE_SWITCH, locale),
        "switch_forbidden": _present(SWITCH_FORBIDDEN, locale),
    }
