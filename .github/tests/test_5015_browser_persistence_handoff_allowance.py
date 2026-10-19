"""#5015 — the Android handoff exception cannot widen the persistence gate.

`b62_browser_persistence_audit.py` fails the build on any browser persistence
primitive. The Android sign-in return is the one reviewed exception: a single
key in a single file reached through one exact call shape. These tests pin the
branch so a future edit cannot turn the exception back into a general
persistence allowance, and so removing the seam cannot be used to make the
gate pass vacuously.
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

_APP = audit.HANDOFF_FILE
_OTHER_FILE = "apps/padiem-chat/static/history.js"
_DECL = audit.HANDOFF_DECLARATION


def _allowed(line: str, *, relative: str = _APP, declaration: str = _DECL) -> bool:
    text = f"{declaration}\n{line}\n"
    start = text.index("sessionStorage")
    # main() counts the canonical declaration, so the probe must too.
    return audit._is_reviewed_handoff(relative, text, start, text.count(_DECL))


class ReviewedHandoffAllowance(unittest.TestCase):
    def test_reviewed_accesses_are_allowed(self) -> None:
        for line in (
            'const raw = window.sessionStorage.getItem(ANDROID_HANDOFF_STORAGE_KEY);',
            'window.sessionStorage.setItem(ANDROID_HANDOFF_STORAGE_KEY, payload);',
            'window.sessionStorage.removeItem(ANDROID_HANDOFF_STORAGE_KEY);',
        ):
            self.assertTrue(_allowed(line), line)

    def test_any_other_key_is_still_a_violation(self) -> None:
        for line in (
            'window.sessionStorage.setItem("padiem.session.v1", token);',
            'window.sessionStorage.setItem(ANDROID_HANDOFF_STORAGE_KEY2, token);',
            "window.sessionStorage.clear();",
        ):
            self.assertFalse(_allowed(line), line)

    def test_aliasing_the_store_is_still_a_violation(self) -> None:
        self.assertFalse(_allowed("const store = window.sessionStorage;"))
        self.assertFalse(_allowed('store.setItem("k", token); // via window.sessionStorage'))

    def test_the_exception_is_confined_to_one_file(self) -> None:
        line = "window.sessionStorage.setItem(ANDROID_HANDOFF_STORAGE_KEY, payload);"
        self.assertFalse(_allowed(line, relative=_OTHER_FILE))

    def test_a_moved_or_duplicated_key_declaration_revokes_the_exception(self) -> None:
        line = "window.sessionStorage.setItem(ANDROID_HANDOFF_STORAGE_KEY, payload);"
        self.assertFalse(_allowed(line, declaration='const ANDROID_HANDOFF_STORAGE_KEY = "other";'))
        self.assertFalse(_allowed(line, declaration=f"{_DECL}\n{_DECL}"))


class ShippedSourceStillMatchesTheGate(unittest.TestCase):
    def test_app_js_storage_lines_are_all_the_reviewed_seam(self) -> None:
        text = (ROOT / _APP).read_text(encoding="utf-8")
        lines = [line for line in text.splitlines() if "sessionStorage" in line]
        self.assertTrue(lines, "the Android handoff storage seam disappeared")
        for line in lines:
            self.assertTrue(audit.HANDOFF_USAGE.search(line), line)

    def test_audit_passes_on_the_shipped_tree(self) -> None:
        audit.main()


if __name__ == "__main__":
    unittest.main()
