"""#3580: real binary chunks, SQLite durable staging, canonical device auth.

No Google Drive writes, no Production binding. Uses actual broker command state
and actual XLSX/PDF bytes, with only HTTPS network replaced by a local port.
"""
from __future__ import annotations

import base64
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
import json
import sqlite3
from types import SimpleNamespace
import pytest

from local_agent_broker_office_chunks import (
    BrokerOfficeChunkStore, OfficeChunkRefused, OFFICE_CHUNK_BYTES,
)
from test_local_agent_broker_device_http import (
    _service_fixture, _envelope, BASE, CREDENTIAL, AUTHORITY_REF,
)
from kagent.local_office_chunk_publisher import LocalOfficeChunkPublisher
from kagent.local_agent_secure_transport import (
    OutboundBrokerEndpoint, OutboundTransportConfig, OutboundTransportMode,
)


class SqlCursor:
    def __init__(self, cursor):
        self.cursor = cursor
        self.rowsWritten = max(0, cursor.rowcount)
    def toArray(self):
        return [dict(r) for r in self.cursor.fetchall()]


class Sql:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
    def exec(self, statement, *params):
        return SqlCursor(self.conn.execute(statement, params))


class DeviceHttpPort:
    def __init__(self, service):
        self.service = service
        self.calls = 0
    def post(self, *, config, operation, payload, timeout_seconds):
        assert config.endpoint.url == "https://broker.example.test/"
        assert operation.value == "office-part"
        self.calls += 1
        body = json.dumps(payload, separators=(",", ":")).encode()
        response = self.service.handle(_envelope(body, route="/office-part"))
        return response["body"]


def fixture(*, installed=True, completed=True):
    state, authority, _, service = _service_fixture()
    if completed:
        session = authority.open_session(
            session_id="session.office.3580", binding_ref="binding.http.1",
            credential=CREDENTIAL, account_ref="account.http.1",
            workspace_ref="workspace.http.1", now=BASE+timedelta(seconds=1),
        )
        command = authority.enqueue_command(
            command_id="command.office.3580", binding_ref="binding.http.1",
            run_id="run.office.3580", tool_request_ref="tool.office.3580",
            request_fingerprint="c"*64, now=BASE+timedelta(seconds=2),
        )
        authority.admit_command(
            admission_ref="admission.office.3580",
            evidence_ref="evidence.office.3580",
            session_id=session.session_id, binding_ref="binding.http.1",
            credential=CREDENTIAL, command_id=command.command_id,
            request_fingerprint="c"*64, request_id="request.office.3580",
            now=BASE+timedelta(seconds=3),
        )
        authority.acknowledge(
            session_id=session.session_id, binding_ref="binding.http.1",
            credential=CREDENTIAL, command_id=command.command_id,
            admission_ref="admission.office.3580",
            evidence_ref="evidence.office.3580",
            revision_ref=command.revision_ref, termination="exited",
            request_id="request.office.3580", exit_code=0,
            now=BASE+timedelta(seconds=4),
        )
    sql = Sql()
    store = BrokerOfficeChunkStore(
        storage=SimpleNamespace(sql=sql),
        state_port=state, authority_ref=AUTHORITY_REF,
        clock=lambda: BASE + timedelta(seconds=10),
    )
    if installed:
        service._office_chunks = store
    http = DeviceHttpPort(service)
    config = OutboundTransportConfig(
        endpoint=OutboundBrokerEndpoint(
            endpoint_ref="broker.office.3580",
            url="https://broker.example.test/",
            mode=OutboundTransportMode.HTTPS_LONG_POLL,
        ),
    )
    client = LocalOfficeChunkPublisher(transport=http, config=config)
    return authority, service, store, sql, http, client


PDF = b"%PDF-1.4\n" + (b"A" * (OFFICE_CHUNK_BYTES + 321)) + b"\n%%EOF\n"
PARAMS = dict(
    binding_ref="binding.http.1", credential=CREDENTIAL,
    command_id="command.office.3580", run_id="run.office.3580",
    artifact_id="artifact.office.pdf.3580", filename="quote.pdf",
    media_type="application/pdf", content=PDF, kind="pdf",
)


def test_real_outbound_chunks_are_durable_and_private_reassembled():
    _, _, store, sql, http, client = fixture()
    receipt = client.publish(**PARAMS)
    assert receipt.private_staging_only is True
    assert receipt.drive_upload_granted is False
    assert receipt.part_count == 2 and http.calls == 2
    chunks = [store.read_part(
        owner="account.http.1", workspace="workspace.http.1",
        run_id="run.office.3580", command_id="command.office.3580",
        kind="pdf", part_index=i,
    ) for i in range(receipt.part_count)]
    rebuilt = b"".join(base64.b64decode(c["data_b64"]) for c in chunks)
    assert rebuilt == PDF
    assert sha256(rebuilt).hexdigest() == receipt.integrity_ref
    assert sql.conn.execute(
        "SELECT verified FROM local_agent_office_artifact"
    ).fetchone()["verified"] == 1
    assert CREDENTIAL not in json.dumps(chunks).encode()
    assert all(c["contract_version"] == "claw-office-artifact-read.v1" for c in chunks)


