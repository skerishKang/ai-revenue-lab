"""#7818: chat.padiem.net/privacy and /terms link the shared PADIEM account
documents (auth.padiem.net/privacy, /terms). The full Chat sections keep
living here (see test_privacy_terms_pages_6659.py); this file only pins the
reciprocal links both ways.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"

PRIVACY = (STATIC / "privacy.html").read_text(encoding="utf-8")
TERMS = (STATIC / "terms.html").read_text(encoding="utf-8")


def test_chat_pages_link_the_shared_documents():
    for page in (PRIVACY, TERMS):
        assert 'href="https://auth.padiem.net/privacy"' in page
        assert 'href="https://auth.padiem.net/terms"' in page


def test_chat_pages_keep_their_content_next_to_the_links():
    # The links are an addition: the verified Chat sections stay intact.
    assert "padiem_session" in PRIVACY and "drive.readonly" in PRIVACY
    assert "준거법" in TERMS
