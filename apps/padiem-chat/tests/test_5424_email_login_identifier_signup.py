"""#5424 signup contract: the email address is the single login identifier.

The signup screen and the server used to disagree about the password floor
and about how many identifiers a new account has. A form that keeps a
separate ID field, or that asks the browser for a longer password than the
server accepts, silently fails a real registration. These checks pin the
served markup, the browser payload, and the server policy to one contract.
"""
from pathlib import Path
import re
from html.parser import HTMLParser

from app.password_auth import PASSWORD_MAX_CHARS, PASSWORD_MIN_CHARS

BASE = Path(__file__).resolve().parents[1] / "static"
HTML = (BASE / "index.html").read_text(encoding="utf-8")
APP = (BASE / "app.js").read_text(encoding="utf-8")
LOCALE = (BASE / "locale.js").read_text(encoding="utf-8")


class Nodes(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = {}
        self.forms = {}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if "id" in attributes:
            self.elements[attributes["id"]] = (tag, attributes)
        if tag == "form" and "id" in attributes:
            self.forms[attributes["id"]] = attributes


def _nodes():
    parser = Nodes()
    parser.feed(HTML)
    return parser


def _register_form_html() -> str:
    match = re.search(
        r'<form class="auth-form" id="passwordRegisterForm">(?P<body>.*?)</form>',
        HTML,
        re.S,
    )
    assert match is not None, "the registration form must exist"
    return match.group("body")


def test_signup_has_one_identifier_and_it_is_the_email():
    register = _register_form_html()
    assert "passwordRegisterUsername" not in register
    assert 'name="username"' not in register
    assert 'id="passwordRegisterEmail"' in register
    assert 'name="email"' in register
    assert 'type="email"' in register


def test_the_form_password_floor_matches_the_server_policy():
    """The browser must not demand a longer password than the server accepts."""
    _tag, attributes = _nodes().elements["passwordRegisterPassword"]
    assert attributes.get("minlength") == str(PASSWORD_MIN_CHARS)
    assert attributes.get("maxlength") == str(PASSWORD_MAX_CHARS)
    assert PASSWORD_MIN_CHARS == 8


def test_the_browser_payload_carries_the_email_identifier_only():
    payload = re.search(
        r'passwordAuthRequest\("/api/auth/password/register",\s*\{(?P<body>.*?)\}\)',
        APP,
        re.S,
    )
    assert payload is not None, "the registration request must exist"
    body = payload.group("body")
    assert "username" not in body
    assert "email: passwordRegisterEmail.value" in body


def test_the_login_screen_presents_the_email_identifier():
    assert 'data-locale-key="auth-identifier"' in HTML
    assert "아이디 또는 이메일" not in HTML
    assert '"auth-identifier": "이메일"' in LOCALE
    assert '"auth-identifier": "Email"' in LOCALE
    assert '"auth-password-login": "이메일로 로그인"' in LOCALE
    assert '"auth-password-login": "Log in with email"' in LOCALE


def test_the_password_rule_text_states_the_new_floor():
    assert '"auth-password-rule": "8~128자.' in LOCALE
    assert '"auth-password-rule": "Use 8–128 characters' in LOCALE
    assert "12자 이상" not in LOCALE
    assert "12–128" not in LOCALE


def test_the_removed_id_label_is_gone_from_both_locales():
    assert '"auth-username"' not in LOCALE
    assert '"auth-email-login-id"' in LOCALE