def test_exact_replay_no_mutation_and_conflicting_replay_refused():
    _, _, store, sql, http, client = fixture()
    client.publish(**PARAMS)
    before = sql.conn.execute("SELECT count(*) FROM local_agent_office_part").fetchone()[0]
    client.publish(**PARAMS)
    after = sql.conn.execute("SELECT count(*) FROM local_agent_office_part").fetchone()[0]
    assert before == after == 2
    with pytest.raises(Exception):
        client.publish(**{**PARAMS, "content": PDF.replace(b"A", b"B")})
    assert sql.conn.execute(
        "SELECT count(*) FROM local_agent_office_part"
    ).fetchone()[0] == 2


def test_missing_last_part_fails_closed_then_completes():
    _, _, store, _, _, client = fixture()
    class BreakSecond:
        def __init__(self, original):
            self.original = original
            self.calls = 0
        def post(self, **kwargs):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("network disconnected")
            return self.original.post(**kwargs)
    client._transport = BreakSecond(client._transport)
    with pytest.raises(RuntimeError):
        client.publish(**PARAMS)
    with pytest.raises(OfficeChunkRefused, match="incomplete"):
        store.read_part(
            owner="account.http.1", workspace="workspace.http.1",
            run_id="run.office.3580", command_id="command.office.3580",
            kind="pdf", part_index=0,
        )
    client._transport = client._transport.original
    client.publish(**PARAMS)
    assert store.read_part(
        owner="account.http.1", workspace="workspace.http.1",
        run_id="run.office.3580", command_id="command.office.3580",
        kind="pdf", part_index=1,
    )["part_count"] == 2


def test_no_artifact_authority_from_browser_or_wrong_owner():
    _, service, store, _, _, client = fixture()
    with pytest.raises(OfficeChunkRefused):
        store.read_part(
            owner="foreign.owner", workspace="workspace.http.1",
            run_id="run.office.3580", command_id="command.office.3580",
            kind="pdf", part_index=0,
        )
    invalid = client.publish if False else None
    del invalid
    http = DeviceHttpPort(service)
    bad = {
        "binding_ref": "binding.http.1",
        "credential_b64": base64.b64encode(b"invalid credential").decode(),
        "contract_version": "claw-office-artifact-chunk.v1",
    }
    response = service.handle(_envelope(
        json.dumps(bad).encode(), route="/office-part",
    ))
    assert response["status"] == 401
    assert response["body"]["error"]["code"] == "local_agent_http_auth_required"


def test_inert_route_and_incomplete_command_blocked():
    _, service, store, _, http, client = fixture(installed=False)
    with pytest.raises(Exception):
        client.publish(**PARAMS)
    assert http.calls == 1
    _, _, _, sql2, http2, client2 = fixture(completed=False)
    with pytest.raises(Exception):
        client2.publish(**PARAMS)
    assert sql2.conn.execute(
        "SELECT count(*) FROM local_agent_office_artifact"
    ).fetchone()[0] == 0


def test_wrong_owner_and_corrupted_bytes_refuse_without_partial_read():
    _, _, store, sql, _, client = fixture()
    client.publish(**PARAMS)
    with pytest.raises(OfficeChunkRefused):
        store.read_part(owner="account.http.1", workspace="other.workspace",
                        run_id="run.office.3580", command_id="command.office.3580",
                        kind="pdf", part_index=0)
    sql.conn.execute("UPDATE local_agent_office_part SET data_b64=? WHERE part_index=1",
                     (base64.b64encode(b"corruption").decode(),))
    with pytest.raises(OfficeChunkRefused):
        store.read_part(owner="account.http.1", workspace="workspace.http.1",
                        run_id="run.office.3580", command_id="command.office.3580",
                        kind="pdf", part_index=0)

def test_revoked_binding_cannot_read_staged_original():
    authority, _, store, _, _, client = fixture()
    client.publish(**PARAMS)
    authority.revoke_binding("binding.http.1", now=BASE+timedelta(seconds=5))
    with pytest.raises(OfficeChunkRefused):
        store.read_part(
            owner="account.http.1", workspace="workspace.http.1",
            run_id="run.office.3580", command_id="command.office.3580",
            kind="pdf", part_index=0,
        )


def test_staged_file_expires_and_reclaims_sql_rows_after_one_day():
    _, _, store, sql, _, client = fixture()
    client.publish(**PARAMS)
    store._clock = lambda: BASE + timedelta(days=2)
    with pytest.raises(OfficeChunkRefused):
        store.read_part(
            owner="account.http.1", workspace="workspace.http.1",
            run_id="run.office.3580", command_id="command.office.3580",
            kind="pdf", part_index=0,
        )
    assert sql.conn.execute("SELECT count(*) FROM local_agent_office_artifact").fetchone()[0] == 0
    assert sql.conn.execute("SELECT count(*) FROM local_agent_office_part").fetchone()[0] == 0


def test_real_xlsx_workbook_bytes_are_staged_as_distinct_kind():
    from io import BytesIO
    from openpyxl import Workbook
    _, _, store, _, _, client = fixture()
    wb = Workbook()
    wb.active["A1"] = "Quote"
    wb.active["B2"] = 1250000
    buffer = BytesIO()
    wb.save(buffer)
    data = buffer.getvalue()
    receipt = client.publish(**{
        **PARAMS, "artifact_id": "artifact.office.xlsx.3580",
        "filename": "quote.xlsx",
        "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "content": data, "kind": "xlsx",
    })
    chunk = store.read_part(
        owner="account.http.1", workspace="workspace.http.1",
        run_id="run.office.3580", command_id="command.office.3580",
        kind="xlsx", part_index=0,
    )
    assert base64.b64decode(chunk["data_b64"]) == data
    assert receipt.integrity_ref == sha256(data).hexdigest()
