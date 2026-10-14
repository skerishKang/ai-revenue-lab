"""#3936: user-facing Claw refusal copy must never ship as corrupted ``???``.

Two 403 refusals in the general Claw lane were written to disk already
mojibake-corrupted (introduced that way in #3929): a signed-in owner whose
conversation could not be bound to the canonical B54 session, and one whose
conversation had no workspace scope, each received a sentence made only of
``?`` characters. The browser renders that literally, so the owner sees no
readable reason for a safe refusal.

This guard is deliberately narrow and mechanical: every message literal handed
to ``_error``/``_deny`` in the Worker app must contain no ``?`` character.
Korean copy is 3-byte UTF-8; when it is mangled by a lossy decode each byte
becomes ``?``, so a corrupted sentence always carries at least one ``?`` while
a correct Korean, English or absent message never does.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
GENERAL_ROUTES = APP / "claw_general_routes.py"

# The canonical copy for each code, pinned so the two repaired sentences cannot
# silently drift apart again. ``canonical_b54_session_unavailable`` is already
# used with this exact sentence in ``claw_routes.py``; the general lane must not
# invent a second wording for the same code.
CANONICAL_COPY = {
    "canonical_b54_session_unavailable": "인증된 Claw 실행 권한을 확인할 수 없습니다.",
    "workspace_scope_unavailable": "대화 작업 공간을 확인할 수 없습니다.",
}


def _message_literals(path: Path) -> list[tuple[int, str]]:
    """Every string-literal argument of an ``_error``/``_deny`` call."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        name = getattr(callee, "id", None) or getattr(callee, "attr", None)
        if name not in {"_error", "_deny"}:
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                found.append((node.lineno, arg.value))
    return found


def test_no_refusal_message_ships_corrupted_question_marks():
    offenders = []
    scanned = 0
    for path in sorted(APP.glob("*.py")):
        for lineno, message in _message_literals(path):
            scanned += 1
            if "?" in message:
                offenders.append(f"{path.name}:{lineno}: {message!r}")
    assert scanned > 300, "the scan must actually reach the Worker refusal copy"
    assert offenders == [], (
        "a user-facing refusal message is corrupted and would render as '?' "
        f"in the browser: {offenders}"
    )


@pytest.mark.parametrize("code,expected", sorted(CANONICAL_COPY.items()))
def test_bounded_refusal_copy_is_the_canonical_korean_sentence(code, expected):
    general = GENERAL_ROUTES.read_text(encoding="utf-8")
    assert f'"{code}",\n' in general or f'"{code}"' in general, code
    assert expected in general, (
        f"{code} must carry the canonical Korean sentence, not corrupted copy"
    )


def test_the_two_repaired_sentences_are_real_korean():
    """A repaired sentence must actually contain Hangul, not ASCII filler."""
    general = GENERAL_ROUTES.read_text(encoding="utf-8")
    for expected in CANONICAL_COPY.values():
        assert expected in general
        assert any("가" <= ch <= "힣" for ch in expected), expected
        assert "?" not in expected
