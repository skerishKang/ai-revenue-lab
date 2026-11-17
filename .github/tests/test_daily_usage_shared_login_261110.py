"""browser_shared_login 판정 함수 직접 호출 시험 (#7078, 2026-11-10).

브라우저 없이 순수 함수만 부른다. 쿠키 이름 목록만 입력으로 받으며, 값은
다루지 않는다.

실행:
    python -m pytest .github/tests/test_daily_usage_shared_login_261110.py -q
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import daily_usage_browser_checks as checks  # noqa: E402

ACCESS = checks.SHARED_ACCESS_COOKIE
REFRESH = checks.SHARED_REFRESH_COOKIE
MARKER = checks.SHARED_MARKER_COOKIE
SESSION = checks.PADIEM_SESSION_COOKIE


class SharedAccessCookieVerdictTest(unittest.TestCase):
    def test_access_cookie_present_passes(self):
        verdict, code = checks.shared_access_cookie_verdict([ACCESS, REFRESH, MARKER])
        self.assertEqual((verdict, code), ("PASS", "none"))

    def test_access_cookie_alone_passes(self):
        verdict, code = checks.shared_access_cookie_verdict([ACCESS])
        self.assertEqual((verdict, code), ("PASS", "none"))

    def test_missing_access_cookie_fails(self):
        for names in ([], [REFRESH], [MARKER], [REFRESH, MARKER], [SESSION]):
            verdict, code = checks.shared_access_cookie_verdict(names)
            self.assertEqual((verdict, code), ("FAIL", "shared_cookie_missing"), names)

    def test_unrelated_names_do_not_satisfy(self):
        verdict, code = checks.shared_access_cookie_verdict(["__Host-padiem-shared-accessx"])
        self.assertEqual((verdict, code), ("FAIL", "shared_cookie_missing"))


class SharedCredentialOkTest(unittest.TestCase):
    def test_email_shape_passes(self):
        self.assertTrue(checks.shared_credential_ok("qa@example.com"))
        self.assertTrue(checks.shared_credential_ok("  qa@example.com  "))

    def test_non_email_shape_fails(self):
        self.assertFalse(checks.shared_credential_ok("cgi1003"))
        self.assertFalse(checks.shared_credential_ok(""))
        self.assertFalse(checks.shared_credential_ok(None))
        self.assertFalse(checks.shared_credential_ok("qa@"))
        self.assertFalse(checks.shared_credential_ok("@example.com"))
        self.assertFalse(checks.shared_credential_ok("qa example.com"))


class SharedStatusVerdictTest(unittest.TestCase):
    def test_after_login_requires_authenticated(self):
        self.assertEqual(checks.shared_status_verdict(True, "after_login"), ("PASS", "none"))
        self.assertEqual(checks.shared_status_verdict(False, "after_login"),
                         ("FAIL", "shared_api_unauthenticated"))

    def test_after_logout_requires_unauthenticated(self):
        self.assertEqual(checks.shared_status_verdict(False, "after_logout"), ("PASS", "none"))
        self.assertEqual(checks.shared_status_verdict(True, "after_logout"),
                         ("FAIL", "logout_still_authenticated"))

    def test_unknown_stage_raises(self):
        with self.assertRaises(ValueError):
            checks.shared_status_verdict(True, "bogus")


class SharedLogoutVerdictTest(unittest.TestCase):
    def test_all_gone_passes(self):
        verdict, code, head = checks.shared_logout_verdict([])
        self.assertEqual((verdict, code, head), ("PASS", "none", ""))

    def test_unrelated_cookies_pass(self):
        verdict, code, head = checks.shared_logout_verdict(["__Host-padiem-shared-state"])
        self.assertEqual((verdict, code, head), ("PASS", "none", ""))

    def test_any_shared_residue_fails_with_names_only(self):
        for residue in ([ACCESS], [REFRESH], [MARKER], [ACCESS, REFRESH], [ACCESS, SESSION]):
            verdict, code, head = checks.shared_logout_verdict(residue)
            self.assertEqual(verdict, "FAIL", residue)
            self.assertEqual(code, "logout_residue", residue)
            self.assertTrue(head.startswith("remaining="), head)
            for name in residue:
                self.assertIn(name, head)

    def test_padiem_session_only_means_not_deployed(self):
        verdict, code, head = checks.shared_logout_verdict([SESSION])
        self.assertEqual((verdict, code, head), ("SKIPPED", "not_deployed", ""))

    def test_residue_list_includes_padiem_session_name(self):
        verdict, code, head = checks.shared_logout_verdict([REFRESH, SESSION])
        self.assertEqual((verdict, code), ("FAIL", "logout_residue"))
        self.assertIn(SESSION, head)
        self.assertIn(REFRESH, head)

    def test_head_carries_no_cookie_values(self):
        _, _, head = checks.shared_logout_verdict([ACCESS, "padiem_session"])
        self.assertNotIn("=", head.split("remaining=", 1)[1].replace(",", ""))


class SharedEndpointVerdictTest(unittest.TestCase):
    """#7364: shared login must resolve devices and the three workspace rows."""

    ROWS = checks.SHARED_GOOGLE_ROWS

    def _rows(self, states):
        return [
            {"connector_id": cid, "workspace_state": state}
            for cid, state in zip(self.ROWS, states)
        ]

    def test_verified_rows_pass(self):
        rows = self._rows(["connected", "not_connected", "ambiguous"])
        self.assertEqual(
            checks.shared_endpoint_verdict(200, rows),
            ("PASS", "none", "devices=200 rows=3"),
        )

    def test_an_unverified_row_fails(self):
        rows = self._rows(["connected", "unverified", "not_connected"])
        verdict, code, head = checks.shared_endpoint_verdict(200, rows)
        self.assertEqual((verdict, code), ("FAIL", "shared_connectors_unverified"))
        self.assertEqual(head, "devices=200 rows=3")

    def test_missing_rows_fail(self):
        verdict, code, _ = checks.shared_endpoint_verdict(200, [])
        self.assertEqual((verdict, code), ("FAIL", "shared_connector_rows_missing"))

    def test_devices_status_fails(self):
        verdict, code, head = checks.shared_endpoint_verdict(503, [])
        self.assertEqual((verdict, code), ("FAIL", "shared_devices_503"))
        self.assertEqual(head, "devices=503")

    def test_head_carries_no_identifiers(self):
        rows = self._rows(["connected", "connected", "connected"])
        _, _, head = checks.shared_endpoint_verdict(200, rows)
        for needle in self.ROWS:
            self.assertNotIn(needle, head)


class SharedLoginStep4CaptureTest(unittest.TestCase):
    """#7943 후속: 로그인된 Chat 화면 캡처가 튜토리얼 4단계 소스와 연결된다.

    흐름이 찍는 파일 이름(browser_shared_login_04_logged-in.png)이 일일 갱신
    매핑(CAPTURE_STEP_TO_SCENE)이 기다느 이름과 정확히 같아야 한다. 촬영
    실패는 새 FAIL 조건이 아니므로 흐름 판정에는 이 파일이 없어도 된다.
    """

    def test_step4_capture_file_name_matches_the_refresh_mapping(self):
        self.assertEqual(
            checks.artifact_filename("browser_shared_login", 4, "logged-in"),
            "browser_shared_login_04_logged-in.png",
        )

    def test_the_capture_call_is_wrapped_so_it_never_fails_the_flow(self):
        # 흐름 본문에서 4단계 촬영 호출은 자체 try/except 로 감싸져 있다.
        source = Path(checks.__file__).read_text(encoding="utf-8")
        call = '_capture(page, out_path, shared, 4, "logged-in", username)'
        self.assertIn(call, source)
        after = source[source.index(call):]
        self.assertIn("except Exception", after[:400])


if __name__ == "__main__":
    unittest.main()
