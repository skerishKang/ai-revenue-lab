"""#6724 2차 판정 함수 시험 (CTO 2026-11-10).

브라우저를 띄우지 않고 판정 함수를 직접 호출한다. 그리고 변이 확인을 한다:
판정 규칙을 일부러 뒤집으면 이 시험이 실패해야 한다. 그래서 시험 파일 안에
"깨진 규칙"을 재현해 두고, 깨진 규칙이 통과시키는 입력을 정상 규칙이
거부하는지 매번 확인한다.

실행:
    python -m pytest .github/tests/test_daily_usage_browser_helpers_261110.py -q
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import daily_usage_browser_checks as checks  # noqa: E402


class ConsoleAllowlistTest(unittest.TestCase):
    def test_unrelated_static_assets_are_allowed_with_a_reason(self):
        allowed = [
            "https://fonts.googleapis.com/css2?family=Inter",
            "https://fonts.gstatic.com/s/inter/v1/abc.woff2",
            "https://chat.padiem.net/favicon.ico",
            "https://chat.padiem.net/push-sw.js",
        ]
        for url in allowed:
            self.assertIsNotNone(checks.console_allow_reason(url), url)

    def test_product_api_errors_are_never_allowed(self):
        blocked = [
            "https://chat.padiem.net/api/chat",
            "https://chat.padiem.net/api/orchestration",
            "https://chat.padiem.net/api/auth/status",
            "https://chat.padiem.net/app.js",
            "https://chat.padiem.net/api/claw/general",
        ]
        for url in blocked:
            self.assertIsNone(checks.console_allow_reason(url), url)

    def test_a_random_404_is_not_excused_by_the_404_text(self):
        ok, code = checks.console_ok([
            ("console", "Failed to load resource: the server responded with a status of 404 (Not Found)",
             "https://chat.padiem.net/api/conversations"),
        ])
        self.assertFalse(ok)
        self.assertEqual(code, "console_error_console_chat_padiem_net_api_conversations")

    def test_console_ok_needs_zero_non_allowlisted_entries(self):
        self.assertEqual(checks.console_ok([]), (True, "none"))
        self.assertEqual(
            checks.console_ok([("console", "boom", "https://fonts.gstatic.com/x.woff2")]),
            (True, "none"),
        )
        ok, code = checks.console_ok([("pageerror", "TypeError: x is undefined", "")])
        self.assertFalse(ok)
        self.assertEqual(code, "console_error_pageerror_page")

    def test_error_code_carries_no_values(self):
        ok, code = checks.console_ok([
            ("console", "leak", "https://chat.padiem.net/api/x?token=SECRET&user=me@example.com"),
        ])
        self.assertFalse(ok)
        self.assertNotIn("SECRET", code)
        self.assertNotIn("@", code)


class AnswerVerdictTest(unittest.TestCase):
    def test_ten_characters_is_the_bar(self):
        self.assertEqual(checks.answer_verdict("네, 시스템이 정상입니다")[0], "PASS")
        verdict, code, head = checks.answer_verdict("짧음")
        self.assertEqual((verdict, code), ("FAIL", "screen_answer_too_short"))
        self.assertEqual(head, "짧음")

    def test_whitespace_only_answer_fails(self):
        self.assertEqual(checks.answer_verdict("   \n\t ")[0], "FAIL")
        self.assertEqual(checks.answer_verdict(None)[0], "FAIL")

    def test_parity_fails_when_only_one_screen_answers(self):
        self.assertEqual(checks.screen_parity("PASS", "PASS"), (True, "none"))
        self.assertEqual(checks.screen_parity("FAIL", "FAIL"), (True, "none"))
        self.assertEqual(checks.screen_parity("PASS", "FAIL"),
                         (False, "screen_parity_chat_only"))
        self.assertEqual(checks.screen_parity("FAIL", "PASS"),
                         (False, "screen_parity_claw_only"))


class ParityTargetTest(unittest.TestCase):
    def test_only_the_failing_screen_is_blamed(self):
        # 실행 42668928406 은 이 지목을 뒤집어, 답한 화면을 FAIL 로 적었다.
        self.assertEqual(checks.parity_target("screen_parity_chat_only"), "browser_claw")
        self.assertEqual(checks.parity_target("screen_parity_claw_only"), "browser_chat")


class SafeCodeTest(unittest.TestCase):
    def test_exception_class_names_become_safe_codes(self):
        # 대문자가 섞인 예외 이름이 unsafe_code 로 사라지지 않아야 한다.
        self.assertEqual(checks.safe_code("browser_claw_Error"), "browser_claw_error")
        self.assertEqual(checks.safe_code("browser_claw_open_TimeoutError"),
                         "browser_claw_open_timeouterror")

    def test_edge_cases_stay_safe(self):
        self.assertEqual(checks.safe_code(""), "unknown")
        self.assertEqual(checks.safe_code("123"), "e_123")
        self.assertLessEqual(len(checks.safe_code("x" * 300)), 80)
        self.assertNotIn(" ", checks.safe_code("a b/c?d=e"))


class StampTest(unittest.TestCase):
    RECENT = ["33d88da1", "5848191a", "496b2347"]

    def test_reads_the_version_from_the_loaded_url(self):
        self.assertEqual(checks.stamp_from_url("https://chat.padiem.net/app.js?v=496b2347"),
                         "496b2347")
        self.assertEqual(checks.stamp_from_url("https://chat.padiem.net/app.js?v=abc&x=1"),
                         "abc")
        self.assertEqual(checks.stamp_from_url("https://chat.padiem.net/app.js"), "")

    def test_head_match_passes(self):
        self.assertEqual(checks.stamp_verdict("496b2347", "496b2347", self.RECENT),
                         ("PASS", "none"))

    def test_one_release_behind_is_a_marked_pass(self):
        self.assertEqual(checks.stamp_verdict("5848191a", "33d88da1", self.RECENT),
                         ("PASS", "deploy_lag"))

    def test_unknown_version_is_a_missing_screen_deploy(self):
        self.assertEqual(checks.stamp_verdict("deadbeef", "33d88da1", self.RECENT),
                         ("FAIL", "screen_deploy_missing"))

    def test_missing_stamp_is_a_failure(self):
        self.assertEqual(checks.stamp_verdict("", "33d88da1", self.RECENT),
                         ("FAIL", "screen_stamp_missing"))

    def test_a_long_dead_string_is_not_excused(self):
        # 변이 확인: 부분 일치로 통과시키면 이 입력이 PASS 가 되어야 한다.
        self.assertNotEqual(checks.stamp_verdict("33d88", "33d88da1", self.RECENT)[0], "PASS")


class SlowdownTest(unittest.TestCase):
    VOICE_BASELINE = [41_500, 40_800, 43_100, 39_900, 42_000, 41_000, 44_200]

    def test_voice_baseline_does_not_warn_at_its_own_speed(self):
        self.assertIsNone(checks.slowdown_note("voice_relay", 41_600, self.VOICE_BASELINE))

    def test_double_the_median_warns(self):
        note = checks.slowdown_note("voice_relay", 84_000, self.VOICE_BASELINE)
        self.assertIsNotNone(note)
        assert note is not None
        self.assertIn(checks.SLOWDOWN_LABEL, note)
        self.assertIn("voice_relay", note)

    def test_just_under_double_does_not_warn(self):
        self.assertIsNone(checks.slowdown_note("voice_relay", 82_000, self.VOICE_BASELINE))

    def test_no_history_means_no_warning(self):
        self.assertIsNone(checks.slowdown_note("voice_relay", 900_000, []))

    def test_only_the_last_seven_samples_count(self):
        # 앞의 오래된 표본(1,000ms)은 창 밖이다. 창 안의 중앙값은 41,500ms 다.
        history = [1_000] * 20 + self.VOICE_BASELINE
        self.assertIsNone(checks.slowdown_note("voice_relay", 80_000, history))
        self.assertIsNotNone(checks.slowdown_note("voice_relay", 90_000, history))

    def test_median_is_the_middle_value(self):
        self.assertEqual(checks.median_of([5, 1, 3]), 3)
        self.assertEqual(checks.median_of([4, 1]), 2)
        self.assertIsNone(checks.median_of([]))


class CaptureNameTest(unittest.TestCase):
    def test_flow_step_name(self):
        self.assertEqual(checks.artifact_filename("browser_chat", 1, "open"),
                         "browser_chat_01_open.png")
        self.assertEqual(checks.artifact_filename("browser_claw", 3, "Answer"),
                         "browser_claw_03_answer.png")
        self.assertEqual(checks.artifact_filename("browser_stamp", 1, "app-version"),
                         "browser_stamp_01_app-version.png")

    def test_capture_width_is_1440(self):
        self.assertEqual(checks.CAPTURE_WIDTH, 1440)
        self.assertEqual(checks.VIEWPORT["width"], 1440)

    def test_no_path_traversal_in_names(self):
        name = checks.artifact_filename("../evil", 1, "../../etc/passwd")
        self.assertNotIn("/", name)
        self.assertNotIn("..", name)


class MutationProbeTest(unittest.TestCase):
    """규칙을 뒤집으면 시험이 실제로 실패하는지 확인한다.

    정상 규칙과 깨진 규칙을 같은 입력에 적용해 결과가 갈리는 것을 본다. 갈리지
    않으면 그 입력은 이 규칙을 지켜주지 못하는 것이므로 시험이 의미 없다.
    """

    def test_stamp_rule_mutation_is_detected(self):
        def broken(observed, head, recent=()):
            # 깨진 규칙: 스탬프가 있으면 무조건 통과.
            return ("PASS", "none") if observed else ("FAIL", "screen_stamp_missing")

        case = ("deadbeef", "33d88da1", ["33d88da1"])
        self.assertEqual(checks.stamp_verdict(*case)[0], "FAIL")
        self.assertEqual(broken(*case)[0], "PASS")

    def test_allowlist_mutation_is_detected(self):
        def broken(url):
            # 깨진 규칙: 404 안내 문구가 있으면 전부 허용.
            return "any-404" if "404" in url else None

        url = "https://chat.padiem.net/api/chat 404"
        self.assertIsNone(checks.console_allow_reason(url))
        self.assertIsNotNone(broken(url))

    def test_slowdown_mutation_is_detected(self):
        def broken(elapsed_ms, history):
            # 깨진 규칙: 중앙값 대신 첫 표본과 비교.
            return "warn" if history and elapsed_ms > history[0] else None

        history = [1_000, 41_500, 41_000, 42_000]
        self.assertIsNone(checks.slowdown_note("voice_relay", 3_000, history))
        self.assertIsNotNone(broken(3_000, history))

    def test_reported_codes_are_safe(self):
        flow = checks.BrowserFlowResult("browser_claw")
        flow.fail("browser_claw_Error")
        self.assertEqual(flow.as_dict()["code"], "browser_claw_error")

    def test_parity_mutation_is_detected(self):
        def broken(chat, claw):
            # 깨진 규칙: 한쪽만 되어도 통과.
            return (True, "none") if "PASS" in (chat, claw) else (True, "none")

        self.assertEqual(checks.screen_parity("PASS", "FAIL"), (False, "screen_parity_chat_only"))
        self.assertEqual(broken("PASS", "FAIL"), (True, "none"))


if __name__ == "__main__":
    unittest.main()
