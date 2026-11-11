"""#7459 - the sign-in hint exception cannot widen the persistence gate.

The owner allowed ONE UI-state hint (2026-11-11): a boolean "was signed in"
flag, one key, one file, closed call shapes. These tests pin that seam so it
cannot turn into a general localStorage allowance.
"""

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "b62_browser_persistence_audit",
    ROOT / ".github/scripts/b62_browser_persistence_audit.py",
)
audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(audit)

_FILE = audit.AUTH_HINT_FILE
_OTHER_FILE = "apps/padiem-chat/static/history.js"
_DECL = audit.AUTH_HINT_DECLARATION


def _allowed(line: str, *, relative: str = _FILE, declaration: str = _DECL) -> bool:
    text = f"{declaration}\n{line}\n"
    start = text.index("localStorage")
    return audit._is_reviewed_auth_hint(relative, text, start, text.count(_DECL))


class ReviewedAuthHintAllowance(unittest.TestCase):
    def test_reviewed_accesses_are_allowed(self) -> None:
        for line in (
            'return window.localStorage.getItem(LAST_SIGNED_IN_KEY) === "1";',
            'window.localStorage.setItem(LAST_SIGNED_IN_KEY, "1");',
            "window.localStorage.removeItem(LAST_SIGNED_IN_KEY);",
        ):
            self.assertTrue(_allowed(line), line)

    def test_only_the_boolean_value_may_be_written(self) -> None:
        for line in (
            "window.localStorage.setItem(LAST_SIGNED_IN_KEY, user.email);",
            'window.localStorage.setItem(LAST_SIGNED_IN_KEY, "alice@example.com");',
            "window.localStorage.setItem(LAST_SIGNED_IN_KEY, token);",
        ):
            self.assertFalse(_allowed(line), line)

    def test_any_other_key_or_call_is_still_a_violation(self) -> None:
        for line in (
            'window.localStorage.setItem("padiem.chat.history", text);',
            'window.localStorage.getItem("padiem.chat.auth.lastSignedIn");',
            "window.localStorage.clear();",
            "window.localStorage.setItem(LAST_SIGNED_IN_KEY2, \"1\");",
        ):
            self.assertFalse(_allowed(line), line)

    def test_aliasing_the_store_is_still_a_violation(self) -> None:
        self.assertFalse(_allowed("const store = window.localStorage;"))

    def test_the_exception_is_confined_to_one_file(self) -> None:
        self.assertFalse(_allowed('window.localStorage.setItem(LAST_SIGNED_IN_KEY, "1");', relative=_OTHER_FILE))

    def test_a_moved_or_duplicated_key_declaration_revokes_the_exception(self) -> None:
        line = 'window.localStorage.setItem(LAST_SIGNED_IN_KEY, "1");'
        self.assertFalse(_allowed(line, declaration='const LAST_SIGNED_IN_KEY = "other";'))
        self.assertFalse(_allowed(line, declaration=f"{_DECL}\n{_DECL}"))

    def test_session_storage_is_not_covered(self) -> None:
        text = f'{_DECL}\nwindow.sessionStorage.setItem(LAST_SIGNED_IN_KEY, "1");\n'
        # The hint exception only ever applies to localStorage matches.
        self.assertIn("localStorage", audit.FORBIDDEN)
        self.assertFalse(audit.AUTH_HINT_USAGE.search(text))


if __name__ == "__main__":
    unittest.main()
