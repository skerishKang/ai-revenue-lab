"""#7690 static contracts: public site feedback is anonymous, bounded, script-off safe."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_home_has_footer_site_feedback_form():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert 'id="siteFeedback"' in html and 'id="siteFeedbackOpen"' in html
    assert 'id="siteFeedbackForm"' in html and 'id="siteFeedbackBody"' in html
    assert '사이트 의견 보내기' in html
    assert '의원실 민원·제안은' in html
    assert '전화' in html and '이메일' in html
    assert 'href="tel:062-613-5133"' in html
    assert 'href="mailto:miran2640@naver.com"' in html
    assert 'maxlength="2000"' in html
    assert 'id="siteFeedbackTrap"' in html and 'aria-hidden="true"' in html
    assert 'id="siteFeedbackStatus"' in html and 'role="status"' in html
    assert 'src="./static/site-feedback.js"' in html
    assert 'type="email"' not in html and 'name="email"' not in html and 'name="phone"' not in html
    assert 'name="contact"' not in html


def test_site_feedback_script_is_anonymous_and_bounded():
    js = (ROOT / "static" / "site-feedback.js").read_text(encoding="utf-8")
    assert 'https://chat.padiem.net/api/site-feedback' in js
    assert 'miraen-home' in js
    assert 'rendered_at' in js and 'honeypot' in js
    assert '2000' in js
    assert 'credentials: "omit"' in js and 'mode: "cors"' in js
    assert 'localStorage' not in js and 'sessionStorage' not in js
    assert 'type="email"' not in js and 'name="email"' not in js
    # #7550: the 201 receipt moves to the announced notice block; the failure
    # guidance with the office contact stays in the form's own status line.
    assert 'siteFeedbackDone' in js and 'siteFeedbackAgain' in js
    assert '보내지 못했습니다. 잠시 후 다시 시도해 주세요. 급한 일은 의원실 전화(062-613-5133)·이메일로 연락해 주세요.' in js


def test_site_feedback_styles_cover_footer_and_mobile():
    css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
    assert '.site-feedback {' in css
    assert '.site-feedback-form {' in css
    assert '.site-feedback-body {' in css
    assert '.site-feedback-trap {' in css
    assert '.site-feedback-status {' in css
    assert 'var(--tap)' in css
    assert '@media (max-width: 720px)' in css
    assert '.site-feedback-send { width: 100%; }' in css