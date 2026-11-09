"""Public privacy policy and terms pages (#6659).

Google OAuth app verification requires a public privacy policy URL. The
service's static assets are served by the chat Worker's asset deployment and
reach anonymous visitors without any login, so the pages live next to the
existing standalone pages (``help.html``, ``third-party-licenses.html``) and
are linked from the app's sidebar footer.

The drafts describe only what the code actually collects and processes and
carry the Google Limited Use disclosure required for verification. The
owner-reserved fields (business name, representative, contact, privacy
officer, effective date, hosting processors, governing law) are filled with
the 2026-11-07 owner decision values and the tests enforce that no
``[대표 확인]`` marker remains.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"

PRIVACY = (STATIC / "privacy.html").read_text(encoding="utf-8")
TERMS = (STATIC / "terms.html").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
LEGAL_CSS = (STATIC / "legal-pages.css").read_text(encoding="utf-8")


def test_the_pages_exist_and_are_public_standalone_documents():
    for name in ("privacy.html", "terms.html", "legal-pages.css"):
        assert (STATIC / name).is_file()
    # Same standalone pattern as the existing public pages: plain HTML, Korean
    # document, no app-shell login gate around the content.
    for page in (PRIVACY, TERMS):
        assert '<html lang="ko">' in page
        assert "legal-back" in page and 'href="/"' in page


def test_the_owner_confirmed_fields_are_filled_and_no_marker_remains():
    """[대표 확인] 자리는 전부 실제 값으로 채워지고 마커는 남지 않는다."""
    for page in (PRIVACY, TERMS):
        assert "[대표 확인" not in page, "all owner-reserved markers must be resolved"
        assert "PADIEM(파디엠)" in page
        assert "2026-11-10" in page
    # Contact and privacy officer (owner decision 2026-11-07).
    assert "강혜림" in PRIVACY and "ceo@padiem.net" in PRIVACY
    assert "강혜림(대표)" in PRIVACY
    assert "ceo@padiem.net" in TERMS
    # Address and business registration number are deliberately not fields yet;
    # only the HTML comment reserves the slot for a later addition, so check
    # the rendered content with comments stripped (email-address prose may
    # still mention 주소).
    import re
    rendered = re.sub(r"<!--.*?-->", "", PRIVACY, flags=re.S)
    assert "회사 주소" not in rendered and "사업자등록번호" not in rendered
    # Governing law (owner decision 2026-11-07).
    assert "대한민국 법" in TERMS
    # Hosting processors are named; the AI processor stays unnamed by decision.
    assert "Cloudflare" in PRIVACY and "Google Cloud" in PRIVACY
    assert "AI 응답 생성을 위한 처리 위탁" in PRIVACY
    assert "기재하지 않습니다" in PRIVACY


def test_the_draft_states_only_what_the_code_does():
    # Account: email + Google sign-in.
    assert "이메일" in PRIVACY and "Google 로그인" in PRIVACY
    # Conversations stored per account, deletable.
    assert "대화 기록" in PRIVACY and "삭제" in PRIVACY
    # PC: requested actions only, re-verified.
    assert "요청한 경우에만" in PRIVACY
    # Read-only Google scopes, no write scope requested or stored.
    assert "drive.readonly" in PRIVACY and "calendar.readonly" in PRIVACY
    assert "읽기 전용" in PRIVACY
    assert "단기 접근 권한" in PRIVACY and "암호화(봉인)" in PRIVACY
    # Web push subscription stays server-side.
    assert "구독 정보" in PRIVACY and "노출되지 않" in PRIVACY
    # One session cookie; no ads/tracking.
    assert "padiem_session" in PRIVACY and "추적용 쿠키는 사용하지 않습니다" in PRIVACY
    # Delegation wording: hosting is named (Cloudflare, Google Cloud); the AI
    # answer generation processor stays unnamed ("AI 응답 생성을 위한 처리 위탁").
    assert "AI 답변 생성" in PRIVACY and "위탁" in PRIVACY
    for banned in ("Workers", "D1", "OpenAI", "Anthropic", "Agnes", "OpenRouter"):
        assert banned not in PRIVACY, banned
        assert banned not in TERMS, banned


def test_the_limited_use_disclosure_is_present_in_both_languages():
    assert "제한적 사용" in PRIVACY
    assert "Google API Services User Data Policy" in PRIVACY
    assert "Limited Use requirements" in PRIVACY
    assert "developers.google.com/terms/api-services-user-data-policy" in PRIVACY
    # The English summary carries the same disclosure.
    assert "Limited Use" in PRIVACY.split('lang="en"')[1]


def test_the_app_links_both_pages_on_the_pre_login_screen():
    """두 링크는 (대표 확정 2026-11-08) 사이드바 하단 계정 행 바로 위 한 줄이고,
    Chat/Claw 첫 화면 카드 아래에서는 사라진다. 로그인·로그아웃 모두 표시다."""
    assert 'class="sidebar-legal-links"' in INDEX
    assert 'href="./privacy.html" data-locale-key="legal-privacy">개인정보처리방침</a>' in INDEX
    assert 'href="./terms.html" data-locale-key="legal-terms">이용약관</a>' in INDEX
    # The links sit inside the sidebar bottom block, above the account row.
    sidebar_bottom = INDEX[INDEX.index('class="sidebar-bottom"'):INDEX.index("sidebar-account")]
    assert "sidebar-legal-links" in sidebar_bottom
    # The old card-area placement is gone for good.
    assert "guest-legal-links" not in INDEX
    # The accepted sidebar footer stays byte-identical: adding links there
    # wrapped the line and squeezed the topbar login target under 44px.
    assert 'sidebar-footer"><span class="preview-dot" aria-hidden="true"></span><span data-locale-key="footer">편하게 질문해 보세요</span> <a href="./third-party-licenses.html">오픈소스 고지</a></div>' in INDEX
    # The links ride the polish layer, not the pinned base stylesheet.
    polish = (STATIC / "padiem-chat-ui-polish.css").read_text(encoding="utf-8")
    assert ".sidebar-legal-links" in polish
    assert ".guest-legal-links" not in polish


def test_the_login_dialog_carries_the_consent_line():
    """로그인 창 한 줄: 계속하면 이용약관·개인정보처리방침에 동의(두 명사가 링크)."""
    auth = INDEX[INDEX.index('id="authDialog"'):INDEX.index("</dialog>", INDEX.index('id="authDialog"'))]
    assert 'class="auth-legal-consent"' in auth
    assert 'href="./terms.html" data-locale-key="legal-terms">이용약관</a>' in auth
    assert 'href="./privacy.html" data-locale-key="legal-privacy">개인정보처리방침</a>' in auth
    assert "계속하면" in auth and "동의하는 것으로 봅니다" in auth


def test_the_legal_layer_uses_the_accepted_palette_and_leaves_styles_css_alone():
    # The accepted stylesheet is byte-pinned by the style contract; the legal
    # pages must not depend on touching it.
    assert "legal-pages.css" in PRIVACY and "legal-pages.css" in TERMS
    for token in ("#f8f8fb", "#19191d", "#6557e8"):
        assert token in LEGAL_CSS
    # #7187 R3 2차: the shared hairline number lives in the token sheet and the
    # legal layer consumes it (the pages load padiem-tokens.css first).
    tokens_css = (STATIC / "padiem-tokens.css").read_text(encoding="utf-8")
    assert "#e3e3e9" in tokens_css
    assert "--legal-line: var(--line);" in LEGAL_CSS
    for page in (PRIVACY, TERMS):
        assert page.index("padiem-tokens.css") < page.index("legal-pages.css")
