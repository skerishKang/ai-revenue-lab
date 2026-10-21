"""#5448: the virtual online order -> supply -> shipment pilot runner.

Focused tests for :mod:`kagent.ops_sales_order_pilot`.

The suite proves that the pilot is a **virtual** run and says so in its own
output:

* one virtual order runs through all eight business steps and completes;
* the supplier purchase-order request stays ``DRAFT`` and the staged outbound
  record stays ``PENDING`` — nothing is issued and nothing is sent;
* every fail-closed guard probe actually fires;
* the generated work products exist, and none of them contains the raw
  recipient name, phone number or address;
* the report separates what was measured on this machine from what is only a
  virtual business timeline, and refuses a baseline comparison it never made.

No network, no credentials, no provider, no model call.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from kagent.ops_sales_order import SalesOrderStatus
from kagent.ops_sales_order_pilot import (
    DEFAULT_PILOT_SLUG,
    OnlineOrderPilotResult,
    SalesOrderPilotError,
    load_pilot_inputs,
    run_online_order_pilot,
)


APP_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = APP_ROOT / "pilots" / DEFAULT_PILOT_SLUG / "sample"

RAW_RECIPIENT_NAME = "테스트수령인"
RAW_PHONE = "010-0000-0000"
RAW_ADDRESS = "가상시 테스트로 1"


class PilotInputTests(unittest.TestCase):
    def test_sample_inputs_are_present_and_parse(self) -> None:
        inputs = load_pilot_inputs(SAMPLE_DIR)

        self.assertEqual(len(inputs.suppliers), 1)
        self.assertEqual(len(inputs.positions), 2)
        self.assertEqual(len(inputs.shipments), 4)
        self.assertEqual(len(inputs.exceptions), 2)
        self.assertTrue(inputs.field_reviews)

    def test_missing_sample_directory_is_refused(self) -> None:
        with self.assertRaises(SalesOrderPilotError):
            load_pilot_inputs(SAMPLE_DIR / "does-not-exist")


class PilotRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.out_dir = Path(self._tmp.name) / "out"
        self.result: OnlineOrderPilotResult = run_online_order_pilot(
            sample_dir=SAMPLE_DIR,
            out_dir=self.out_dir,
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_the_virtual_order_reaches_completion(self) -> None:
        self.assertEqual(self.result.order_status, SalesOrderStatus.COMPLETED.value)

    def test_the_supplier_request_stays_a_draft_and_nothing_is_sent(self) -> None:
        self.assertEqual(self.result.supplier_request_status, "draft")
        self.assertEqual(self.result.outbox_state, "pending")

    def test_every_guard_probe_fires(self) -> None:
        missed = [
            probe.name for probe in self.result.guard_probes if not probe.fired
        ]

        self.assertEqual(missed, [], f"guard probes did not fire: {missed}")
        self.assertEqual(len(self.result.guard_probes), 5)

    def test_the_expected_work_products_are_written(self) -> None:
        names = {Path(artifact.path).name for artifact in self.result.artifacts}

        self.assertEqual(
            names,
            {
                "order_intake_record.json",
                "supplier_order_request_draft.md",
                "supplier_order_request_email_draft.txt",
                "tracking_input_template.csv",
                "shipment_tracking.csv",
                "order_lines.csv",
                "exception_cases.csv",
                "order_completion_record.json",
                "fulfillment_case.json",
                "pilot_report.json",
            },
        )
        for artifact in self.result.artifacts:
            self.assertTrue(Path(artifact.path).is_file())
            self.assertGreater(artifact.bytes, 0)

    def test_no_artifact_contains_the_raw_recipient_data(self) -> None:
        for artifact in self.result.artifacts:
            text = Path(artifact.path).read_text(encoding="utf-8")
            self.assertNotIn(RAW_RECIPIENT_NAME, text, artifact.path)
            self.assertNotIn(RAW_PHONE, text, artifact.path)
            self.assertNotIn(RAW_ADDRESS, text, artifact.path)

    def test_the_shipment_tracking_record_carries_the_waybill(self) -> None:
        text = (self.out_dir / "shipment_tracking.csv").read_text(encoding="utf-8")

        self.assertIn("tracking_number", text.splitlines()[0])
        self.assertIn("TRK-2026-0001", text)
        self.assertIn("delivered", text)

    def test_the_tracking_input_template_is_reusable(self) -> None:
        text = (self.out_dir / "tracking_input_template.csv").read_text(encoding="utf-8")
        header = text.splitlines()[0]

        self.assertEqual(
            header,
            "shipment_id,carrier,tracking_number,observed_at,delivered_at,status,note",
        )

    def test_the_supplier_draft_is_marked_as_a_draft_and_not_sent(self) -> None:
        text = (self.out_dir / "supplier_order_request_draft.md").read_text(encoding="utf-8")

        self.assertIn("DRAFT", text)
        self.assertIn("발송되지 않았습니다", text)

    def test_the_case_json_marks_the_draft_as_unsent(self) -> None:
        payload = json.loads(
            (self.out_dir / "fulfillment_case.json").read_text(encoding="utf-8")
        )

        self.assertFalse(payload["supplier_order_request_draft"]["sent"])
        self.assertEqual(len(payload["fulfillment_steps"]), 8)
        self.assertEqual(payload["order"]["status"], SalesOrderStatus.COMPLETED.value)

    def test_the_report_separates_measurement_from_the_virtual_timeline(self) -> None:
        report = json.loads((self.out_dir / "pilot_report.json").read_text(encoding="utf-8"))

        self.assertTrue(report["automation_execution"]["measured"])
        self.assertFalse(report["business_step_intervals"]["production_measurement"])
        self.assertFalse(report["kpi_measurement_scope"]["production_measurement"])
        self.assertFalse(report["baseline_measured"])
        self.assertFalse(report["measured_comparison_available"])

    def test_the_report_states_that_nothing_live_happened(self) -> None:
        report = json.loads((self.out_dir / "pilot_report.json").read_text(encoding="utf-8"))

        self.assertTrue(report["pilot"]["virtual_case"])
        self.assertFalse(report["pilot"]["real_customer_data_used"])
        self.assertFalse(report["pilot"]["real_order_placed"])
        self.assertFalse(report["pilot"]["real_purchase_order_issued"])
        self.assertFalse(report["pilot"]["message_sent"])

    def test_the_measurement_plan_covers_all_eight_steps(self) -> None:
        report = json.loads((self.out_dir / "pilot_report.json").read_text(encoding="utf-8"))

        self.assertEqual(len(report["measurement_plan"]), 8)
        for entry in report["measurement_plan"]:
            self.assertTrue(entry["production_clock_source"])
            self.assertTrue(entry["error_signal"])


if __name__ == "__main__":
    unittest.main()
