"""#5895: the PC connector canary's verdict table and its own boundaries.

Offline only. It runs the canary's pure functions and the shipped workflow text, so
what is proved here is the decision the scheduled job makes — never a live request.
"""
from __future__ import annotations

import http.cookiejar
import os
import importlib.util
import pathlib
import re
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / ".github" / "scripts" / "pc_connector_canary.py"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "pc-connector-canary.yml"
STORE_PATH = ROOT / "apps" / "padiem-chat" / "app" / "pc_device_pairing_store.py"

spec = importlib.util.spec_from_file_location("pc_connector_canary", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
canary = importlib.util.module_from_spec(spec)
sys.modules["pc_connector_canary"] = canary
spec.loader.exec_module(canary)

RUN_ID = "chat_pcq_" + "a" * 32
CONVERSATION_ID = "chat_" + "c" * 32


def result(**fields: object) -> dict:
    return {"ok": True, "result": {"run_id": RUN_ID, "conversation_id": CONVERSATION_ID, **fields}}


class PcConnectorCanaryVerdictTests(unittest.TestCase):
    def test_a_verified_pc_result_is_the_only_pass(self) -> None:
        self.assertEqual(
            canary.pending_result_verdict(result(
                status="completed", answer_source="pc_command_result",
                answer="Applications\nWindows\nUsers\nProgram Files\n",
            )),
            ("PASS", "none", 4, "pc_command_result"),
        )
        self.assertEqual(
            canary.pending_result_verdict(result(
                status="completed", answer_source="pc_command_result", answer="   \n\n",
            ))[:2],
            ("FAIL", "pc_no_dispatch_result"),
        )

    def test_an_unfinished_run_is_a_wait_and_not_a_verdict(self) -> None:
        for status in ("pending", "running"):
            self.assertEqual(canary.pending_result_verdict(result(status=status))[0], "WAIT", status)

    def test_a_model_reply_or_a_dead_run_is_named_not_guessed(self) -> None:
        self.assertEqual(
            canary.pending_result_verdict(result(
                status="completed", answer_source="model_reply", answer="죄송하지만 PC에 연결할 수 없습니다.",
            ))[:2],
            ("FAIL", "pc_no_dispatch_result"),
        )
        self.assertEqual(
            canary.pending_result_verdict(result(status="failed"))[:2], ("FAIL", "pc_run_failed"),
        )
        self.assertEqual(
            canary.pending_result_verdict(result(status="cancelled"))[:2], ("FAIL", "pc_run_cancelled"),
        )
        self.assertEqual(
            canary.pending_result_verdict(result(status="something else"))[:2],
            ("FAIL", "pc_run_unknown_state"),
        )

    def test_no_paired_pc_is_reported_as_its_own_end(self) -> None:
        self.assertEqual(canary.active_pairing({"ok": True, "links": []}),
                         (None, canary.NO_ACTIVE_PAIRING))
        self.assertEqual(canary.active_pairing({"ok": True, "links": [
            {"state": "paused", "roots": [{"state": "active"}]},
        ]}), (None, canary.NO_ACTIVE_PAIRING))
        self.assertEqual(canary.active_pairing({"ok": True, "links": [
            {"state": "active", "roots": []},
        ]}), (None, canary.NO_ACTIVE_PAIRING))
        self.assertEqual(canary.active_pairing({"ok": True, "links": [
            {"state": "active", "roots": [{"state": "revoked"}]},
        ]}), (None, canary.NO_ACTIVE_PAIRING))
        self.assertEqual(canary.active_pairing({"ok": True, "links": [
            {"state": "active", "roots": [{"state": "active", "path": "C:\\"}]},
        ]})[1], "none")

    def test_an_unknown_state_word_never_becomes_a_quiet_skip(self) -> None:
        """A renamed or unexpected server word must surface, not hide.

        The 11-05 → 11-15 outage was exactly this shape: the pair test looked for a
        word the server never emitted and answered "nothing to test" every hour.
        """
        for body in (
            {"ok": True, "links": [{"state": "approved", "roots": [{"state": "active"}]}]},
            {"ok": True, "links": [{"state": "active", "roots": [{"state": "approved"}]}]},
            {"ok": True, "links": [{"state": "active"}]},
            {"ok": True},
            {"ok": True, "links": "not-a-list"},
            {"ok": True, "links": ["not-a-link"]},
        ):
            with self.subTest(body=body):
                self.assertEqual(canary.active_pairing(body),
                                 (None, canary.PAIRING_STATE_UNRECOGNIZED))

    def test_the_pairing_vocabulary_is_the_servers_own(self) -> None:
        """The mirrored words are pinned to the store that emits them.

        The canary cannot import the product store, so it mirrors the vocabulary.
        This test reads ``apps/padiem-chat/app/pc_device_pairing_store.py`` and fails
        as soon as the server renames a state, which is the only way the canary could
        drift back into a permanent "nothing to test".
        """
        store_source = STORE_PATH.read_text(encoding="utf-8")
        constants = dict(re.findall(r'^(_STATE_[A-Z_]+)\s*=\s*"([a-z_]+)"',
                                    store_source, re.M))
        self.assertEqual(constants.get("_STATE_ACTIVE"), canary.LINK_ACTIVE)
        self.assertEqual(constants.get("_STATE_REVOKED"), canary.LINK_REVOKED)
        self.assertEqual(
            constants.get("_STATE_REPLACED"), canary.LINK_REPLACED)
        self.assertEqual(
            constants.get("_STATE_PENDING_VERIFICATION"), canary.LINK_PENDING_VERIFICATION)
        # A granted root and an active link share the server's one granted word; the
        # browser projection also names a paused link, which the canary must know.
        self.assertEqual(canary.ROOT_GRANTED, canary.LINK_ACTIVE)
        self.assertEqual(canary.ROOT_REVOKED, canary.LINK_REVOKED)
        self.assertIn('state = "paused"', store_source.replace("'", '"'))
        self.assertEqual(canary.LINK_PAUSED, "paused")
        # Every word the store can emit is in the canary's known set.
        self.assertEqual(canary.KNOWN_LINK_STATES,
                         frozenset(constants.values()) | {canary.LINK_PAUSED})
        self.assertEqual(canary.KNOWN_ROOT_STATES,
                         frozenset({constants["_STATE_ACTIVE"], constants["_STATE_REVOKED"]}))

    def test_the_reported_line_carries_the_facts_and_no_content(self) -> None:
        self.assertEqual(
            canary.summary_line("PASS", entries=57, elapsed=212, code="none", pc_state="connected"),
            "CANARY=PASS items=57 elapsed_seconds=212 code=none pc_state=connected "
            "last_status=unknown",
        )
        self.assertEqual(
            canary.summary_line("SKIP_NO_PC", entries=0, elapsed=0, code="no_active_pairing",
                               pc_state="unknown"),
            "CANARY=SKIP_NO_PC items=0 elapsed_seconds=0 code=no_active_pairing "
            "pc_state=unknown last_status=unknown",
        )

    def test_the_monitor_waits_a_bounded_time_while_the_work_keeps_no_ceiling(self) -> None:
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn("POLL_INTERVAL_SECONDS = 2.0", source)
        self.assertIn("while True:", source)
        # #82 standard 4: a stop has to be known within ten minutes, so the
        # MONITOR's wait carries a bound. The bound is on this script's patience.
        self.assertEqual(canary.RESULT_WAIT_CEILING_SECONDS, 600)
        self.assertIn("RESULT_WAIT_CEILING_SECONDS = 600", source)
        # #5895 standard 1: nothing here may put a ceiling on the PC's own work. The
        # canary never cancels, shortens or times out the dispatch it started; the
        # bound below only ends this script's own waiting, and the result is still
        # accepted late by #6073 when it arrives.
        for forbidden in ("max_attempts", "MAX_ATTEMPTS", "deadline =", "max_wait",
                          "MAX_WAIT", "timeout_seconds"):
            self.assertNotIn(forbidden, source, forbidden)
        # The durable read is the #5983 path, addressed by the canonical PC run id.
        self.assertEqual(
            canary.PENDING_RESULT_PATH.format(run_id=RUN_ID),
            f"/api/claw/runs/{RUN_ID}/pending-result",
        )
        self.assertTrue(canary.PC_RUN_ID.fullmatch(canary.mint_pc_run_id()))
        # The turn is one composer POST with the run id the caller minted: nothing else.
        # `mode` left the request contract with the chat-mode remnant.
        self.assertEqual(
            set(canary.turn_payload(RUN_ID)), {"messages", "pc_run_id"},
        )
        self.assertNotIn("mode", canary.turn_payload(RUN_ID))

    def test_a_run_still_unfinished_at_the_bound_is_a_named_failure(self) -> None:
        """The 2026-10-29 miss, fixed: silence now ends with a verdict, not with the job.

        The server keeps calling the run ``running`` forever when the executor stops;
        the old wait accepted that and printed nothing. The bound turns it into a
        FAIL that names the status the server actually reported.
        """
        import unittest.mock as mock

        answers = iter([(200, result(status=s)) for s in ("pending",) * 400])
        with mock.patch.object(canary, "bounded_call",
                               lambda opener, path, **kwargs: next(answers)):
            outcome = canary.wait_for_result(
                object(), RUN_ID, started=0.0,
                clock=_clock_at(step=2.0), sleep=lambda _s: None,
            )
        self.assertEqual(outcome["verdict"], "FAIL")
        self.assertEqual(outcome["code"], "pc_result_wait_ceiling")
        self.assertGreaterEqual(outcome["elapsed_seconds"], 600)
        self.assertEqual(outcome["last_status"], "pending")

    def test_the_bound_ends_the_wait_and_an_answer_always_beats_it(self) -> None:
        """Boundary on both sides, because "10 minutes" is the number the standard names.

        At 600 s of unanswered waiting the script produces a verdict. An answer that
        arrives after a long wait still wins: the bound is on this script's patience,
        never on the PC's work, so the check runs only while the server itself says the
        run is unfinished.
        """
        import unittest.mock as mock

        def outcome(responses, step: float) -> dict:
            answers = iter(responses)
            with mock.patch.object(canary, "bounded_call",
                                   lambda opener, path, **kwargs: next(answers)):
                return canary.wait_for_result(
                    object(), RUN_ID, started=0.0,
                    clock=_clock_at(step=step), sleep=lambda _s: None,
                )

        at_the_bound = outcome([(200, result(status="running"))], step=600.0)
        self.assertEqual(at_the_bound["verdict"], "FAIL")
        self.assertEqual(at_the_bound["code"], "pc_result_wait_ceiling")
        self.assertEqual(at_the_bound["elapsed_seconds"], 600)

        just_under = outcome([(200, result(status="running")),
                              (200, result(status="completed",
                                            answer_source="pc_command_result",
                                            answer="A\n"))], step=599.0)
        self.assertEqual(just_under["verdict"], "PASS",
                         "a 599 s wait is patience, and the answer that follows wins")
        self.assertEqual(just_under["code"], "none")

    def test_an_answered_run_is_a_pass_even_at_the_bound(self) -> None:
        """The order matters: the answer is checked before the bound.

        A PC command that finishes exactly at the bound is not a failure, and a long
        answer that arrives inside it is not a failure either. The bound only fires
        while the server itself still calls the run unfinished.
        """
        import unittest.mock as mock

        answers = iter([
            (200, result(status="running")),
            (200, result(status="completed", answer_source="pc_command_result",
                         answer="A\nB\n")),
        ])
        with mock.patch.object(canary, "bounded_call",
                               lambda opener, path, **kwargs: next(answers)):
            outcome = canary.wait_for_result(
                object(), RUN_ID, started=0.0,
                clock=_clock_at(step=300.0), sleep=lambda _s: None,
            )
        self.assertEqual(outcome["verdict"], "PASS")
        self.assertEqual(outcome["code"], "none")
        self.assertEqual(outcome["elapsed_seconds"], 600)
        self.assertEqual(outcome["last_status"], "completed")

    def test_a_caller_that_names_no_bound_waits_as_long_as_the_server_is_unfinished(self) -> None:
        """The bound is this monitor's choice, not a rule the lane imposes.

        A caller that passes ``ceiling_seconds=None`` keeps the pre-#82 behaviour: the
        wait ends only on the server's own terminal status. Nothing in the product
        dispatch path inherits a ceiling from this script.
        """
        import unittest.mock as mock

        answers = iter([(200, result(status="running"))] * 3
                       + [(200, result(status="completed",
                                         answer_source="pc_command_result",
                                         answer="A\n"))])
        with mock.patch.object(canary, "bounded_call",
                               lambda opener, path, **kwargs: next(answers)):
            outcome = canary.wait_for_result(
                object(), RUN_ID, started=0.0, ceiling_seconds=None,
                clock=_clock_at(step=5_000.0), sleep=lambda _s: None,
            )
        self.assertEqual(outcome["verdict"], "PASS")
        self.assertEqual(outcome["elapsed_seconds"], 20_000)

    def test_the_last_status_comes_from_the_status_field_alone(self) -> None:
        # The rule the owner wrote after a hex id was misread out of log text: a
        # verdict reads a state field, never a substring of a body.
        self.assertEqual(canary.last_reported_status(result(status="paused")), "paused")
        self.assertEqual(canary.last_reported_status(
            {"result": {"status": "chat_pcq_" + "a" * 32}}), "unknown")
        self.assertEqual(canary.last_reported_status({"result": {"status": 7}}), "unknown")
        self.assertEqual(canary.last_reported_status({"error": {"code": "x"}}), "unknown")
        self.assertEqual(canary.last_reported_status(
            {"result": {"status": "completed", "answer": "C:\\Users\\padiem-정리.pdf"}}),
            "completed")

    def test_the_canary_reads_only_the_existing_authority_and_leaves_nothing_behind(self) -> None:
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        # The same QA identity the post-deploy chat smoke already signs in with.
        self.assertIn('QA_USERNAME_ENV = "QA_MANUAL_USERNAME"', source)
        self.assertIn('QA_PASSWORD_ENV = "QA_MANUAL_PASSWORD"', source)
        self.assertIn("from b62_live_long_context_canary import", source)
        # The same cleanup the smoke does.
        self.assertIn("bounded_call(opener, CONVERSATION + conversation_id, method=\"DELETE\")", source)
        # Never content, never a credential value.
        self.assertIn("PC_CANARY_ANSWER_TEXT_LOGGED=0", source)
        self.assertIn("CREDENTIAL_VALUES_LOGGED=0", source)
        self.assertNotIn("os.environ[QA_PASSWORD_ENV]", source)

    def test_self_test_agrees_with_these_expectations(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--self-test"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=120,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("PC_CONNECTOR_CANARY_SELF_TEST=PASS", completed.stdout)

    def test_the_wait_loops_until_the_server_calls_it_terminal(self) -> None:
        answers = iter([
            (200, result(status="pending")),
            (200, result(status="running")),
            (200, result(status="completed", answer_source="pc_command_result",
                         answer="A\nB\nC\n")),
        ])
        seen: list[str] = []
        slept: list[float] = []

        def fake_call(opener, path, **kwargs):
            seen.append(path)
            return next(answers)

        import unittest.mock as mock

        with mock.patch.object(canary, "bounded_call", fake_call):
            outcome = canary.wait_for_result(
                object(), RUN_ID, clock=_clock(100.0), sleep=slept.append,
            )
        self.assertEqual(outcome["verdict"], "PASS")
        self.assertEqual(outcome["entries"], 3)
        self.assertEqual(outcome["elapsed_seconds"], 6)
        self.assertEqual(seen, [f"/api/claw/runs/{RUN_ID}/pending-result"] * 3)
        self.assertEqual(slept, [canary.POLL_INTERVAL_SECONDS, canary.POLL_INTERVAL_SECONDS])

    def test_the_reported_time_covers_the_whole_turn_including_the_stream(self) -> None:
        import unittest.mock as mock

        answers = iter([(200, result(status="completed", answer_source="pc_command_result",
                                     answer="A\n"))])
        with mock.patch.object(canary, "bounded_call",
                               lambda opener, path, **kwargs: next(answers)):
            outcome = canary.wait_for_result(object(), RUN_ID, started=10.0,
                                            clock=lambda: 40.0, sleep=lambda _s: None)
        self.assertEqual(outcome["elapsed_seconds"], 30)

    def test_a_read_that_cannot_see_the_run_ends_the_wait_with_a_name(self) -> None:
        import unittest.mock as mock

        for status, expected in ((404, "pc_run_not_staged"), (503, "pc_result_unavailable"),
                                 (401, "pc_result_unauthorized")):
            with self.subTest(status=status), mock.patch.object(
                canary, "bounded_call",
                lambda opener, path, _status=status, **_kwargs: (_status, {
                    "error": {"code": "whatever_the_server_said"},
                }),
            ):
                outcome = canary.wait_for_result(object(), RUN_ID, clock=lambda: 0.0,
                                                 sleep=lambda _seconds: None)
            self.assertEqual(outcome["verdict"], "FAIL", status)
            self.assertEqual(outcome["code"], expected, status)


def _clock(start: float):
    """A clock that advances 2 seconds per read, so elapsed is checkable."""

    ticks = iter([start, start + 2.0, start + 4.0, start + 6.0])

    def read() -> float:
        return next(ticks)

    return read


def _clock_at(*, step: float):
    """A clock that reads `step`, `2 * step`, `3 * step`… — one step per poll.

    The wait reads the clock once per poll, so elapsed time is predictable: exactly
    one answer can be observed per step, and the first read already shows `step`.
    """

    ticks = iter(range(1, 10_000))

    def read() -> float:
        return next(ticks) * step

    return read


class _FakeResponse:
    """One iterable body: each item is exactly one wire line, as http.client yields."""

    def __init__(self, status: int, lines: list[bytes]) -> None:
        self.status = status
        self._lines = iter(lines)

    def __enter__(self):
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False

    def __iter__(self):
        return self._lines


class _FakeOpener:
    def __init__(self, response) -> None:
        self.response = response
        self.sent: list[bytes] = []

    def open(self, request, timeout=None):
        self.sent.append(request.data)
        return self.response


def sse(*frames: tuple[str, str]) -> list[bytes]:
    """(event, json) pairs as the separate lines the real stream sends."""

    lines: list[bytes] = []
    for event, body in frames:
        lines.append(f"event: {event}\n".encode())
        lines.append(f"data: {body}\n".encode())
        lines.append(b"\n")
    return lines


class PcConnectorCanaryStreamTests(unittest.TestCase):
    def test_the_terminal_frame_names_the_turn_without_reading_its_content(self) -> None:
        opener = _FakeOpener(_FakeResponse(200, sse(
            ("delta", '{"delta":"C:\\\\Applications"}'),
            ("scope_notice", '{"scope_notice":"pinned"}'),
            ("done", '{"done":true,"pc_pending":true,'
                     f'"run_id":"{RUN_ID}","conversation_id":"{CONVERSATION_ID}"}}'),
        )))
        outcome = canary.read_pc_turn_stream(opener, canary.turn_payload(RUN_ID))
        self.assertEqual(outcome["status"], 200)
        self.assertTrue(outcome["done"])
        self.assertTrue(outcome["pc_pending"])
        self.assertEqual(outcome["conversation_id"], CONVERSATION_ID)
        self.assertEqual(outcome["error_code"], "none")
        self.assertIn(b'"pc_run_id":"' + RUN_ID.encode() + b'"', opener.sent[0])
        # `mode` left the request contract with the chat-mode remnant; a canary that
        # still sent it would be refused as an unknown key.
        self.assertNotIn(b'"mode"', opener.sent[0])

    def test_a_refusal_frame_is_named_and_the_conversation_is_still_found(self) -> None:
        opener = _FakeOpener(_FakeResponse(200, sse(
            ("error", '{"error":{"code":"tier_not_available"},'
                      f'"conversation_id":"{CONVERSATION_ID}"}}'),
        )))
        outcome = canary.read_pc_turn_stream(opener, canary.turn_payload(RUN_ID))
        self.assertEqual(outcome["error_code"], "tier_not_available")
        self.assertEqual(outcome["conversation_id"], CONVERSATION_ID)
        self.assertFalse(outcome["done"])

    def test_a_json_answer_with_no_frame_is_the_lane_not_being_offered(self) -> None:
        opener = _FakeOpener(_FakeResponse(200, [
            b'{"orchestration":{},"answer":"\xec\xa0\x95\xec\x9e\x85","conversation_id":"'
            + CONVERSATION_ID.encode() + b'"}\n',
        ]))
        outcome = canary.read_pc_turn_stream(opener, canary.turn_payload(RUN_ID))
        self.assertEqual(outcome["status"], 200)
        self.assertFalse(outcome["framed"])
        self.assertFalse(outcome["done"])
        self.assertFalse(outcome["stream_stopped"])
        self.assertEqual(outcome["conversation_id"], CONVERSATION_ID)

    def test_a_stream_that_never_terminates_is_not_a_verdict(self) -> None:
        opener = _FakeOpener(_FakeResponse(200, sse(("delta", '{"delta":"x"}'))))
        outcome = canary.read_pc_turn_stream(opener, canary.turn_payload(RUN_ID))
        self.assertFalse(outcome["done"])
        self.assertTrue(outcome["framed"])
        self.assertFalse(outcome["stream_stopped"])


class PcConnectorCanarySignInTests(unittest.TestCase):
    """The 2026-11-13 refusal, fixed: sign-in rides the existing common login.

    Since the #7078 step-3 switch moved email login, the old direct-only POST
    was answered 409 ``email_login_moved`` and the canary never reached the PC
    check. The fix reuses the same helper the USAGE_CHECK flows sign in with
    (``shared_login_client.login_session_cookie``): direct first, common login
    on 409. No new login method is introduced here.
    """

    def test_sign_in_reuses_the_shared_login_helper_and_not_a_new_method(self) -> None:
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn("from shared_login_client import", source)
        self.assertIn("login_session_cookie(ORIGIN, username, password)", source)
        # The old direct-only login POST is gone; the helper owns the
        # direct-then-common-login order itself.
        self.assertNotIn("    LOGIN,\n", source)
        self.assertNotIn("opener, LOGIN", source)

    def test_a_signed_in_session_cookie_reaches_the_canary_jar(self) -> None:
        import http.cookiejar
        import unittest.mock as mock

        jar = http.cookiejar.CookieJar()
        status_reads: list[str] = []

        def fake_call(_opener, path, **_kwargs):
            status_reads.append(path)
            return 200, {"authenticated": True}

        env = {
            canary.QA_USERNAME_ENV: "qa@example.invalid",
            canary.QA_PASSWORD_ENV: "stub-password-not-a-real-value",
        }
        with mock.patch.dict(os.environ, env), mock.patch.object(
            canary, "login_session_cookie", lambda *a, **k: "stub-session-value",
        ), mock.patch.object(canary, "bounded_call", fake_call):
            canary.sign_in(object(), jar)
        self.assertEqual(status_reads, [canary.STATUS])
        request = canary.Request(canary.ORIGIN + canary.STATUS)
        jar.add_cookie_header(request)
        carried = request.get_header("Cookie") or ""
        self.assertIn(canary.SESSION_COOKIE_NAME + "=stub-session-value", carried)

    def test_a_common_login_refusal_is_a_named_failure(self) -> None:
        import unittest.mock as mock

        env = {
            canary.QA_USERNAME_ENV: "qa@example.invalid",
            canary.QA_PASSWORD_ENV: "stub-password-not-a-real-value",
        }
        with mock.patch.dict(os.environ, env), mock.patch.object(
            canary, "login_session_cookie",
            mock.Mock(side_effect=canary.SharedLoginError("shared_login_refused_http_429")),
        ):
            with self.assertRaises(canary.CanaryError) as caught:
                canary.sign_in(object(), http.cookiejar.CookieJar())
        self.assertEqual(caught.exception.public_code, "qa_login_refused")

    def test_missing_credentials_are_refused_before_any_request(self) -> None:
        import unittest.mock as mock

        with mock.patch.dict(os.environ, {canary.QA_USERNAME_ENV: "", canary.QA_PASSWORD_ENV: ""}):
            with self.assertRaises(canary.CanaryError) as caught:
                canary.sign_in(object(), http.cookiejar.CookieJar())
        self.assertEqual(caught.exception.public_code, "qa_credential_missing")


class PcConnectorCanaryRunPathTests(unittest.TestCase):
    """Where one run goes: a live pairing, no pairing, or a word it cannot read.

    These drive ``run()`` itself so the routing is proved, not only the pure pair
    test: an active pairing must reach the PC turn, no pairing must end as the
    non-zero SKIP, and an unrecognised state word must end as a named FAIL.
    """

    def _run(self, pairings: dict, *, devices: dict | None = None,
             select: dict | None = None,
             closed_lane: str | None = None,
             no_run: bool | None = None,
             text_answer: bool = False) -> tuple[int, str]:
        import contextlib
        import io
        import unittest.mock as mock

        calls: list[str] = []

        def fake_call(_opener, path, **_kwargs):
            calls.append(path)
            if path == canary.PAIRINGS:
                return 200, pairings
            if path == canary.DEVICE_SELECT:
                calls.append("select_saved")
                return 200, select or {"ok": True, "selectedDeviceId": "pc_test"}
            if path == canary.DEVICES:
                return 200, devices or {"ok": True, "available": True, "devices": [
                    {"deviceId": "pc_test", "usable": True, "state": "CONNECTED"},
                ]}
            if path.startswith("/api/claw/runs/"):
                absent = (closed_lane is not None) if no_run is None else no_run
                if absent:
                    # No dispatch happened on that turn, so no run row exists for the
                    # id this turn minted: the public read cannot see it.
                    return 404, {"ok": False, "error": {"code": "run_not_found"}}
                return 200, result(status="completed", answer_source="pc_command_result",
                                   answer="Windows\nUsers\n")
            return 200, {}

        def fake_stream(_opener, payload):
            calls.append("pc_turn")
            calls.append("device_id=" + str(payload.get("device_id")))
            outcome = canary.new_answer_outcome()
            outcome["status"] = 200
            outcome["conversation_id"] = CONVERSATION_ID
            if closed_lane is not None:
                # The operating lane answered in text: one whole JSON body, no frame.
                outcome["pc_lane_closed"] = closed_lane
                return outcome
            if text_answer:
                # A text answer whose stream shape this canary must not judge by.
                return outcome
            # The screen's lane: a tool frame, then the terminal frame.
            outcome["ndjson"] = True
            outcome["tool_frames"] = 2
            outcome["done"] = True
            outcome["pc_pending"] = True
            outcome["framed"] = True
            return outcome

        buffer = io.StringIO()
        env = {canary.QA_USERNAME_ENV: "qa@example.invalid",
               canary.QA_PASSWORD_ENV: "stub-password-not-a-real-value"}
        with mock.patch.dict(os.environ, env), mock.patch.object(
            canary, "sign_in", lambda *a, **k: None,
        ), mock.patch.object(
            canary, "bounded_call", fake_call,
        ), mock.patch.object(
            canary, "read_pc_turn_stream", fake_stream,
        ), contextlib.redirect_stdout(buffer):
            code = canary.run()
        return code, buffer.getvalue() + " calls=" + ",".join(calls)

    def test_an_active_pairing_reaches_the_pc_turn(self) -> None:
        code, output = self._run({"ok": True, "links": [
            {"state": "active", "roots": [{"state": "active", "path": "C:\\"}]},
        ]})
        self.assertIn("pc_turn", output)
        # 2026-11-16: the turn names the PC it verified. Without the id the server
        # keeps the plain stream and the run ends as pc_lane_not_offered.
        self.assertIn("device_id=pc_test", output)
        self.assertIn("CANARY=PASS", output)
        self.assertEqual(code, 0)
        # 2026-11-16 (#7826): the account keeps no browser, so the PC it asks is
        # saved through the screen's own save before the turn. Same value every run.
        self.assertIn("select_saved", output)
        self.assertIn("device_selection=saved", output)

    def test_a_saved_choice_is_not_written_again(self) -> None:
        code, output = self._run(
            {"ok": True, "links": [
                {"state": "active", "roots": [{"state": "active", "path": "C:\\"}]},
            ]},
            devices={"ok": True, "available": True, "selectedDeviceId": "pc_test",
                     "devices": [{"deviceId": "pc_test", "usable": True,
                                  "state": "CONNECTED"}]},
        )
        self.assertNotIn("select_saved", output)
        self.assertIn("device_selection=already_saved", output)
        self.assertIn("CANARY=PASS", output)
        self.assertEqual(code, 0)

    def test_a_closed_lane_reason_is_printed_when_the_server_sends_one(self) -> None:
        # #7826: the canary interprets nothing; it repeats the server's own word
        # when the answer carries one, and says nothing when it does not.
        code, output = self._run(
            {"ok": True, "links": [
                {"state": "active", "roots": [{"state": "active", "path": "C:\\"}]},
            ]},
            closed_lane="turn_names_no_pc",
        )
        self.assertIn("PC_CANARY_PC_LANE_CLOSED=turn_names_no_pc", output)
        self.assertIn("code=pc_lane_not_offered", output)
        self.assertEqual(code, 1)

    def test_no_closed_lane_reason_is_invented(self) -> None:
        code, output = self._run(
            {"ok": True, "links": [
                {"state": "active", "roots": [{"state": "active", "path": "C:\\"}]},
            ]},
            closed_lane="",
        )
        self.assertNotIn("PC_CANARY_PC_LANE_CLOSED", output)
        self.assertEqual(code, 1)

    def test_a_text_answer_is_judged_by_the_durable_read(self) -> None:
        # 2026-11-16 (#7836): the operating lane answers in text when the model
        # selects no tool, and it still dispatches a PC run when it does. A stream
        # frame is therefore no longer the verdict: the run's own public row is.
        code, output = self._run(
            {"ok": True, "links": [
                {"state": "active", "roots": [{"state": "active", "path": "C:\\"}]},
            ]},
            text_answer=True,
            no_run=False,
        )
        self.assertIn("CANARY=PASS", output)
        self.assertIn("PC_CANARY_TOOL_FRAMES=0", output)
        self.assertEqual(code, 0)

    def test_a_text_answer_with_no_run_row_is_the_lane_name(self) -> None:
        # No run for the id this turn minted means no PC tool ran; the reporting
        # name stays the one this canary has always used.
        code, output = self._run(
            {"ok": True, "links": [
                {"state": "active", "roots": [{"state": "active", "path": "C:\\"}]},
            ]},
            text_answer=True,
            no_run=True,
        )
        self.assertIn("code=" + canary.PC_LANE_NOT_OFFERED, output)
        self.assertEqual(code, 1)

    def test_a_save_the_server_refuses_is_a_named_failure(self) -> None:
        code, output = self._run(
            {"ok": True, "links": [
                {"state": "active", "roots": [{"state": "active", "path": "C:\\"}]},
            ]},
            select={"ok": False, "error": {"code": "pc_selection_not_online"}},
        )
        self.assertIn("code=" + canary.DEVICE_SELECT_UNSAVED, output)
        self.assertNotIn("pc_turn", output)
        self.assertEqual(code, 1)

    def test_a_pairing_without_a_connected_pc_is_a_named_failure(self) -> None:
        code, output = self._run(
            {"ok": True, "links": [
                {"state": "active", "roots": [{"state": "active", "path": "C:\\"}]},
            ]},
            devices={"ok": True, "available": True, "devices": [
                {"deviceId": "pc_test", "usable": False, "state": "OFFLINE"},
            ]},
        )
        self.assertIn("code=" + canary.NO_USABLE_DEVICE, output)
        self.assertNotIn("pc_turn", output)
        self.assertEqual(code, 1)

    def test_no_pairing_ends_as_a_non_zero_skip_not_a_silent_success(self) -> None:
        code, output = self._run({"ok": True, "links": []})
        self.assertIn("CANARY=SKIP_NO_PC", output)
        self.assertIn("code=" + canary.NO_ACTIVE_PAIRING, output)
        self.assertIn("PC_CANARY_SKIP_IS_A_WARNING=1", output)
        self.assertNotIn("pc_turn", output)
        self.assertEqual(code, canary.EXIT_SKIP_NO_PC)
        self.assertNotEqual(code, 0)

    def test_an_unreadable_pairing_read_is_a_named_failure(self) -> None:
        code, output = self._run({"ok": True, "links": [
            {"state": "approved", "roots": [{"state": "active"}]},
        ]})
        self.assertIn("CANARY=FAIL", output)
        self.assertIn("code=" + canary.PAIRING_STATE_UNRECOGNIZED, output)
        self.assertNotIn("pc_turn", output)
        self.assertEqual(code, 1)


class PcConnectorCanaryWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_it_runs_hourly_and_by_hand_and_never_on_a_pull(self) -> None:
        self.assertIn("schedule:", self.workflow)
        self.assertIn("cron: '7 * * * *'", self.workflow)
        self.assertIn("workflow_dispatch:", self.workflow)
        # A pull request may check the contract but never calls production.
        live_guard = "github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'"
        self.assertIn(live_guard, self.workflow)

    def test_it_measures_the_lane_and_records_only_a_status(self) -> None:
        lowered = self.workflow.lower()
        for forbidden in ("rollback", "deploy_production_code", "allow_binding_removal",
                          "promote", "set_var", "delete_deployment"):
            self.assertNotIn(forbidden, lowered, forbidden)
        self.assertIn(
            "PC_CONNECTOR_CANARY_MUTATIONS=NONE_EXCEPT_OWNER_PC_SELECTION_PREFERENCE",
            self.workflow)
        # A FAIL reddens the run and is recorded as a commit status. Both are
        # GitHub-side: no production endpoint is written, no deployment is touched.
        self.assertIn("continue-on-error: false", self.workflow)
        self.assertIn("/statuses/${GITHUB_SHA}", self.workflow)
        # 2026-11-16: "measured nothing" is recorded as a failure, not as neutral.
        # Ten green hours with no PC check (11-05 → 11-15) were the reason.
        self.assertIn('SKIP_NO_PC) state="failure"; ;;', self.workflow)
        self.assertNotIn('state="neutral"', self.workflow)
        # The live job is still gated off pull requests: only the offline contract
        # job runs there, so a PR can never call production.
        self.assertIn("if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'",
                      self.workflow)
        # #82 standard 4: the verdict has to reach a person, not only a log file.
        self.assertIn('context="padiem/pc-connector-canary"', self.workflow)
        # 2026-11-16: publishing that status needs the scope on the live job. Run
        # 43862546352 lost its verdict to "Resource not accessible by
        # integration" because the job token held `contents: read` only.
        self.assertIn("statuses: write", self.workflow)
        # Event data reaches the shell as a quoted variable, never inline.
        self.assertIn("GITHUB_REPOSITORY: ${{ github.repository }}", self.workflow)
        self.assertNotIn("repos/${{ github.repository }}", self.workflow)

    def test_two_hours_cannot_stack_and_the_two_bounds_are_separate(self) -> None:
        self.assertIn("concurrency:", self.workflow)
        self.assertIn("group: pc-connector-canary", self.workflow)
        self.assertIn("cancel-in-progress: false", self.workflow)
        # Two ceilings, deliberately different numbers. The script ends its own wait at
        # 600 s and prints a verdict (#82 standard 4); the runner's 35-minute job
        # ceiling stays as the outer guard and must never be the thing that ends the
        # wait first, because a job killed by the runner records nothing.
        self.assertIn("timeout-minutes: 35", self.workflow)
        self.assertIn("RUNNER_JOB_CEILING_IS_NOT_A_PRODUCT_DEADLINE=YES", self.workflow)
        self.assertIn("RESULT_WAIT_CEILING_SECONDS = 600",
                       SCRIPT_PATH.read_text(encoding="utf-8"))

    def test_it_uses_existing_authority_names_only_and_prints_one_line(self) -> None:
        # 2026-11-11 QA purpose split: the identifier is an email, so both the
        # username and the password ride GitHub secrets — never a public var.
        self.assertIn("QA_MANUAL_USERNAME: ${{ secrets.PC_CANARY_QA_USERNAME }}", self.workflow)
        self.assertIn("QA_MANUAL_PASSWORD: ${{ secrets.PC_CANARY_QA_PASSWORD }}", self.workflow)
        self.assertIn("environment: production", self.workflow)
        self.assertIn('tee -a "${GITHUB_STEP_SUMMARY}"', self.workflow)
        # The credential presence is tested by length, never echoed.
        self.assertIn('test -n "${QA_MANUAL_USERNAME}"', self.workflow)
        self.assertNotIn('echo "${QA_MANUAL_PASSWORD}', self.workflow)


if __name__ == "__main__":
    unittest.main()
