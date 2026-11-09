"""Pin the chat.padiem.net custom-domain ownership after the 2026-11-09 accident.

The 2026-11-08 cutover moved the public hostname ``chat.padiem.net`` from the
Python Worker (``padiem-chat``) to the front proxy (``padiem-chat-front``). On
2026-11-09 a routine ``padiem-chat`` deploy silently re-claimed the hostname
because this app's ``wrangler.toml`` still declared it as a ``custom_domain``
route: for ~16 minutes the public surface served the Python Worker fallback
(``runtime: mock``, D1-backed reads) instead of the COM2 canonical host.

The rule this test pins: the public hostname may be declared as a route in
``apps/padiem-chat-front/wrangler.toml`` ONLY, and must never be declared in
``apps/padiem-chat/wrangler.toml``. Deploying either worker then keeps the
domain where the cutover put it.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CHAT_TOML = ROOT / "apps" / "padiem-chat" / "wrangler.toml"
FRONT_TOML = ROOT / "apps" / "padiem-chat-front" / "wrangler.toml"

_PUBLIC_HOST = "chat.padiem.net"
_PATTERN_RE = re.compile(r'^\s*pattern\s*=\s*"([^"]+)"\s*$')
_CUSTOM_DOMAIN_RE = re.compile(r"^\s*custom_domain\s*=\s*true\s*$")
# The front declares its single route inline:
#   routes = [{ pattern = "chat.padiem.net", custom_domain = true }]
_INLINE_ROUTES_RE = re.compile(r'^\s*routes\s*=\s*\[', re.MULTILINE)
_INLINE_PATTERN_RE = re.compile(r'"pattern"\s*:\s*"([^"]+)"|pattern\s*=\s*"([^"]+)"')
_INLINE_CUSTOM_RE = re.compile(r'"custom_domain"\s*:\s*true|custom_domain\s*=\s*true')


def _route_blocks(text: str) -> list[dict[str, object]]:
    """Collect route declarations from both TOML spellings.

    Handles the array-of-tables form (``[[routes]]`` blocks) and the inline
    array form (``routes = [{ pattern = "...", custom_domain = true }]``).
    """

    blocks: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[[") and line.endswith("]]"):
            current = {"section": line[2:-2].strip()}
            blocks.append(current)
            continue
        if current is None or current.get("section") != "routes":
            continue
        match = _PATTERN_RE.match(line)
        if match is not None:
            current["pattern"] = match.group(1)
            continue
        if _CUSTOM_DOMAIN_RE.match(line) is not None:
            current["custom_domain"] = True
    for inline in _INLINE_ROUTES_RE.finditer(text):
        # Take the statement up to the closing bracket of this array.
        tail = text[inline.end():]
        closing = tail.find("]")
        statement = tail[: closing + 1] if closing >= 0 else tail
        statement = statement.split("#", 1)[0]
        block: dict[str, object] = {"section": "routes-inline"}
        pattern = _INLINE_PATTERN_RE.search(statement)
        if pattern is not None:
            block["pattern"] = pattern.group(1) or pattern.group(2)
        if _INLINE_CUSTOM_RE.search(statement) is not None:
            block["custom_domain"] = True
        blocks.append(block)
    return blocks


def _declared_host_routes(text: str, host: str) -> list[dict[str, object]]:
    return [
        block
        for block in _route_blocks(text)
        if block.get("pattern") == host
    ]


def test_padiem_chat_declares_no_public_hostname_route() -> None:
    """The Python Worker must never re-claim chat.padiem.net on deploy."""

    text = CHAT_TOML.read_text(encoding="utf-8")
    routes = _declared_host_routes(text, _PUBLIC_HOST)
    assert routes == [], (
        "apps/padiem-chat/wrangler.toml must not declare a chat.padiem.net "
        "route: the 2026-11-08 cutover moved the public hostname to "
        "padiem-chat-front, and a custom_domain route here makes every "
        "padiem-chat deploy steal it back (the 2026-11-09 accident)."
    )


def test_padiem_chat_declares_no_custom_domain_at_all() -> None:
    """No custom_domain route may exist anywhere in the Python Worker config."""

    text = CHAT_TOML.read_text(encoding="utf-8")
    for block in _route_blocks(text):
        assert "custom_domain" not in block, (
            "apps/padiem-chat/wrangler.toml declares a custom_domain route; "
            "the Python Worker has no public hostname since the 2026-11-08 "
            "cutover."
        )


def test_padiem_chat_front_pins_the_public_hostname() -> None:
    """The front proxy is the only owner of the public hostname route."""

    text = FRONT_TOML.read_text(encoding="utf-8")
    routes = _declared_host_routes(text, _PUBLIC_HOST)
    assert len(routes) == 1, (
        "apps/padiem-chat-front/wrangler.toml must declare exactly one "
        "chat.padiem.net route so every front deploy re-pins the hostname "
        "the 2026-11-08 cutover moved here."
    )
    assert routes[0].get("custom_domain") is True
