"""#3580: legacy OLE2 XLS must never be mislabeled as editable XLSX."""
from __future__ import annotations

import os
from pathlib import Path
import unittest
from unittest.mock import patch

from kagent.contracts import ContractError
from kagent.supervised_windows_legacy_xls_pdf import (
    SupervisedWindowsLegacyXlsPdfRenderer,
)
from kagent.windows_excel_legacy_xls_child import OLE2_SIGNATURE, main as child_main
from test_3580_resident_office_post_ack_delivery import PDF
from test_3580_supervised_office_pair_producer import FakeJob, FakeProcess

SAMPLE_OLE2_HEADER = OLE2_SIGNATURE + b"\0" * 128


class FakeLauncher:
    def __init__(self, *, timeout=False, bad_exit=False, bad_output=False):
        self.timeout = timeout
        self.bad_exit = bad_exit
        self.bad_output = bad_output
        self.calls = []
        self.jobs = []

    def __call__(self, argv, *, cwd, environment):
        self.calls.append((argv, cwd, environment))
        job = FakeJob()
        self.jobs.append(job)
        if not self.timeout and not self.bad_exit:
            Path(argv[-1]).write_bytes(b"not-PDF" if self.bad_output else PDF)
        return type("Bound", (), {
            "job": job,
            "process": FakeProcess(timeout=self.timeout, bad_exit=self.bad_exit),
        })()


class LegacyXlsPdfTests(unittest.TestCase):
    def test_linux_no_legacy_job_or_fake_pdf(self):
        if os.name == "nt":
            self.skipTest("non-Windows only")
        fake = FakeLauncher()
        with self.assertRaisesRegex(ContractError, "Windows-only"):
            SupervisedWindowsLegacyXlsPdfRenderer(launcher=fake).render_xls_pdf(SAMPLE_OLE2_HEADER)
        self.assertEqual(fake.calls, [])

    def test_original_unchanged_proper_pdf_and_no_secrets_in_child(self):
        if os.name != "nt":
            self.skipTest("Windows Job supervision only")
        fake = FakeLauncher()
        original = SAMPLE_OLE2_HEADER
        with patch.dict(os.environ, {"GOOGLE_DRIVE_REFRESH_TOKEN": "never", "OPENAI_API_KEY": "never", "PADIEM_AGENT_DEVICE_CREDENTIAL": "never"}):
            pdf = SupervisedWindowsLegacyXlsPdfRenderer(launcher=fake).render_xls_pdf(original)
        self.assertEqual(pdf, PDF)
        self.assertEqual(original, SAMPLE_OLE2_HEADER)
        self.assertEqual(fake.calls[0][0][1:3], ["-m", "kagent.windows_excel_legacy_xls_child"])
        for name in ("GOOGLE_DRIVE_REFRESH_TOKEN", "OPENAI_API_KEY", "PADIEM_AGENT_DEVICE_CREDENTIAL"):
            self.assertNotIn(name, fake.calls[0][2])
        self.assertTrue(fake.jobs[0].terminated)
        self.assertTrue(fake.jobs[0].closed)

    def test_invalid_or_oversize_source_rejected_before_excel(self):
        if os.name != "nt":
            self.skipTest("Windows-only")
        fake = FakeLauncher()
        for payload in (b"", OLE2_SIGNATURE, b"PK\x03\x04"+b"fake", "text", OLE2_SIGNATURE+b"x" * (1024*1024)):
            with self.subTest(kind=str(payload)[:12]):
                with self.assertRaises(ContractError):
                    SupervisedWindowsLegacyXlsPdfRenderer(launcher=fake).render_xls_pdf(payload)
        self.assertEqual(fake.calls, [])

    def test_timeout_closes_job_without_claiming_excel_com_orphan_cleanup(self):
        if os.name != "nt":
            self.skipTest("Windows-only")
        fake = FakeLauncher(timeout=True)
        with self.assertRaisesRegex(ContractError, "timed out"):
            SupervisedWindowsLegacyXlsPdfRenderer(timeout_seconds=5, launcher=fake).render_xls_pdf(SAMPLE_OLE2_HEADER)
        self.assertTrue(fake.jobs[0].terminated)
        self.assertTrue(fake.jobs[0].closed)

    def test_bad_or_missing_pdf_is_rejected(self):
        if os.name != "nt":
            self.skipTest("Windows-only")
        for flags in ({"bad_exit":True},{"bad_output":True}):
            fake = FakeLauncher(**flags)
            with self.assertRaises(ContractError):
                SupervisedWindowsLegacyXlsPdfRenderer(launcher=fake).render_xls_pdf(SAMPLE_OLE2_HEADER)
            self.assertTrue(fake.jobs[0].closed)

    def test_timeouts_and_untrusted_paths_cannot_be_injected(self):
        for t in (0, 1, 121, True, 8.5):
            with self.subTest(timeout=t):
                with self.assertRaises(ContractError):
                    SupervisedWindowsLegacyXlsPdfRenderer(timeout_seconds=t)
        self.assertEqual(child_main([]), 2)
        self.assertEqual(child_main(["C:/user-data.xls", "C:/tmp/out.pdf"]), 2)


if __name__ == "__main__":
    unittest.main()
