"""#8075 후속 — sid 없는 세션 쿠키 사용 0 계약(전환 기한 이후).

검토된 sid 없는 세션 수용 기한(app.auth.SIDELESS_SESSION_ACCEPTED_UNTIL,
2026-11-18 23:59:59Z)이 만료되어 sid 없는 시험 쿠키는 401이 된다. 이 계약은
테스트가 더 이상 sid 없는 create_session_token 쿠키를 심지 않는지("사용 0")를
pytest 수집과 같은 방식(다중 라인 호출 포함)으로 고정한다.

예외(정책 시험 — sid 없는 동작 자체가 시험 대상):
  * test_261110_sidless_session_policy.py — 전환 기한 계약 양변 고정.
  * test_5225_logout_session_revocation.py — 로그아웃 세션 무효화 계약.
  * test_7233_identity_shadow_pointer_refresh.py — request_canonical_session_id의
    sid 없는 경로(단위).
  * test_email_recovery_7606.py — 전환 기한 스위치 off에서 sid 없는 쿠키가
    되살아나지 않는다는 정책.
  * test_7078_shadow_verify.py — shadow verify의 sid 없는 legacy 경로
    (no_token_legacy_nosid) 단위 시험.
"""
from __future__ import annotations

import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent

EXEMPT = {
    "test_261110_sidless_session_policy.py",
    "test_5225_logout_session_revocation.py",
    "test_7233_identity_shadow_pointer_refresh.py",
    "test_email_recovery_7606.py",
    "test_7078_shadow_verify.py",
}


def _call_args(text: str, start: int) -> str:
    depth = 0
    i = start
    while i < len(text):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        elif ch in ("\"", "'"):
            quote = ch
            i += 1
            while i < len(text):
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == quote:
                    break
                i += 1
        i += 1
    return text[start:]


def test_no_sidless_create_session_token_usage_outside_policy_tests() -> None:
    offenders: list[str] = []
    for path in sorted(TESTS.glob("test_*.py")):
        if path.name in EXEMPT:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(r"(?<![\w.])create_session_token\s*\(", text):
            args = _call_args(text, match.end() - 1)
            if "canonical_session_id" not in args:
                line = text[:match.start()].count("\n") + 1
                offenders.append(f"{path.name}:{line}")
                break
    assert not offenders, (
        "sid 없는 create_session_token 사용이 남아 있다(정책 시험만 예외): "
        + ", ".join(offenders)
    )


def test_every_sid_session_token_consumer_imports_the_helper() -> None:
    """sid_session_token을 쓰는 시험은 헬퍼를 임포트한다(CI 수집과 같은 목록)."""
    missing: list[str] = []
    for path in sorted(TESTS.glob("test_*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if "sid_session_token(" in text and "sid_session_helper" not in text:
            missing.append(path.name)
    assert not missing, f"헬퍼 import가 없는 시험: {missing}"