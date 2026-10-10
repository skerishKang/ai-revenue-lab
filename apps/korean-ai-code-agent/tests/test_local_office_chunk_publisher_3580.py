"""#3580: real KAgent pinned HTTPS chunk envelope; no network or Drive WRITE."""
from __future__ import annotations

import base64
from hashlib import sha256
from io import BytesIO
from openpyxl import Workbook
import pytest

from kagent.local_office_chunk_publisher import (
    LocalOfficeChunkPublisher, OFFICE_TRANSFER_CHUNK_BYTES,
)
from kagent.local_agent_control_plane_https import ControlPlaneHttpsOperation
from kagent.local_agent_secure_transport import (
    OutboundBrokerEndpoint, OutboundTransportConfig, OutboundTransportMode,
)
from kagent.contracts import ContractError


class FakePinnedHttps:
    def __init__(self, deny=False):
        self.calls = []
        self.deny = deny

    def post(self, *, config, operation, payload, timeout_seconds):
        assert config.endpoint.url == "https://broker.example.test/"
        assert operation is ControlPlaneHttpsOperation.OFFICE_PART
        assert timeout_seconds == 20
        self.calls.append(payload)
        if self.deny:
            return {"ok": False, "error": {"code": "office_transfer_not_configured"}}
        return {"ok": True, "office_part": {
            "stored": True, "kind": payload["kind"],
            "part_index": payload["part_index"],
        }}


def client(transport):
    config = OutboundTransportConfig(endpoint=OutboundBrokerEndpoint(
        endpoint_ref="broker.office.3580",
        url="https://broker.example.test/",
        mode=OutboundTransportMode.HTTPS_LONG_POLL,
    ))
    return LocalOfficeChunkPublisher(transport=transport, config=config)


BASE = dict(
    binding_ref="binding.office.1", credential=b"private-device-credential",
    command_id="command.office.1", run_id="run.office.1",
    artifact_id="artifact.office.1", filename="quote.pdf",
    media_type="application/pdf", kind="pdf",
)


def test_real_pinned_https_json_contains_only_chunk_auth_and_no_drive_claim():
    port = FakePinnedHttps()
    pdf = b"%PDF-1.4\n" + (b"R" * (OFFICE_TRANSFER_CHUNK_BYTES + 20)) + b"\n%%EOF\n"
    receipt = client(port).publish(**BASE, content=pdf)
    assert receipt.part_count == 2
    assert receipt.integrity_ref == sha256(pdf).hexdigest()
    assert receipt.private_staging_only and not receipt.drive_upload_granted
    assert len(port.calls) == 2
    assert "workspace_ref" not in port.calls[0]
    assert "owner_id" not in port.calls[0]
    assert "target_ref" not in port.calls[0]
    assert b"".join(base64.b64decode(c["data_b64"]) for c in port.calls) == pdf
    assert all(c["integrity_ref"] == receipt.integrity_ref for c in port.calls)


def test_real_openpyxl_xlsx_content_is_classified_and_emitted():
    book = Workbook()
    book.active["A1"] = "Quote"
    book.active["B2"] = 1250000
    buffer = BytesIO()
    book.save(buffer)
    original = buffer.getvalue()
    port = FakePinnedHttps()
    receipt = client(port).publish(**{
        **BASE, "content": original, "filename": "quote.xlsx",
        "kind": "xlsx",
        "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    })
    assert receipt.integrity_ref == sha256(original).hexdigest()
    assert b"".join(base64.b64decode(c["data_b64"]) for c in port.calls) == original


def test_untrusted_zip_rejected_before_credential_sent():
    port = FakePinnedHttps()
    with pytest.raises(ContractError):
        client(port).publish(**{
            **BASE, "content": b"PK\\x03\\x04bad archive",
            "kind": "xlsx", "filename": "quote.xlsx",
            "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        })
    assert port.calls == []


def test_explicit_server_refusal_is_not_retried():
    port = FakePinnedHttps(deny=True)
    with pytest.raises(ContractError, match="refused"):
        client(port).publish(**BASE, content=b"%PDF-1.4\n%%EOF")
    assert len(port.calls) == 1
