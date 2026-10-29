"""#5895: the PC connector canary's verdict table and its own boundaries.

Offline only. It runs the canary's pure functions and the shipped workflow text, so
what is proved here is the decision the scheduled job makes — never a live request.
"""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / ".github" / "scripts" / "pc_connector_canary.py"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "pc-connector-canary.yml"

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

    def test_no_paired_pc_is_not_a_failure(self) -> None:
        self.assertIsNone(canary.active_pairing({"ok": True, "links": []}))
        self.assertIsNone(canary.active_pairing({"ok": True, "links": [
            {"state": "paused", "roots": [{"state": "approved"}]},
        ]}))
        self.assertIsNone(canary.active_pairing({"ok": True, "links": [
            {"state": "active", "roots": []},
        ]}))
        self.assertIsNotNone(canary.active_pairing({"ok": True, "links": [
            {"state": "active", "roots": [{"state": "approved", "path": "C:\\"}]},
        ]}))

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
        self.assertEqual(
            set(canary.turn_payload(RUN_ID)), {"mode", "messages", "pc_run_id"},
        )
        self.assertEqual(canary.turn_payload(RUN_ID)["mode"], "auto")

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
        self.assertIn('QA_USERNAME_ENV = "B66_CGI_ALPHA_USERNAME"', source)
        self.assertIn('QA_PASSWORD_ENV = "B66_CGI_ALPHA_PASSWORD"', source)
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
            cwd=ROOT, capture_output=True, text=True, timeout=120,
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
        self.assertIn(b'"mode":"auto"', opener.sent[0])

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
        self.assertIn("PC_CONNECTOR_CANARY_MUTATIONS=NONE", self.workflow)
        # A FAIL reddens the run and is recorded as a commit status. Both are
        # GitHub-side: no production endpoint is written, no deployment is touched.
        self.assertIn("continue-on-error: false", self.workflow)
        self.assertIn("/statuses/${GITHUB_SHA}", self.workflow)
        # #82 standard 4: the verdict has to reach a person, not only a log file.
        self.assertIn('context="padiem/pc-connector-canary"', self.workflow)
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
        self.assertIn("B66_CGI_ALPHA_USERNAME: ${{ vars.B66_CGI_ALPHA_USERNAME }}", self.workflow)
        self.assertIn("B66_CGI_ALPHA_PASSWORD: ${{ secrets.B66_CGI_ALPHA_PASSWORD }}", self.workflow)
        self.assertIn("environment: production", self.workflow)
        self.assertIn('tee -a "${GITHUB_STEP_SUMMARY}"', self.workflow)
        # The credential presence is tested by length, never echoed.
        self.assertIn('test -n "${B66_CGI_ALPHA_USERNAME}"', self.workflow)
        self.assertNotIn('echo "${B66_CGI_ALPHA_PASSWORD}', self.workflow)


if __name__ == "__main__":
    unittest.main()
