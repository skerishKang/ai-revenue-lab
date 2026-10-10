"""#3580: resident sends exact P01 Office original pair ONLY after broker ACK.

No real provider calls; fake pinned transport and canonical in-memory broker
exercise the real resident coordinator through admission, execution and ACK.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import unittest

from kagent.artifact_registration import register_canonical_artifact
from kagent.contracts import ContractError
from kagent.local_agent_runtime_host import InMemorySingleInstanceLock
from kagent.local_office_chunk_publisher import LocalOfficeChunkPublisher
from kagent.local_resident_office_delivery import ResidentOfficePairPublisher
from kagent.local_xlsx_artifact_handoff import LocalXlsxArtifactHandoff
from kagent.local_xlsx_pdf_output import render_local_xlsx_pdf_output
from kagent.local_agent_secure_transport import (
    OutboundBrokerEndpoint, OutboundTransportConfig, OutboundTransportMode,
)
from kagent.xlsx_fidelity_route import classify_xlsx
from test_xlsx_fidelity_route import workbook, SIMPLE_SHEET
from test_local_agent_runtime_host import _harness

XLSX = workbook(sheet=SIMPLE_SHEET)
PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
NOW = datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc)


class FakeExcel:
    def render_xlsx_pdf(self, source_bytes):
        assert source_bytes == XLSX
        return PDF


def pair_for_host(*, workspace="ws_host_1", run="run_host_1"):
    from hashlib import sha256
    source = LocalXlsxArtifactHandoff(
        record=register_canonical_artifact(
            artifact_id="quote_source_3580", artifact_kind="source.xlsx",
            filename="quote.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            size_bytes=len(XLSX), integrity_ref=sha256(XLSX).hexdigest(),
            workspace_ref=workspace, run_ref=run, source_ref="local-read/approved",
        ),
        content=XLSX, route=classify_xlsx(XLSX, local_only=True),
    )
    output = render_local_xlsx_pdf_output(
        source=source, renderer=FakeExcel(), workspace_ref=workspace,
        run_ref=run, artifact_id="quote_output_pdf_3580",
        lineage_id="lineage_quote_3580", now=NOW,
    )
    return source, output


class FakeProducer:
    def __init__(self, pair):
        self.pair = pair
        self.calls = []
    def completed_pair(self, **kwargs):
        self.calls.append(kwargs)
        return self.pair


class FakePinnedHttps:
    def __init__(self, broker):
        self.broker = broker
        self.calls = []
        self.deny_kind = ""
    def post(self, *, config, operation, payload, timeout_seconds):
        assert config.endpoint.url.startswith("https://")
        assert operation.value == "office-part"
        # The canonical broker already ACKed the exact command. No upload
        # may arrive before the ACK reaches the broker.
        command = self.broker._commands["cmd_host_1"]
        assert command.state.value == "acknowledged"
        self.calls.append(payload)
        if self.deny_kind == payload["kind"]:
            return {"ok": False}
        return {"ok": True, "office_part": {
            "stored": True, "kind": payload["kind"],
            "part_index": payload["part_index"],
        }}


def staging(*, broker, pair):
    port = FakePinnedHttps(broker)
    config = OutboundTransportConfig(
        endpoint=OutboundBrokerEndpoint(
            endpoint_ref="broker.resident.3580", url="https://broker.example.test/",
            mode=OutboundTransportMode.HTTPS_LONG_POLL,
        ),
    )
    source = FakeProducer(pair)
    deliver = ResidentOfficePairPublisher(
        approved_pairs=source,
        publisher=LocalOfficeChunkPublisher(transport=port, config=config),
    )
    return deliver, source, port


class ResidentPostAckDeliveryTests(unittest.TestCase):
    def setUp(self):
        InMemorySingleInstanceLock.reset()
    def tearDown(self):
        InMemorySingleInstanceLock.reset()

    def test_real_resident_ack_then_exact_original_xlsx_and_pdf(self):
        host, runtime, port, clock = _harness()
        stage, approved, tls = staging(
            broker=port.broker_authority, pair=pair_for_host(),
        )
        host._office_staging = stage
        host.start()
        clock.advance(5)
        self.assertEqual(host.run_once(now=clock.now), 1)
        self.assertEqual(runtime.executed, ["req_host_1"])
        self.assertEqual(len(approved.calls), 1)
        self.assertEqual([p["kind"] for p in tls.calls], ["xlsx", "pdf"])
        self.assertEqual(tls.calls[0]["command_id"], "cmd_host_1")
        self.assertEqual(tls.calls[0]["run_id"], "run_host_1")
        self.assertNotIn("account_ref", tls.calls[0])
        self.assertNotIn("workspace_ref", tls.calls[0])
        self.assertEqual(port.broker_authority._commands["cmd_host_1"].exit_code, 0)
        host.stop()

    def test_non_office_command_does_not_publish(self):
        host, _, port, clock = _harness()
        stage, approved, tls = staging(broker=port.broker_authority, pair=None)
        host._office_staging = stage
        host.start()
        clock.advance(5)
        self.assertEqual(host.run_once(now=clock.now), 1)
        self.assertEqual(len(approved.calls), 1)
        self.assertEqual(tls.calls, [])
        host.stop()

    def test_cross_workspace_office_pair_is_refused_but_ack_retained(self):
        host, _, port, clock = _harness()
        stage, approved, tls = staging(broker=port.broker_authority,
                                       pair=pair_for_host(workspace="foreign"))
        host._office_staging = stage
        host.start()
        clock.advance(5)
        self.assertEqual(host.run_once(now=clock.now), 1)
        self.assertEqual(tls.calls, [])
        self.assertEqual(port.broker_authority._commands["cmd_host_1"].state.value, "acknowledged")
        host.stop()

    def test_broker_stage_refusal_does_not_retry_execute_or_claim_drive(self):
        host, runtime, port, clock = _harness()
        stage, _, tls = staging(broker=port.broker_authority,
                                pair=pair_for_host())
        tls.deny_kind = "xlsx"
        host._office_staging = stage
        host.start()
        clock.advance(5)
        self.assertEqual(host.run_once(now=clock.now), 1)
        self.assertEqual(runtime.executed, ["req_host_1"])
        self.assertEqual(len(tls.calls), 1)
        self.assertEqual(port.broker_authority._commands["cmd_host_1"].state.value, "acknowledged")
        host.stop()

    def test_mismatched_canonical_output_refuses_before_any_bytes(self):
        host, _, port, clock = _harness()
        source, output = pair_for_host()
        output = replace(output, content=b"%PDF-corrupt")
        stage, _, tls = staging(broker=port.broker_authority,
                                pair=(source, output))
        host._office_staging = stage
        host.start()
        clock.advance(5)
        self.assertEqual(host.run_once(now=clock.now), 1)
        self.assertEqual(tls.calls, [])
        host.stop()

    def test_unconfigured_default_resident_never_publishes(self):
        host, runtime, port, clock = _harness()
        self.assertIsNone(host._office_staging)
        host.start()
        clock.advance(5)
        self.assertEqual(host.run_once(now=clock.now), 1)
        self.assertEqual(runtime.executed, ["req_host_1"])
        host.stop()


if __name__ == "__main__":
    unittest.main()

def test_failed_local_execution_never_enters_office_staging():
    InMemorySingleInstanceLock.reset()
    host, runtime, port, clock = _harness(fail_runtime=True)
    stage, approved, tls = staging(
        broker=port.broker_authority, pair=pair_for_host(),
    )
    host._office_staging = stage
    host.start()
    clock.advance(5)
    try:
        try:
            host.run_once(now=clock.now)
        except Exception:
            pass
        assert approved.calls == []
        assert tls.calls == []
    finally:
        host.stop()
        InMemorySingleInstanceLock.reset()
