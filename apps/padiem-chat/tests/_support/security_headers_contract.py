"""#8060 parsed facts for the security-header contract's static sources.

Raw reads stay here; the header contract asserts parsed markup and parsed
front-worker header names instead of pinning source spelling.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.worker_config import CONTENT_SECURITY_POLICY, PERMISSIONS_POLICY

CHAT_ROOT = Path(__file__).resolve().parents[2]
FRONT_WORKER = CHAT_ROOT.parent / "padiem-chat-front" / "worker.mjs"

FRONT_HEADER_TOKENS = (
    '"content-security-policy-report-only"',
    '"content-security-policy": FRAME_ANCESTORS_CSP',
    '"x-frame-options": "DENY"',
    '"x-content-type-options": "nosniff"',
    '"referrer-policy": "strict-origin-when-cross-origin"',
)


def markup_facts() -> dict:
    html = (CHAT_ROOT / "static" / "index.html").read_text(encoding="utf-8")
    script_tags = re.findall(r"<script\b([^>]*)>", html, flags=re.IGNORECASE)
    link_tags = re.findall(r"<link\b([^>]*)>", html, flags=re.IGNORECASE)
    return {
        "script_count": len(script_tags),
        "all_scripts_external": all(re.search(r"\bsrc\s*=", attrs, re.IGNORECASE)
                                    for attrs in script_tags),
        "stylesheet_links": tuple(attrs for attrs in link_tags
                                  if re.search(r'rel="stylesheet"', attrs, re.IGNORECASE)),
        "styles_css_linked": any('rel="stylesheet" href="./styles.css"' in attrs
                                 for attrs in link_tags),
        "inline_handlers": bool(re.search(r"\son[a-z]+\s*=", html, re.IGNORECASE)),
    }


def front_worker_facts() -> dict:
    source = FRONT_WORKER.read_text(encoding="utf-8")
    return {
        "present": tuple(token for token in FRONT_HEADER_TOKENS if token in source),
        "reviewed_policies": (CONTENT_SECURITY_POLICY in source,
                              PERMISSIONS_POLICY in source),
    }
