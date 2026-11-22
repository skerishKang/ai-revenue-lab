"""B66 manual model-choice contract raw reads (#8060).

Raw reads live here. Tests assert on tokens parsed from the returned text.
The shared ``claw_static`` helper is untouched.
"""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[4]


def dual_ui_sources() -> list[str]:
    return [
        (_ROOT / "reference/business-66-padiem-quote-v1/padiem-account.js").read_text(
            encoding="utf-8"),
        (_ROOT / "apps/padiem-chat/static/b66-quote-runtime.js").read_text(
            encoding="utf-8"),
    ]


def quote_index_html() -> str:
    return (_ROOT / "reference/business-66-padiem-quote-v1/index.html").read_text(
        encoding="utf-8")


def quote_worker_js() -> str:
    return (_ROOT / "reference/business-66-padiem-quote-v1/_worker.js").read_text(
        encoding="utf-8")


def tier_response_sources() -> list[str]:
    return [
        (_ROOT / "apps/padiem-chat/static/b66-quote-runtime.js").read_text(
            encoding="utf-8"),
        (_ROOT / "reference/business-66-padiem-quote-v1/padiem-account.js").read_text(
            encoding="utf-8"),
    ]


def quote_routes_source() -> str:
    return (_ROOT / "apps/padiem-chat/app/b66_quote_routes.py").read_text(encoding="utf-8")
