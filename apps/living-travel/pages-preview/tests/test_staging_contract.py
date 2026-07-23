"""Staging contract tests for the connected Living Travel staging surface.

These tests guard the security/privacy contract of ``site/staging/**``:

* the Firebase Web SDK is the modular ESM build, pinned to an exact version;
* the ``/staging/*`` CSP allows only the exact gstatic script origin and the
  exact Firebase auth + Modal staging API connect origins (no wildcard, no
  ``unsafe-inline``, no ``unsafe-eval``);
* the synthetic preview CSP on ``/*`` is unchanged (still ``script-src 'none'``);
* no secrets (service account, private key, Neon URL, Modal/operator secret)
  and only public Firebase web config ship to the browser;
* API content is rendered with safe DOM sinks only (no ``innerHTML`` etc.);
* no Firebase ID token is stored in custom localStorage/sessionStorage;
* staging HTML uses no inline ``style=`` attributes (CSP omits unsafe-inline).

Standard library only (no third-party dependencies), like the synthetic
preview tests. Run with:

    python -m pytest apps/living-travel/pages-preview/tests -q
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from urllib.parse import urlparse

# tests/test_staging_contract.py  →  pages-preview/  →  site/  →  staging/
SITE_DIR = Path(__file__).resolve().parents[1] / "site"
STAGING_DIR = SITE_DIR / "staging"
HEADERS_FILE = SITE_DIR / "_headers"

# Pinned values the contract fixes. If these change, the SDK import URLs in
# firebase.js, API_BASE in config.js, and the /staging/* CSP must change too.
EXPECTED_SDK_VERSION = "12.16.0"
EXPECTED_API_ORIGIN = "https://padiemipu--ai-revenue-living-travel-staging-web.modal.run"
EXPECTED_AUTH_DOMAIN = "ai-revenue-lab-identity.firebaseapp.com"

STAGING_HTML = ["index.html", "traveler.html", "operator.html"]
STAGING_JS = [
    "assets/config.js",
    "assets/firebase.js",
    "assets/api.js",
    "assets/dom.js",
    "assets/app-index.js",
    "assets/app-traveler.js",
    "assets/app-operator.js",
]
STAGING_CSS = ["assets/staging.css"]
ALL_STAGING_FILES = STAGING_HTML + STAGING_JS + STAGING_CSS

# Firebase auth origins that the modular SDK must be allowed to contact.
FIREBASE_CONNECT_ORIGINS = [
    "https://identitytoolkit.googleapis.com",
    "https://securetoken.googleapis.com",
    "https://www.googleapis.com",
    f"https://{EXPECTED_AUTH_DOMAIN}",
]

STAGING_LABEL = "Staging · Synthetic data · Connected API"
SYNTHETIC_MARKER = "Synthetic Preview"

# Patterns that indicate secrets/private infrastructure. Deliberately specific
# to avoid false positives on class names (e.g. "desk-header") and placeholders.
SECRET_PATTERNS = [
    re.compile(r"private_key", re.IGNORECASE),
    re.compile(r"client_email", re.IGNORECASE),
    re.compile(r"BEGIN [A-Z ]*PRIVATE KEY"),
    re.compile(r"postgres(ql)?://"),
    re.compile(r"neon\.tech", re.IGNORECASE),
    re.compile(r"FIREBASE_SERVICE_ACCOUNT"),
    re.compile(r"LT_DATABASE_URL"),
    re.compile(r"LT_MIGRATION_DATABASE_URL"),
    re.compile(r"LT_OPERATOR_SECRET"),
    re.compile(r"sk-[A-Za-z0-9]{10,}"),
    re.compile(r"sk_(live|test)"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"gho_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
]

# Unsafe DOM sinks that could turn API data into markup. Matched as property
# accesses / calls (leading dot or call paren) so documentation comments that
# merely name the sinks do not trigger false positives.
UNSAFE_DOM_SINKS = [".innerHTML", ".outerHTML", ".insertAdjacentHTML", "document.write("]

# Custom Web Storage usage (where an app would stash an ID token). Matched as
# member access so comments naming "localStorage/sessionStorage" don't match.
WEB_STORAGE_RE = re.compile(r"(localStorage|sessionStorage)\s*[\.\[]")


def _read(rel: str) -> str:
    return (STAGING_DIR / rel).read_text(encoding="utf-8")


def _headers_blocks() -> dict[str, list[str]]:
    """Parse _headers into {path_pattern: [stripped header lines]}."""
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    for line in HEADERS_FILE.read_text(encoding="utf-8").splitlines():
        if line.strip() == "":
            continue
        if line[:1] in (" ", "\t"):
            if current is not None:
                blocks[current].append(line.strip())
        elif line.lstrip().startswith("#"):
            current = None
        else:
            current = line.strip()
            blocks[current] = []
    return blocks


def _csp_for(blocks: dict[str, list[str]], path: str) -> str | None:
    for entry in blocks.get(path, []):
        if entry.startswith("!"):
            continue
        if entry.lower().startswith("content-security-policy:"):
            return entry.split(":", 1)[1].strip()
    return None


def _detached(blocks: dict[str, list[str]], path: str) -> set[str]:
    return {entry[1:].strip() for entry in blocks.get(path, []) if entry.startswith("!")}


def _config_const(name: str) -> str | None:
    text = _read("assets/config.js")
    match = re.search(rf'export const {name}\s*=\s*"([^"]+)"', text)
    return match.group(1) if match else None


def _csp_directives(csp: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for part in csp.split(";"):
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        result[tokens[0]] = tokens[1:]
    return result


class TestStagingFileStructure(unittest.TestCase):
    def test_staging_dir_exists(self) -> None:
        self.assertTrue(STAGING_DIR.is_dir(), f"Missing staging dir: {STAGING_DIR}")

    def test_all_staging_files_exist(self) -> None:
        for rel in ALL_STAGING_FILES:
            self.assertTrue((STAGING_DIR / rel).exists(), f"Missing staging file: {rel}")


class TestPinnedFirebaseSdk(unittest.TestCase):
    def test_config_pins_expected_version(self) -> None:
        self.assertEqual(_config_const("FIREBASE_SDK_VERSION"), EXPECTED_SDK_VERSION)

    def test_firebase_imports_use_pinned_version(self) -> None:
        text = _read("assets/firebase.js")
        versions = re.findall(
            r'https://www\.gstatic\.com/firebasejs/([^/\s"\']+)/', text
        )
        self.assertTrue(versions, "firebase.js has no pinned gstatic import URLs")
        self.assertNotIn("latest", versions)
        for version in versions:
            self.assertEqual(version, EXPECTED_SDK_VERSION)

    def test_modular_not_compat(self) -> None:
        text = _read("assets/firebase.js")
        self.assertNotIn("firebase-compat", text)
        self.assertIn("firebase-app.js", text)
        self.assertIn("firebase-auth.js", text)
        self.assertIn("import {", text)

    def test_html_does_not_load_sdk_directly(self) -> None:
        for rel in STAGING_HTML:
            self.assertNotIn("gstatic", _read(rel), f"{rel} loads the SDK directly")

    def test_html_uses_module_scripts(self) -> None:
        for rel in STAGING_HTML:
            self.assertRegex(_read(rel), r'<script[^>]*type="module"')


class TestStagingCsp(unittest.TestCase):
    def setUp(self) -> None:
        self.blocks = _headers_blocks()
        self.staging_csp = _csp_for(self.blocks, "/staging/*")
        self.global_csp = _csp_for(self.blocks, "/*")

    def test_global_preview_csp_unchanged(self) -> None:
        self.assertIsNotNone(self.global_csp)
        self.assertIn("script-src 'none'", self.global_csp)
        self.assertIn("connect-src 'none'", self.global_csp)

    def test_staging_detaches_global_csp(self) -> None:
        self.assertIn("Content-Security-Policy", _detached(self.blocks, "/staging/*"))

    def test_staging_csp_present(self) -> None:
        self.assertIsNotNone(self.staging_csp, "/staging/* has no CSP")

    def test_script_src_allows_gstatic_only(self) -> None:
        directives = _csp_directives(self.staging_csp)
        self.assertIn("https://www.gstatic.com", directives.get("script-src", []))
        self.assertIn("'self'", directives.get("script-src", []))

    def test_connect_src_has_firebase_and_api_origins(self) -> None:
        directives = _csp_directives(self.staging_csp)
        connect = directives.get("connect-src", [])
        for origin in FIREBASE_CONNECT_ORIGINS:
            self.assertIn(origin, connect, f"connect-src missing {origin}")
        self.assertIn(EXPECTED_API_ORIGIN, connect)

    def test_no_wildcard_or_unsafe(self) -> None:
        self.assertNotIn("*", self.staging_csp)
        self.assertNotIn("'unsafe-inline'", self.staging_csp)
        self.assertNotIn("'unsafe-eval'", self.staging_csp)

    def test_config_api_base_matches_csp_origin(self) -> None:
        api_base = _config_const("API_BASE")
        self.assertIsNotNone(api_base)
        parsed = urlparse(api_base)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        self.assertEqual(origin, EXPECTED_API_ORIGIN)
        self.assertIn(origin, _csp_directives(self.staging_csp).get("connect-src", []))

    def test_config_auth_domain_matches_csp(self) -> None:
        text = _read("assets/config.js")
        self.assertIn(EXPECTED_AUTH_DOMAIN, text)
        connect = _csp_directives(self.staging_csp).get("connect-src", [])
        self.assertIn(f"https://{EXPECTED_AUTH_DOMAIN}", connect)


class TestNoSecrets(unittest.TestCase):
    def test_no_secret_patterns_in_staging(self) -> None:
        errors: list[str] = []
        for rel in ALL_STAGING_FILES:
            text = _read(rel)
            for pattern in SECRET_PATTERNS:
                if pattern.search(text):
                    errors.append(f"{rel}: matches secret pattern {pattern.pattern}")
        self.assertEqual(errors, [], "Secret patterns found:\n" + "\n".join(errors))

    def test_config_has_only_public_web_keys(self) -> None:
        text = _read("assets/config.js")
        forbidden_keys = [
            "private_key",
            "client_email",
            "client_id",
            "database_url",
            "token_uri",
            "service_account",
        ]
        for key in forbidden_keys:
            self.assertNotIn(key, text, f"config.js contains private key '{key}'")
        # Public web config shape is present.
        for key in ["apiKey", "authDomain", "projectId", "appId"]:
            self.assertIn(key, text, f"config.js missing public web key '{key}'")


class TestSafeRendering(unittest.TestCase):
    def test_no_unsafe_dom_sinks(self) -> None:
        errors: list[str] = []
        for rel in STAGING_JS:
            text = _read(rel)
            for sink in UNSAFE_DOM_SINKS:
                if sink in text:
                    errors.append(f"{rel}: uses unsafe sink '{sink}'")
        self.assertEqual(errors, [], "Unsafe DOM sinks:\n" + "\n".join(errors))

    def test_no_custom_token_storage(self) -> None:
        errors: list[str] = []
        for rel in STAGING_JS:
            text = _read(rel)
            if WEB_STORAGE_RE.search(text):
                errors.append(f"{rel}: uses Web Storage member access")
        self.assertEqual(
            errors, [], "Custom token storage found:\n" + "\n".join(errors)
        )

    def test_no_inline_style_attributes(self) -> None:
        errors: list[str] = []
        for rel in STAGING_HTML:
            if re.search(r"\bstyle\s*=", _read(rel), re.IGNORECASE):
                errors.append(f"{rel}: inline style attribute (CSP forbids unsafe-inline)")
        self.assertEqual(errors, [], "Inline styles:\n" + "\n".join(errors))


class TestStagingLabels(unittest.TestCase):
    def test_staging_label_present(self) -> None:
        for rel in STAGING_HTML:
            self.assertIn(STAGING_LABEL, _read(rel), f"{rel}: missing staging label")

    def test_synthetic_notice_present(self) -> None:
        for rel in STAGING_HTML:
            self.assertIn(SYNTHETIC_MARKER, _read(rel), f"{rel}: missing synthetic notice")


# ---- Email/Password auth contract -------------------------------------------

FORBIDDEN_AUTH_UI_PATTERNS = [
    re.compile(r"sign.?up", re.IGNORECASE),
    re.compile(r"reset.*password|password.*reset", re.IGNORECASE),
    re.compile(r"create.?account", re.IGNORECASE),
    re.compile(r"register", re.IGNORECASE),
]
CONSOLE_CREDENTIAL_RE = re.compile(
    r"""console\.(log|error|warn|debug)\s*\(.*(?:email|password|token|credential|secret|authorization|bearer)""",
    re.IGNORECASE,
)


class TestEmailAuthContract(unittest.TestCase):
    """Contract tests for the Email/Password authentication implementation."""

    def test_firebase_imports_sign_in_with_email_and_password(self) -> None:
        text = _read("assets/firebase.js")
        self.assertIn(
            "signInWithEmailAndPassword",
            text,
            "firebase.js must import signInWithEmailAndPassword",
        )

    def test_firebase_exports_sign_in_with_email_wrapper(self) -> None:
        text = _read("assets/firebase.js")
        self.assertIn(
            "export function signInWithEmail",
            text,
            "firebase.js must export a signInWithEmail wrapper",
        )

    def test_sign_in_with_email_delegates_to_sdk(self) -> None:
        text = _read("assets/firebase.js")
        self.assertIn(
            "signInWithEmailAndPassword(auth, email, password)",
            text,
            "signInWithEmail must delegate to the SDK function",
        )

    def test_email_input_type_email(self) -> None:
        html = _read("index.html")
        login_email_line = [
            l for l in html.splitlines() if 'id="login-email"' in l
        ]
        self.assertTrue(login_email_line, "login-email input not found")
        self.assertIn(
            'type="email"', login_email_line[0],
            "login-email input must have type='email'",
        )

    def test_email_input_autocomplete_username(self) -> None:
        html = _read("index.html")
        login_email_line = [
            l for l in html.splitlines() if 'id="login-email"' in l
        ]
        self.assertTrue(login_email_line, "login-email input not found")
        self.assertIn(
            'autocomplete="username"', login_email_line[0],
            "login-email input must have autocomplete='username'",
        )

    def test_password_input_type_password(self) -> None:
        html = _read("index.html")
        login_pass_line = [
            l for l in html.splitlines() if 'id="login-password"' in l
        ]
        self.assertTrue(login_pass_line, "login-password input not found")
        self.assertIn(
            'type="password"', login_pass_line[0],
            "login-password input must have type='password'",
        )

    def test_password_input_autocomplete_current_password(self) -> None:
        html = _read("index.html")
        login_pass_line = [
            l for l in html.splitlines() if 'id="login-password"' in l
        ]
        self.assertTrue(login_pass_line, "login-password input not found")
        self.assertIn(
            'autocomplete="current-password"', login_pass_line[0],
            "login-password input must have autocomplete='current-password'",
        )

    def test_no_sign_up_password_reset_or_register_ui(self) -> None:
        errors: list[str] = []
        for rel in STAGING_HTML:
            text = _read(rel)
            for pattern in FORBIDDEN_AUTH_UI_PATTERNS:
                if pattern.search(text):
                    errors.append(
                        f"{rel}: contains forbidden auth UI pattern: {pattern.pattern}"
                    )
        self.assertEqual(
            errors, [], "Sign-up/password-reset UI must not appear:\n" + "\n".join(errors)
        )

    def test_no_credential_console_output(self) -> None:
        errors: list[str] = []
        for rel in STAGING_JS:
            text = _read(rel)
            if CONSOLE_CREDENTIAL_RE.search(text):
                errors.append(f"{rel}: console.* may output credential data")
        self.assertEqual(
            errors, [], "Console must not log credentials:\n" + "\n".join(errors)
        )

    def test_no_raw_firebase_error_message_in_app_index(self) -> None:
        """app-index.js must not display the raw Firebase err.message to the user."""
        text = _read("assets/app-index.js")
        forbidden = [
            "err.message",
            "error.message",
        ]
        for token in forbidden:
            self.assertNotIn(token, text, f"app-index.js must not reference '{token}' in error display")

    def test_generic_login_error_used(self) -> None:
        text = _read("assets/app-index.js")
        # Email sign-in handler must use the generic message.
        self.assertIn(
            "로그인에 실패했습니다. 이메일과 비밀번호를 확인하세요.",
            text,
        )

    def test_google_sign_in_preserved(self) -> None:
        html = _read("index.html")
        self.assertIn("Google", html, "Google sign-in button must still be present")
        js = _read("assets/app-index.js")
        self.assertIn("signInWithGoogle", js, "app-index.js must still import signInWithGoogle")

    def test_no_credential_stored_in_web_storage_by_app_scripts(self) -> None:
        errors: list[str] = []
        for rel in STAGING_JS:
            text = _read(rel)
            if WEB_STORAGE_RE.search(text):
                errors.append(f"{rel}: uses Web Storage member access")
        self.assertEqual(
            errors,
            [],
            "No staging script may store email/password/token in Web Storage:\n"
            + "\n".join(errors),
        )

    def test_email_form_has_no_role_selection_ui(self) -> None:
        html = _read("index.html")
        self.assertNotIn("traveler", html.split('id="email-auth-form"')[1].split('</div>')[0].lower(),
                         msg="Email auth form must not contain role selection UI")


if __name__ == "__main__":
    unittest.main()
