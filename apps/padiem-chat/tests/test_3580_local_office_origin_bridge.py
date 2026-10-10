"""#3580: owner/run/correlation-gated Local Runner Office completion, no real Drive.

Actual SQLite migration 020 + 026, existing approved uploader with fake provider.
No browser or model-supplied reference can choose the conversation or authorize
WRITE. Broker terminal exit=0 alone never attests document material.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import unittest

from app.claw_durable_drive_output_pipeline import DurableArtifactCompletionError
from app.claw_local_office_origin_bridge import LocalOfficeOriginBridge
from app.claw_local_task_result_composition import LocalRunnerResultSource
from app.claw_local_task_result_projection import LocalRunnerTerminalObservation
from test_3929_claw_conversation_artifact_d1 import (
    OWNER, FOREIGN, RUN, MIGRATIONS,
)
import test_3933_office_drive_completion as office

CORR = {
    "command_id": "cmd_office_3580",
    "tool_request_ref": "tool_office_3580",
    "request_id": "request_office_3580",
    "revision_ref": "revision_office_3580",
    "evidence_ref": "evidence_office_3580",
    "request_fingerprint": "a" * 64,
}


class FakeCanonicalBroker:
    def __init__(self):
        self.calls = 0
        self.fail = False
        self.fact = LocalRunnerTerminalObservation(
            **CORR, run_id=RUN, sequence=1,
            state="acknowledged", termination="exited", exit_code=0,
            acknowledged_at="2026-10-10T10:00:00Z",
        )

    async def command_result(
        self, *, command_id, run_id, owner_id, workspace_id,
    ):
        self.calls += 1
        if self.fail:
            raise RuntimeError("secret broker detail must not escape")
        assert (command_id, run_id, owner_id, workspace_id) == (
            CORR["command_id"], RUN, OWNER, office.WORKSPACE,
        )
        return self.fact


class LocalOfficeOriginTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Reuse the same proven XLSX/PDF, Drive-upload, and D1-index fixtures
        # rather than fabricating a parallel Office upload implementation.
        self.fixture = office.OfficeDriveCompletionTests(
            methodName="test_actual_canonical_xlsx_pdf_both_registered_after_approved_upload"
        )
        self.fixture.setUp()
        self.fixture.db.executescript(
            (MIGRATIONS / "020_claw_local_task_correlation.sql").read_text(encoding="utf8")
        )
        await self.fixture.history.record_local_task_correlation(
            user_id=OWNER, run_id=RUN, **CORR,
        )
        self.broker = FakeCanonicalBroker()
        self.bridge = LocalOfficeOriginBridge(
            history=self.fixture.history, terminal_port=self.broker,
            completion=self.fixture.completion,
        )

    async def asyncTearDown(self):
        self.fixture.tearDown()

    def kwargs(self, **kw):
        values = dict(
            owner_id=OWNER, run_ref=RUN,
            outputs=self.fixture.outputs,
            xlsx_intent=self.fixture.xlsx_intent,
            pdf_intent=self.fixture.pdf_intent,
            now=office.NOW,
        )
        values.update(kw)
        return values

    async def test_successful_exact_broker_run_uploads_two_authorized_files(self):
        result = await self.bridge.complete_approved_office_run(**self.kwargs())
        self.assertTrue(result.public_projection()["both_indexed"])
        self.assertEqual(self.broker.calls, 1)
        self.assertEqual(self.fixture.provider.calls, 2)
        self.assertEqual(
            self.fixture.db.execute(
                "SELECT count(*) FROM claw_conversation_artifact_index"
            ).fetchone()[0], 2,
        )

    async def test_local_runner_source_exposes_only_explicit_trusted_completion(self):
        no_writer = LocalRunnerResultSource(
            history=self.fixture.history, result_port=self.broker,
        )
        with self.assertRaisesRegex(DurableArtifactCompletionError, "unavailable"):
            await no_writer.complete_approved_office_run(**self.kwargs())
        self.assertEqual(self.broker.calls, 0)
        wired = LocalRunnerResultSource(
            history=self.fixture.history, result_port=self.broker,
            office_completion=self.fixture.completion,
        )
        response = await wired.complete_approved_office_run(**self.kwargs())
        self.assertTrue(response.public_projection()["both_indexed"])
        self.assertEqual(self.fixture.provider.calls, 2)

    async def test_foreign_owner_and_wrong_run_ref_fail_before_broker(self):
        for kw in ({"owner_id": FOREIGN}, {"run_ref": "run_unrelated_3580"}):
            with self.subTest(kw=kw):
                with self.assertRaises(DurableArtifactCompletionError):
                    await self.bridge.complete_approved_office_run(**self.kwargs(**kw))
        self.assertEqual(self.broker.calls, 0)
        self.assertEqual(self.fixture.provider.calls, 0)

    async def test_uncompleted_run_fails_even_if_broker_reports_success(self):
        self.fixture.db.execute(
            "UPDATE claw_run_history SET status='waiting_approval' WHERE run_id=?",
            (RUN,),
        )
        with self.assertRaises(DurableArtifactCompletionError):
            await self.bridge.complete_approved_office_run(**self.kwargs())
        self.assertEqual(self.broker.calls, 0)
        self.assertEqual(self.fixture.provider.calls, 0)

    async def test_terminal_fact_mismatch_or_failure_denies_all_writes(self):
        valid = self.broker.fact
        variants = (
            replace(valid, exit_code=1),
            replace(valid, termination="timed_out", exit_code=None),
            replace(valid, state="expired", termination=None, exit_code=None),
            replace(valid, request_fingerprint="b" * 64),
            replace(valid, command_id="other_command_3580"),
            None,
        )
        for candidate in variants:
            with self.subTest(candidate=candidate):
                self.broker.fact = candidate
                with self.assertRaises(DurableArtifactCompletionError):
                    await self.bridge.complete_approved_office_run(**self.kwargs())
        self.assertEqual(self.fixture.provider.calls, 0)

    async def test_broker_exception_never_surfaces_private_text(self):
        self.broker.fail = True
        with self.assertRaises(DurableArtifactCompletionError) as raised:
            await self.bridge.complete_approved_office_run(**self.kwargs())
        self.assertNotIn("secret broker detail", str(raised.exception))
        self.assertEqual(self.fixture.provider.calls, 0)

    async def test_office_bytes_must_still_match_after_successful_broker(self):
        tampered = replace(
            self.fixture.outputs,
            revised_bytes=self.fixture.outputs.revised_bytes + b"tampered"
        )
        with self.assertRaises(DurableArtifactCompletionError):
            await self.bridge.complete_approved_office_run(
                **self.kwargs(outputs=tampered)
            )
        self.assertEqual(self.broker.calls, 1)
        self.assertEqual(self.fixture.provider.calls, 0)


if __name__ == "__main__":
    unittest.main()
