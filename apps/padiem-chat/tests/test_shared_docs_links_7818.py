"""#7818: chat.padiem.net/privacy and /terms link the shared PADIEM account
documents (auth.padiem.net/privacy, /terms). The full Chat sections keep
living here (see test_privacy_terms_pages_6659.py); this file only pins the
reciprocal links both ways.
"""

from __future__ import annotations

# #8060: shipped reads live in _support; assertions stay here.
from _support.locale_source import consent_html, council_app_js, index_html, locale_js, pc_ready_js, privacy_html, read, terms_html

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"

PRIVACY = privacy_html()
TERMS = terms_html()


def test_chat_pages_link_the_shared_documents():
    for page in (PRIVACY, TERMS):
        assert 'href="https://auth.padiem.net/privacy"' in page
        assert 'href="https://auth.padiem.net/terms"' in page


def test_chat_pages_keep_their_content_next_to_the_links():
    # The links are an addition: the verified Chat sections stay intact.
    assert "padiem_session" in PRIVACY and "drive.readonly" in PRIVACY
    assert "준거법" in TERMS
