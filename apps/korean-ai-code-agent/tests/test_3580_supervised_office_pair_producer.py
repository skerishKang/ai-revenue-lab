"""#3580 real resident-approved XLSX READ -> PDF material -> Broker post-ACK.

The genuine selected-root capture and canonical Office material composition run,
using an injected fake file runtime/Excel child so customer files are untouched.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import os
import subprocess
import unittest
from unittest.mock import patch

from kagent.approved_windows_office_pair_producer import (
    ApprovedWindowsOfficePairProducer, compose_approved_windows_office_pairs,
)
from kagent.contracts import ContractError
from kagent.local_agent_runtime_host import InMemorySingleInstanceLock
from kagent.supervised_windows_excel_pdf import SupervisedWindowsExcelPdfRenderer
from kagent.windows_local_filesystem import (
    WindowsSelectedRootFileRuntime, LocalFileRequest, LocalFileOperation,
    LocalFileResult,
)
from test_3580_resident_office_post_ack_delivery import (
    _harness, pair_for_host, staging, XLSX, PDF,
)


class AuthorizedFileRuntime(WindowsSelectedRootFileRuntime):
    """Test adapter. Real runtime checks P01 grant, selected root and symlinks."""

    def __init__(self, *, content=XLSX, deny=False):
        self.content = content
        self.deny = deny
        self.calls = []

    def perform(self, request, *, now):
        self.calls.append((request, now))
        if self.deny:
            raise ContractError("P01 READ permission revoked")
        return LocalFileResult(
            action_id=request.action_id, run_id=request.run_id,
            device_id=request.device_id, root_ref=request.root_ref,
            operation=LocalFileOperation.READ,
            path_relative=request.path_relative,
            completed_at=now, bytes_count=len(self.content),
            content_sha256=sha256(self.content).hexdigest(), content=self.content,
        )


class Plan:
    def __init__(self, *, allowed=True, wrong_run=False, wrong_device=False):
        self.allowed = allowed
        self.wrong_run = wrong_run
        self.wrong_device = wrong_device
        self.calls = 0

    def request_for_completed_command(self, *, binding, command, receipt):
        self.calls += 1
        if not self.allowed:
            return None
        return LocalFileRequest(
            action_id="approved_read_quote_3580",
            run_id="other_run" if self.wrong_run else command.run_id,
            device_id="other_device" if self.wrong_device else binding.device_id,
            root_ref="root_repo", operation=LocalFileOperation.READ,
            path_relative=r"reports\quote.xlsx",
            requested_at=receipt.acknowledged_at,
        )


class FakeExcelRenderer:
    def __init__(self):
        self.calls = []
    def render_xlsx_pdf(self, source_bytes):
        self.calls.append(source_bytes)
        return PDF


class FakeJob:
    def __init__(self):
        self.terminated = False
        self.closed = False
    def terminate_tree(self):
        self.terminated = True
    def close(self):
        self.closed = True


class FakeProcess:
    def __init__(self, *, timeout=False, bad_exit=False):
        self.timeout = timeout
        self.returncode = 1 if bad_exit else 0
        self.waited = False
    def communicate(self, *, timeout):
        if self.timeout:
            raise subprocess.TimeoutExpired(cmd="Excel", timeout=timeout)
        return "", ""
    def poll(self):
        return self.returncode
    def wait(self, *, timeout):
        self.waited = True


class FakeLauncher:
    def __init__(self, *, timeout=False, bad_exit=False):
        self.timeout = timeout
        self.bad_exit = bad_exit
        self.calls = []
        self.jobs = []
    def __call__(self, argv, *, cwd, environment):
        self.calls.append((argv, cwd, environment))
        job = FakeJob()
        self.jobs.append(job)
        if not self.timeout and not self.bad_exit:
            Path(argv[-1]).write_bytes(PDF)
        return type("Bound", (), {
            "job": job, "process": FakeProcess(
                timeout=self.timeout, bad_exit=self.bad_exit
            ),
        })()


class SupervisedOfficeProducerTests(unittest.TestCase):
    def setUp(self):
        InMemorySingleInstanceLock.reset()
    def tearDown(self):
        InMemorySingleInstanceLock.reset()

    def run_resident(self, *, plan=None, files=None):
        host, runtime, port, clock = _harness()
        plans = plan if plan is not None else Plan()
        files = files if files is not None else AuthorizedFileRuntime()
        renderer = FakeExcelRenderer()
        producer = ApprovedWindowsOfficePairProducer(
            files=files, requests=plans, renderer=renderer, clock=clock,
        )
        stage, _, tls = staging(broker=port.broker_authority, pair=None)
        stage._approved_pairs = producer
        host._office_staging = stage
        host.start()
        clock.advance(5)
        count = host.run_once(now=clock.now)
        host.stop()
        return count, runtime, plans, files, renderer, tls, port

    def test_real_resident_full_read_render_and_two_binary_uploads(self):
        count, runtime, plan, files, renderer, tls, broker = self.run_resident()
        self.assertEqual(count, 1)
        self.assertEqual(runtime.executed, ["req_host_1"])
        self.assertEqual(plan.calls, 1)
        self.assertEqual(len(files.calls), 1)
        self.assertEqual(renderer.calls, [XLSX])
        self.assertEqual([v["kind"] for v in tls.calls], ["xlsx", "pdf"])
        self.assertEqual(tls.calls[0]["integrity_ref"], sha256(XLSX).hexdigest())
        self.assertEqual(tls.calls[1]["integrity_ref"], sha256(PDF).hexdigest())
        self.assertEqual(broker.broker_authority._commands["cmd_host_1"].state.value,
                         "acknowledged")

    def test_non_office_receipt_never_reads_or_exports(self):
        _, _, _, files, renderer, tls, _ = self.run_resident(
            plan=Plan(allowed=False)
        )
        self.assertEqual(files.calls, [])
        self.assertEqual(renderer.calls, [])
        self.assertEqual(tls.calls, [])

    def test_wrong_run_or_device_refuses_before_selected_root_read(self):
        for plan in (Plan(wrong_run=True), Plan(wrong_device=True)):
            with self.subTest(plan=plan):
                _, _, _, files, renderer, tls, _ = self.run_resident(plan=plan)
                self.assertEqual(files.calls, [])
                self.assertEqual(renderer.calls, [])
                self.assertEqual(tls.calls, [])
                InMemorySingleInstanceLock.reset()

    def test_revoked_read_grant_denies_excel_and_broker_transfer(self):
        _, _, _, files, renderer, tls, _ = self.run_resident(
            files=AuthorizedFileRuntime(deny=True),
        )
        self.assertEqual(len(files.calls), 1)
        self.assertEqual(renderer.calls, [])
        self.assertEqual(tls.calls, [])

    def test_original_hash_mismatch_denies_export_or_send(self):
        _, _, _, files, renderer, tls, _ = self.run_resident(
            files=AuthorizedFileRuntime(content=b"not a valid XLSX"),
        )
        self.assertEqual(len(files.calls), 1)
        self.assertEqual(renderer.calls, [])
        self.assertEqual(tls.calls, [])

    def test_supervised_child_validates_source_and_has_bounded_shutdown(self):
        if os.name != "nt":
            self.skipTest("Windows-only isolated Excel child")
        launcher = FakeLauncher()
        renderer = SupervisedWindowsExcelPdfRenderer(launcher=launcher)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "never-send", "GOOGLE_DRIVE_REFRESH_TOKEN": "nope"}):
            result = renderer.render_xlsx_pdf(XLSX)
        self.assertEqual(result, PDF)
        self.assertEqual(len(launcher.calls), 1)
        self.assertEqual(launcher.calls[0][0][1:3], ["-m", "kagent.windows_excel_pdf_child"])
        self.assertNotIn("OPENAI_API_KEY", launcher.calls[0][2])
        self.assertNotIn("GOOGLE_DRIVE_REFRESH_TOKEN", launcher.calls[0][2])
        self.assertTrue(launcher.jobs[0].terminated)
        self.assertTrue(launcher.jobs[0].closed)

    def test_supervised_excel_timeout_kills_job_and_returns_no_bytes(self):
        if os.name != "nt":
            self.skipTest("Windows-only isolated Excel child")
        launcher = FakeLauncher(timeout=True)
        renderer = SupervisedWindowsExcelPdfRenderer(
            timeout_seconds=5, launcher=launcher,
        )
        with self.assertRaisesRegex(ContractError, "timed out"):
            renderer.render_xlsx_pdf(XLSX)
        self.assertTrue(launcher.jobs[0].terminated)
        self.assertTrue(launcher.jobs[0].closed)

    def test_supervised_rejects_corrupted_workbook_before_process(self):
        if os.name != "nt":
            self.skipTest("Windows-only isolated Excel child")
        launcher = FakeLauncher()
        with self.assertRaises(ContractError):
            SupervisedWindowsExcelPdfRenderer(launcher=launcher).render_xlsx_pdf(
                b"PK\x03\x04not a valid workbook"
            )
        self.assertEqual(launcher.calls, [])

    def test_composition_needs_independent_selected_root_read_grant(self):
        host, _, _, clock = _harness()
        device = host._assembly._device
        with self.assertRaises(ContractError):
            compose_approved_windows_office_pairs(
                device=device, file_requests=Plan(),
                file_authorization_port=None, clock=clock,
            )
        class RefusingGrant:
            def authorize(self, *, request, now):
                raise ContractError("not approved")
        producer = compose_approved_windows_office_pairs(
            device=device, file_requests=Plan(),
            file_authorization_port=RefusingGrant(), clock=clock,
        )
        self.assertIsInstance(producer, ApprovedWindowsOfficePairProducer)
        self.assertIsInstance(producer._files, WindowsSelectedRootFileRuntime)
        self.assertIsInstance(producer._renderer, SupervisedWindowsExcelPdfRenderer)

    def test_supervised_child_nonzero_exposes_no_original_bytes(self):
        if os.name != "nt":
            self.skipTest("Windows-only isolated Excel child")
        launcher = FakeLauncher(bad_exit=True)
        with self.assertRaisesRegex(ContractError, "refused"):
            SupervisedWindowsExcelPdfRenderer(launcher=launcher).render_xlsx_pdf(XLSX)
        self.assertTrue(launcher.jobs[0].terminated)
        self.assertTrue(launcher.jobs[0].closed)


if __name__ == "__main__":
    unittest.main()
