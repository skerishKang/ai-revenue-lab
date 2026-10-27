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

    def test_the_reported_line_carries_the_four_facts_and_no_content(self) -> None:
        self.assertEqual(
            canary.summary_line("PASS", entries=57, elapsed=212, code="none", pc_state="connected"),
            "CANARY=PASS items=57 elapsed_seconds=212 code=none pc_state=connected",
        )
        self.assertEqual(
            canary.summary_line("SKIP_NO_PC", entries=0, elapsed=0, code="no_active_pairing",
                               pc_state="unknown"),
            "CANARY=SKIP_NO_PC items=0 elapsed_seconds=0 code=no_active_pairing pc_state=unknown",
        )

    def test_the_wait_is_open_ended_and_spaces_reads_on_the_existing_cadence(self) -> None:
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn("POLL_INTERVAL_SECONDS = 2.0", source)
        self.assertIn("while True:", source)
        # No client-side give-up: no attempt count, no deadline, no wall-clock cap.
        for forbidden in ("max_attempts", "MAX_ATTEMPTS", "deadline =", "DEADLINE",
                          "max_wait", "MAX_WAIT", "timeout-minutes"):
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

    def test_it_measures_and_never_deploys_or_rolls_back(self) -> None:
        lowered = self.workflow.lower()
        for forbidden in ("rollback", "deploy_production_code", "allow_binding_removal",
                          "promote", "set_var", "delete_deployment"):
            self.assertNotIn(forbidden, lowered, forbidden)
        self.assertIn("PC_CONNECTOR_CANARY_MUTATIONS=NONE", self.workflow)
        # A FAIL reddens the run; nothing else acts on it.
        self.assertIn("continue-on-error: false", self.workflow)

    def test_it_uses_existing_authority_names_only_and_prints_one_line(self) -> None:
        self.assertIn("B66_CGI_ALPHA_USERNAME: ${{ vars.B66_CGI_ALPHA_USERNAME }}", self.workflow)
        self.assertIn("B66_CGI_ALPHA_PASSWORD: ${{ secrets.B66_CGI_ALPHA_PASSWORD }}", self.workflow)
        self.assertIn("environment: production", self.workflow)
        self.assertIn('tee -a "${GITHUB_STEP_SUMMARY}"', self.workflow)
        # The credential presence is tested by length, never echoed.
        self.assertIn('test -n "${B66_CGI_ALPHA_USERNAME}"', self.workflow)
        self.assertNotIn('echo "${B66_CGI_ALPHA_PASSWORD}', self.workflow)

    def test_two_hours_cannot_stack_and_the_runner_ceiling_is_the_only_end(self) -> None:
        self.assertIn("concurrency:", self.workflow)
        self.assertIn("group: pc-connector-canary", self.workflow)
        self.assertIn("cancel-in-progress: false", self.workflow)
        self.assertIn("timeout-minutes: 35", self.workflow)
        # The ceiling is documented as the runner's, not a product deadline.
        self.assertIn("RUNNER_JOB_CEILING_IS_NOT_A_PRODUCT_DEADLINE=YES", self.workflow)


if __name__ == "__main__":
    unittest.main()
