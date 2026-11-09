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
    """스탬프 판정: 화면 경로 변경 여부 + 6시간 배포 창 (#6724 CTO 지시).

    "스탬프가 main 최근 30커밋 안이면 PASS" 하던 규칙은 화면 파일을 바꾼 PR 이
    머지되고 release 가 빠져도 30커밋 동안 잡지 못했다.
    """

    NOW = 1_800_000_000
    HEAD = "a1b2c3d4" + "0" * 32
    STAMP = "0f9e8d7c" + "1" * 32
    OBSERVED = "0f9e8d7c"

    def verdict(self, **overrides):
        payload = {"stamp_sha": self.STAMP, "screen_changes": [],
                   "ancestor": True, "now_epoch": self.NOW}
        payload.update(overrides)
        return checks.stamp_verdict(self.OBSERVED, self.HEAD, **payload)

    def test_reads_the_version_from_the_loaded_url(self):
        self.assertEqual(checks.stamp_from_url("https://chat.padiem.net/app.js?v=496b2347"),
                         "496b2347")
        self.assertEqual(checks.stamp_from_url("https://chat.padiem.net/app.js?v=abc&x=1"),
                         "abc")
        self.assertEqual(checks.stamp_from_url("https://chat.padiem.net/app.js"), "")

    def test_the_lag_window_is_six_hours(self):
        self.assertEqual(checks.SCREEN_LAG_LIMIT_SECONDS, 6 * 3600)

    def test_no_screen_change_since_the_stamp_is_up_to_date(self):
        self.assertEqual(self.verdict(), ("PASS", "up_to_date", self.OBSERVED))

    def test_a_screen_change_within_six_hours_is_a_marked_pass(self):
        self.assertEqual(
            self.verdict(screen_changes=[("b" * 40, self.NOW - 3 * 3600)]),
            ("PASS", "deploy_lag", "bbbbbbbb"),
        )

    def test_six_hours_is_still_inside_the_window(self):
        self.assertEqual(self.verdict(screen_changes=[("b" * 40, self.NOW - 6 * 3600)])[:2],
                         ("PASS", "deploy_lag"))

    def test_beyond_six_hours_is_a_missing_screen_deploy(self):
        self.assertEqual(
            self.verdict(screen_changes=[("b" * 40, self.NOW - 6 * 3600 - 1)]),
            ("FAIL", "screen_deploy_missing", "bbbbbbbb"),
        )

    def test_the_earliest_screen_change_sets_the_clock(self):
        # 최신 변경(5시간 전)이 아니라 가장 이른 변경(9시간 전)이 기준이다.
        changes = [("c" * 40, self.NOW - 5 * 3600), ("b" * 40, self.NOW - 9 * 3600)]
        self.assertEqual(self.verdict(screen_changes=changes),
                         ("FAIL", "screen_deploy_missing", "bbbbbbbb"))

    def test_a_stamp_commit_that_cannot_be_found_fails(self):
        self.assertEqual(self.verdict(stamp_sha=""),
                         ("FAIL", "screen_stamp_unknown", self.OBSERVED))

    def test_a_stamp_outside_main_history_fails(self):
        self.assertEqual(self.verdict(ancestor=False),
                         ("FAIL", "screen_stamp_not_on_main", self.OBSERVED))

    def test_unreadable_history_is_not_a_pass(self):
        self.assertEqual(self.verdict(screen_changes=None)[:2],
                         ("FAIL", "screen_history_unavailable"))

    def test_a_missing_stamp_is_a_failure(self):
        self.assertEqual(checks.stamp_verdict("", self.HEAD, stamp_sha=self.STAMP),
                         ("FAIL", "screen_stamp_missing", ""))

    def test_a_stamp_that_is_not_a_sha_is_a_failure(self):
        # '33d88'(5자)·'v1.2.3' 은 배포 스크립트가 넣는 모양이 아니다.
        self.assertEqual(checks.stamp_verdict("33d88", self.HEAD, stamp_sha=self.STAMP)[0],
                         "FAIL")
        self.assertEqual(checks.stamp_verdict("v1.2.3", self.HEAD)[0], "FAIL")

    def test_the_head_stamp_needs_no_git_lookup(self):
        self.assertEqual(checks.stamp_verdict("a1b2c3d4", self.HEAD, stamp_sha=""),
                         ("PASS", "up_to_date", "a1b2c3d4"))


class ReleasePathContractTest(unittest.TestCase):
    """판정 경로가 실제 배포 스크립트의 경로와 같은지.

    목록이 갈라지면 화면을 바꾼 커밋을 놓쳐도 점검이 PASS 를 낸다.
    """

    def test_the_same_paths_the_release_script_archives(self):
        script = (Path(__file__).resolve().parents[2]
                  / "deploy" / "chat-release" / "release_chat.ps1")
        text = script.read_text(encoding="utf-8")
        line = next(row for row in text.splitlines()
                    if "git -C $RepoRoot archive" in row and " -- " in row)
        archived = tuple(part for part in line.split(" -- ", 1)[1].split()
                         if part.startswith("apps/"))
        self.assertEqual(archived, checks.SCREEN_RELEASE_PATHS)


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
        def broken(observed, head, **kwargs):
            # 깨진 규칙: 스탬프가 있으면 무조건 통과(예전 30커밋 규칙의 축소판).
            return (("PASS", "none", "") if observed
                    else ("FAIL", "screen_stamp_missing", ""))

        now = 1_800_000_000
        changes = [("b" * 40, now - 30 * 3600)]
        self.assertEqual(
            checks.stamp_verdict("0f9e8d7c", "a" * 40, stamp_sha="f" * 40,
                                 screen_changes=changes, now_epoch=now)[0],
            "FAIL",
        )
        self.assertEqual(broken("0f9e8d7c", "a" * 40)[0], "PASS")

    def test_stamp_window_mutation_is_detected(self):
        # 창을 12시간으로 넓히면 7시간 전 변경이 통과해 버린다.
        now = 1_800_000_000
        age = 7 * 3600
        verdict = checks.stamp_verdict(
            "0f9e8d7c", "a" * 40, stamp_sha="f" * 40,
            screen_changes=[("b" * 40, now - age)], now_epoch=now)
        self.assertEqual(verdict[0], "FAIL")
        self.assertLessEqual(age, 12 * 3600)

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
