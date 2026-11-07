"""Public privacy policy and terms pages (#6659).

Google OAuth app verification requires a public privacy policy URL. The
service's static assets are served by the chat Worker's asset deployment and
reach anonymous visitors without any login, so the pages live next to the
existing standalone pages (``help.html``, ``third-party-licenses.html``) and
are linked from the app's sidebar footer.

The drafts describe only what the code actually collects and processes, mark
every owner-reserved field as ``[대표 확인]``, and carry the Google Limited
Use disclosure required for verification.
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


def test_the_owner_reserved_fields_are_marked_not_invented():
    required_markers = [
        "사업자명", "대표자", "주소", "개인정보 보호책임자", "시행일",
    ]
    for marker in required_markers:
        assert "[대표 확인" in PRIVACY, marker
    assert PRIVACY.count("[대표 확인") >= 6
    assert TERMS.count("[대표 확인") >= 3
    # No invented business facts: the placeholders must survive into the draft.
    assert "시행일: <span" in PRIVACY and "시행일: <span" in TERMS


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
    # Delegation wording stays at the "AI 처리 위탁" level: no vendor names.
    assert "AI 답변 생성" in PRIVACY and "위탁" in PRIVACY
    for banned in ("Cloudflare", "Workers", "D1", "OpenAI", "Anthropic", "Agnes", "OpenRouter"):
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
    """두 링크는 로그인 전 게스트 화면 하단에 있고 사이드바 레이아웃은 그대로다."""
    assert 'class="guest-legal-links"' in INDEX
    assert 'href="./privacy.html">개인정보처리방침</a>' in INDEX
    assert 'href="./terms.html">이용약관</a>' in INDEX
    # The accepted sidebar footer stays byte-identical: adding links there
    # wrapped the line and squeezed the topbar login target under 44px.
    assert 'sidebar-footer"><span class="preview-dot" aria-hidden="true"></span><span data-locale-key="footer">편하게 질문해 보세요</span> <a href="./third-party-licenses.html">오픈소스 고지</a></div>' in INDEX
    # The links ride the polish layer, not the pinned base stylesheet.
    assert ".guest-legal-links" in (STATIC / "padiem-chat-ui-polish.css").read_text(encoding="utf-8")


def test_the_legal_layer_uses_the_accepted_palette_and_leaves_styles_css_alone():
    # The accepted stylesheet is byte-pinned by the style contract; the legal
    # pages must not depend on touching it.
    assert "legal-pages.css" in PRIVACY and "legal-pages.css" in TERMS
    for token in ("#f8f8fb", "#19191d", "#6557e8", "#e3e3e9"):
        assert token in LEGAL_CSS
