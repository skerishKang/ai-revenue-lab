"""#4434: real XLSX workcopy revision and staging on a Windows selected root.

These tests write actual workbook bytes to disk with openpyxl, run them through
the actual selected-root runtime with canonical P01 approval evidence, and
re-read the produced file. Only the broker transport is faked, because no
network or Drive WRITE is part of this slice.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import os
import tempfile
import unittest
import zipfile

from openpyxl import Workbook, load_workbook

from padiem_ai_core.agent_approval import (
    ApprovalOutcome,
    ApprovalPause,
    ApprovalRequirement,
    VerifiedApprovalDecision,
    tool_invocation_digest,
)

from kagent.contracts import ContractError
from kagent.local_agent import LocalAgentDeviceProfile, LocalAgentPlatform, LocalRoot
from kagent.local_agent_control_plane_https import ControlPlaneHttpsOperation
from kagent.local_agent_permissions import (
    LocalPermissionRequest, default_device_permission_profile,
)
from kagent.local_agent_secure_transport import (
    OutboundBrokerEndpoint, OutboundTransportConfig, OutboundTransportMode,
)
from kagent.local_office_chunk_publisher import (
    LocalOfficeChunkPublisher, OFFICE_TRANSFER_CHUNK_BYTES,
)
from kagent.local_xlsx_python_copy_editor import (
    IndependentZipXlsxRevisionVerifier, OfficeFidelityRequired, PythonXlsxValueCopyEditor,
    MAX_XML_BYTES, _parse_xml_part,
)
from kagent.local_xlsx_revision_pdf import ReviewedCellRevision
from kagent.local_xlsx_workcopy_roundtrip import (
    revise_and_stage_approved_xlsx_workcopy, revised_path_for,
)
from kagent.local_xlsx_revision_pdf import revise_and_render_local_xlsx_pdf
from kagent.windows_local_filesystem import (
    DeterministicWindowsFileAuthorityEvidencePort,
    LocalFileOperation,
    LocalFileRequest,
    P01LocalPermissionWindowsFileAuthorizationPort,
    WindowsFileAuthorityEvidence,
    WindowsSelectedRootFileRuntime,
    file_request_fingerprint,
    windows_file_tool_invocation,
)

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
DEVICE_ID = "device_4434_xlsx"
WORKSPACE = "workspace_4434_xlsx"
RUN = "run_4434_xlsx"
SOURCE_PATH = "quote\\book.xlsx"
DERIVED_PATH = "quote\\book_revised.xlsx"

EDIT = ReviewedCellRevision(
    sheet_name="Quote", cell="B2", previous_value=88_000_000, replacement_value=91_500_000,
)
TEXT_EDIT = ReviewedCellRevision(
    sheet_name="Quote", cell="C2", previous_value="text kept", replacement_value="바뀐 값",
)


def excel_workbook_bytes(*, formula: bool = False) -> bytes:
    """A real Excel-shaped workbook: fidelity-sensitive, so the Office route owns it.

    openpyxl writes a styles part, a theme, ``pageMargins`` and cell style
    indices, and merges when asked, which is exactly what
    ``classify_xlsx(local_only=True)`` treats as fidelity-sensitive.
    """
    book = Workbook()
    sheet = book.active
    sheet.title = "Quote"
    sheet["A1"] = "기존 항목"
    sheet["B2"] = 88_000_000
    sheet["C2"] = "text kept"
    sheet["A5"] = "merged note"
    sheet.merge_cells("A5:C5")
    if formula:
        sheet["B3"] = "=B2*0.1"
    buffer = BytesIO()
    book.save(buffer)
    book.close()
    return buffer.getvalue()


def workbook_bytes(*, formula: bool = False, styles: bool = False,
                   second_sheet: bool = False) -> bytes:
    """The bytes a Python-path revision may attempt: see ``eligible_workbook_bytes``."""
    return eligible_workbook_bytes(formula=formula, styles=styles,
                                   second_sheet=second_sheet)


def eligible_workbook_bytes(*, styles: bool = False, formula: bool = False,
                            second_sheet: bool = False) -> bytes:
    """A workbook ``classify_xlsx(local_only=True)`` admits to the Python path.

    openpyxl always writes ``xl/styles.xml`` and a theme, gives cells a style
    index and writes ``pageMargins``/``mergeCells``, so anything it saves is
    fidelity-sensitive and belongs to the existing Office route. This package has
    no styles part, no ``s`` attribute and no blocked element unless the matching
    flag asks for it, which is what makes the route refusal, the editor's own
    formula refusal and the successful literal edit separately testable on real
    bytes.
    """
    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    pr = "http://schemas.openxmlformats.org/package/2006/relationships"
    types = [
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>',
    ]
    workbook_rels = [
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>',
    ]
    styled = ' s="1"' if styles else ""
    if styles:
        types.append('<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>')
        workbook_rels.append('<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>')
    if second_sheet:
        types.append('<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
        workbook_rels.append('<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>')
    sheets = '<sheet name="Quote" sheetId="1" r:id="rId1"/>'
    if second_sheet:
        sheets += '<sheet name="Later" sheetId="2" r:id="rId3"/>'
    formula_cell = ('<c r="B3"><f>B2*0.1</f><v>8800000</v></c>' if formula else "")
    parts = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            + "".join(types) + "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="{pr}">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>"
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<workbook xmlns="{main}" xmlns:r="{rel}">'
            f'<sheets>{sheets}</sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="{pr}">' + "".join(workbook_rels) + "</Relationships>"
        ),
        "xl/worksheets/sheet1.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<worksheet xmlns="{main}"><sheetData>'
            f'<row r="1"><c r="A1"{styled} t="inlineStr"><is><t>기존 항목</t></is></c></row>'
            f'<row r="2"><c r="B2"{styled}><v>88000000</v></c>'
            f'<c r="C2"{styled} t="inlineStr"><is><t>text kept</t></is></c>'
            f'{formula_cell}</row>'
            "</sheetData></worksheet>"
        ),
    }
    if second_sheet:
        parts["xl/worksheets/sheet2.xml"] = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<worksheet xmlns="{main}"><sheetData>'
            f'<row r="1"><c r="A1"{styled} t="inlineStr"><is><t>  후행 시트  </t></is></c></row>'
            f'<row r="2"><c r="B2"{styled}><v>-250</v></c>'
            f'<c r="D2"{styled}><v>1234567890123</v></c></row>'
            "</sheetData></worksheet>"
        )
    if styles:
        parts["xl/styles.xml"] = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<styleSheet xmlns="{main}"><fonts count="1"><font><sz val="11"/></font></fonts>'
            '<cellXfs count="2"><xf/><xf fontId="0"/></cellXfs></styleSheet>'
        )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in parts.items():
            archive.writestr(name, text)
    return buffer.getvalue()


def device(
    root_path: str, *, device_id: str = DEVICE_ID, workspace_ref: str = WORKSPACE,
    root_ref: str = "work",
) -> LocalAgentDeviceProfile:
    return LocalAgentDeviceProfile(
        device_id=device_id,
        workspace_ref=workspace_ref,
        platform=LocalAgentPlatform.WINDOWS,
        roots=(LocalRoot(root_ref=root_ref, windows_path=root_path),),
    )


def file_request(
    operation: LocalFileOperation,
    *,
    path_relative: str,
    action_id: str,
    content: bytes | None = None,
    run_id: str = RUN,
    device_id: str = DEVICE_ID,
    root_ref: str = "work",
    at: datetime = NOW,
) -> LocalFileRequest:
    return LocalFileRequest(
        action_id=action_id,
        run_id=run_id,
        device_id=device_id,
        root_ref=root_ref,
        operation=operation,
        path_relative=path_relative,
        requested_at=at - timedelta(minutes=1),
        content=content,
    )


def evidence_for(request: LocalFileRequest, *, at: datetime = NOW) -> WindowsFileAuthorityEvidence:
    invocation = windows_file_tool_invocation(request)
    fingerprint = file_request_fingerprint(request)
    permission = request.capability
    return WindowsFileAuthorityEvidence(
        evidence_ref=f"authority_{request.action_id}",
        request_fingerprint=fingerprint,
        permission_request=LocalPermissionRequest(
            action_id=f"permission_{request.action_id}",
            run_id=request.run_id,
            device_id=request.device_id,
            capability=permission,
            target_ref=fingerprint,
            root_ref=request.root_ref,
        ),
        approval_pause=ApprovalPause(
            pause_id=f"pause_{request.action_id}",
            run_id=request.run_id,
            agent_runtime_id="agent_4434",
            tool_id=invocation.tool_id,
            invocation_sha256=tool_invocation_digest(invocation),
            requirement=ApprovalRequirement.USER_CONFIRMATION,
            step_index=1,
            created_at=at - timedelta(minutes=2),
            expires_at=at + timedelta(minutes=10),
            approval_scope=(request.capability.value,),
        ),
        approval_decision=VerifiedApprovalDecision(
            decision_id=f"decision_{request.action_id}",
            pause_id=f"pause_{request.action_id}",
            outcome=ApprovalOutcome.APPROVED,
            authority_ref="p01_4434_authority",
            evidence_ref="p01_4434_evidence",
            decided_at=at - timedelta(seconds=30),
        ),
        local_policy_ref="local_file_policy_v1",
        expires_at=at + timedelta(minutes=5),
    )


def runtime(profile: LocalAgentDeviceProfile, requests: list[LocalFileRequest]):
    port = P01LocalPermissionWindowsFileAuthorizationPort(
        permission_profile=default_device_permission_profile(device=profile),
        evidence_port=DeterministicWindowsFileAuthorityEvidencePort(
            tuple(evidence_for(item) for item in requests)
        ),
    )
    return WindowsSelectedRootFileRuntime(device=profile, authorization_port=port)


class FakePinnedHttps:
    def __init__(self, *, deny_at: int | None = None) -> None:
        self.calls: list[dict] = []
        self.deny_at = deny_at

    def post(self, *, config, operation, payload, timeout_seconds):
        assert operation is ControlPlaneHttpsOperation.OFFICE_PART
        self.calls.append(payload)
        if self.deny_at is not None and len(self.calls) == self.deny_at:
            return {"ok": False, "error": {"code": "office_part_rejected"}}
        return {"ok": True, "office_part": {
            "stored": True, "kind": payload["kind"], "part_index": payload["part_index"],
        }}

    def reassembled(self) -> bytes:
        ordered = sorted(self.calls, key=lambda row: row["part_index"])
        return b"".join(base64.b64decode(row["data_b64"]) for row in ordered)


def publisher(transport: FakePinnedHttps) -> LocalOfficeChunkPublisher:
    return LocalOfficeChunkPublisher(
        transport=transport,
        config=OutboundTransportConfig(endpoint=OutboundBrokerEndpoint(
            endpoint_ref="broker.office.4434",
            url="https://broker.example.test/",
            mode=OutboundTransportMode.HTTPS_LONG_POLL,
        )),
    )


class _StubRenderer:
    """A stand-in for the Office renderer; this test proves port compatibility only."""

    def render_xlsx_pdf(self, source_bytes: bytes) -> bytes:
        return b"%PDF-1.4" + source_bytes[:64] + bytes([10]) + b"%%EOF" + bytes([10])


BASE_ARGS = dict(
    workspace_ref=WORKSPACE,
    source_artifact_id="artifact_4434_source",
    result_artifact_id="artifact_4434_result",
    binding_ref="binding_4434_device",
    command_id="command_4434_xlsx",
    credential=b"device-credential-for-staging",
    now=NOW,
)


@unittest.skipUnless(os.name == "nt", "physical selected-root file I/O is Windows-only")
class LocalXlsxWorkcopyRoundtripTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = self._directory.name
        os.makedirs(os.path.join(self.root, "quote"), exist_ok=True)
        self.source_on_disk = os.path.join(self.root, "quote", "book.xlsx")
        self.result_on_disk = os.path.join(self.root, "quote", "book_revised.xlsx")

    def write_source(self, data: bytes) -> bytes:
        with open(self.source_on_disk, "wb") as handle:
            handle.write(data)
        return data

    def run_roundtrip(self, source_bytes: bytes, edits=(EDIT, TEXT_EDIT)):
        self.write_source(source_bytes)
        profile = device(self.root)
        revised = PythonXlsxValueCopyEditor().revise_xlsx_copy(source_bytes, tuple(edits))
        read_request = file_request(
            LocalFileOperation.READ, path_relative=SOURCE_PATH, action_id="action_read",
        )
        write_request = file_request(
            LocalFileOperation.WRITE, path_relative=revised_path_for(SOURCE_PATH),
            action_id="action_write", content=revised,
        )
        host = runtime(profile, [read_request, write_request])
        transport = FakePinnedHttps()
        result = revise_and_stage_approved_xlsx_workcopy(
            runtime=host, device=profile,
            source_request=read_request,
            result_request_factory=lambda content, path: file_request(
                LocalFileOperation.WRITE, path_relative=path,
                action_id="action_write", content=content,
            ),
            edits=tuple(edits), publisher=publisher(transport),
            **BASE_ARGS,
        )
        return result, transport, revised

    def test_real_revision_writes_a_new_file_and_preserves_the_original(self) -> None:
        source = workbook_bytes(second_sheet=True)
        source_sha = sha256(source).hexdigest()
        result, transport, expected = self.run_roundtrip(source)

        with open(self.source_on_disk, "rb") as handle:
            self.assertEqual(sha256(handle.read()).hexdigest(), source_sha)
        self.assertTrue(os.path.isfile(self.result_on_disk))
        with open(self.result_on_disk, "rb") as handle:
            written = handle.read()
        self.assertEqual(sha256(written).hexdigest(), result.revised.integrity_ref)
        self.assertEqual(written, expected)
        self.assertEqual(written, transport.reassembled())
        self.assertEqual(result.staging.part_count, len(transport.calls))
        self.assertEqual(result.public_projection()["atomic_write_verified"], True)
        self.assertEqual(result.public_projection()["original_preserved"], True)

        book = load_workbook(BytesIO(written))
        sheet = book["Quote"]
        self.assertEqual(sheet["B2"].value, 91_500_000)
        self.assertEqual(sheet["C2"].value, "바뀐 값")
        self.assertEqual(sheet["A1"].value, "기존 항목")
        # A worksheet nobody approved stays exactly as it was.
        later = book["Later"]
        self.assertEqual(later["B2"].value, -250)
        self.assertEqual(later["D2"].value, 1_234_567_890_123)
        self.assertEqual(later["A1"].value, "  후행 시트  ")
        book.close()

    def test_only_the_target_sheet_part_differs_from_the_original(self) -> None:
        source = workbook_bytes(second_sheet=True)
        result, _transport, _expected = self.run_roundtrip(source)
        with open(self.result_on_disk, "rb") as handle:
            written = handle.read()
        before, after = zipfile.ZipFile(BytesIO(source)), zipfile.ZipFile(BytesIO(written))
        self.assertEqual(sorted(before.namelist()), sorted(after.namelist()))
        changed = [name for name in before.namelist() if before.read(name) != after.read(name)]
        self.assertEqual(changed, ["xl/worksheets/sheet1.xml"])
        self.assertEqual(before.read("xl/worksheets/sheet2.xml"),
                         after.read("xl/worksheets/sheet2.xml"))
        self.assertEqual(before.read("[Content_Types].xml"), after.read("[Content_Types].xml"))
        self.assertEqual(before.read("xl/workbook.xml"), after.read("xl/workbook.xml"))

    def test_formula_workbook_is_routed_to_the_office_path_without_writing(self) -> None:
        source = workbook_bytes(formula=True)
        profile = device(self.root)
        self.write_source(source)
        read_request = file_request(
            LocalFileOperation.READ, path_relative=SOURCE_PATH, action_id="action_read",
        )
        host = runtime(profile, [read_request])
        transport = FakePinnedHttps()
        with self.assertRaises(OfficeFidelityRequired):
            revise_and_stage_approved_xlsx_workcopy(
                runtime=host, device=profile, source_request=read_request,
                result_request_factory=lambda content, path: file_request(
                    LocalFileOperation.WRITE, path_relative=path,
                    action_id="action_write", content=content,
                ),
                edits=(EDIT,), publisher=publisher(transport), **BASE_ARGS,
            )
        self.assertFalse(os.path.exists(self.result_on_disk))
        self.assertEqual(transport.calls, [])

    def test_stale_previous_value_refuses_before_any_write(self) -> None:
        stale = ReviewedCellRevision(
            sheet_name="Quote", cell="B2", previous_value=1, replacement_value=2,
        )
        profile = device(self.root)
        self.write_source(workbook_bytes())
        read_request = file_request(
            LocalFileOperation.READ, path_relative=SOURCE_PATH, action_id="action_read",
        )
        host = runtime(profile, [read_request])
        with self.assertRaises(ContractError):
            revise_and_stage_approved_xlsx_workcopy(
                runtime=host, device=profile, source_request=read_request,
                result_request_factory=lambda content, path: file_request(
                    LocalFileOperation.WRITE, path_relative=path,
                    action_id="action_write", content=content,
                ),
                edits=(stale,), publisher=publisher(FakePinnedHttps()), **BASE_ARGS,
            )
        self.assertFalse(os.path.exists(self.result_on_disk))

    def test_write_without_p01_evidence_is_refused_and_nothing_is_staged(self) -> None:
        source = workbook_bytes()
        self.write_source(source)
        profile = device(self.root)
        revised = PythonXlsxValueCopyEditor().revise_xlsx_copy(source, (EDIT,))
        read_request = file_request(
            LocalFileOperation.READ, path_relative=SOURCE_PATH, action_id="action_read",
        )
        # Only the READ is approved: the WRITE evidence was never granted.
        host = runtime(profile, [read_request])
        transport = FakePinnedHttps()
        with self.assertRaises(ContractError):
            revise_and_stage_approved_xlsx_workcopy(
                runtime=host, device=profile, source_request=read_request,
                result_request_factory=lambda content, path: file_request(
                    LocalFileOperation.WRITE, path_relative=path,
                    action_id="action_unapproved", content=content,
                ),
                edits=(EDIT,), publisher=publisher(transport), **BASE_ARGS,
            )
        self.assertFalse(os.path.exists(self.result_on_disk))
        self.assertEqual(transport.calls, [])
        with open(self.source_on_disk, "rb") as handle:
            self.assertEqual(sha256(handle.read()).hexdigest(), sha256(source).hexdigest())
        self.assertIsInstance(revised, bytes)

    def test_result_must_use_the_derived_path_and_cannot_overwrite(self) -> None:
        source = workbook_bytes()
        profile = device(self.root)
        self.write_source(source)
        revised = PythonXlsxValueCopyEditor().revise_xlsx_copy(source, (EDIT,))
        read_request = file_request(
            LocalFileOperation.READ, path_relative=SOURCE_PATH, action_id="action_read",
        )
        wrong = file_request(
            LocalFileOperation.WRITE, path_relative=SOURCE_PATH,
            action_id="action_write", content=revised,
        )
        host = runtime(profile, [read_request, wrong])
        with self.assertRaises(ContractError):
            revise_and_stage_approved_xlsx_workcopy(
                runtime=host, device=profile, source_request=read_request,
                result_request_factory=lambda content, path: file_request(
                    LocalFileOperation.WRITE, path_relative=SOURCE_PATH,
                    action_id="action_write", content=content,
                ),
                edits=(EDIT,), publisher=publisher(FakePinnedHttps()), **BASE_ARGS,
            )

        os.makedirs(os.path.dirname(self.result_on_disk), exist_ok=True)
        with open(self.result_on_disk, "wb") as handle:
            handle.write(b"already finished")
        good = file_request(
            LocalFileOperation.WRITE, path_relative=DERIVED_PATH,
            action_id="action_write", content=revised,
        )
        host = runtime(device(self.root), [read_request, good])
        with self.assertRaises(ContractError):
            revise_and_stage_approved_xlsx_workcopy(
                runtime=host, device=device(self.root), source_request=read_request,
                result_request_factory=lambda content, path: file_request(
                    LocalFileOperation.WRITE, path_relative=path,
                    action_id="action_write", content=content,
                ),
                edits=(EDIT,), publisher=publisher(FakePinnedHttps()), **BASE_ARGS,
            )
        with open(self.result_on_disk, "rb") as handle:
            self.assertEqual(handle.read(), b"already finished")

    def test_cross_run_or_device_result_request_is_refused(self) -> None:
        source = workbook_bytes()
        profile = device(self.root)
        self.write_source(source)
        read_request = file_request(
            LocalFileOperation.READ, path_relative=SOURCE_PATH, action_id="action_read",
        )
        host = runtime(profile, [read_request])
        for field, value in (("run_id", "run_other"), ("device_id", "device_other")):
            with self.subTest(**{field: value}):
                with self.assertRaises(ContractError):
                    revise_and_stage_approved_xlsx_workcopy(
                        runtime=host, device=profile, source_request=read_request,
                        result_request_factory=lambda content, path: file_request(
                            LocalFileOperation.WRITE, path_relative=path,
                            action_id="action_write", content=content, **{field: value},
                        ),
                        edits=(EDIT,), publisher=publisher(FakePinnedHttps()), **BASE_ARGS,
                    )

    def test_untrusted_source_never_reaches_the_editor(self) -> None:
        profile = device(self.root)
        self.write_source(b"not a workbook at all")
        read_request = file_request(
            LocalFileOperation.READ, path_relative=SOURCE_PATH, action_id="action_read",
        )
        host = runtime(profile, [read_request])
        with self.assertRaises(ContractError):
            revise_and_stage_approved_xlsx_workcopy(
                runtime=host, device=profile, source_request=read_request,
                result_request_factory=lambda content, path: file_request(
                    LocalFileOperation.WRITE, path_relative=path,
                    action_id="action_write", content=content,
                ),
                edits=(EDIT,), publisher=publisher(FakePinnedHttps()), **BASE_ARGS,
            )
        self.assertFalse(os.path.exists(self.result_on_disk))

    def test_staging_parts_reassemble_to_the_verified_digest(self) -> None:
        result, transport, expected = self.run_roundtrip(workbook_bytes())
        self.assertEqual(result.revised.size_bytes, len(expected))
        self.assertEqual(
            result.staging.part_count,
            (len(expected) + OFFICE_TRANSFER_CHUNK_BYTES - 1) // OFFICE_TRANSFER_CHUNK_BYTES,
        )
        for row in transport.calls:
            self.assertEqual(sha256(base64.b64decode(row["data_b64"])).hexdigest(), row["part_sha256"])
            self.assertEqual(row["integrity_ref"], result.revised.integrity_ref)
            self.assertEqual(row["run_id"], RUN)
            self.assertEqual(row["command_id"], "command_4434_xlsx")
            self.assertNotIn("destination", row)
            self.assertNotIn("drive", row)
            self.assertNotIn("path", row)
        self.assertNotIn("quote", str(transport.calls).lower())

    def test_broker_refusal_of_a_part_produces_no_receipt(self) -> None:
        source = workbook_bytes()
        self.write_source(source)
        profile = device(self.root)
        revised = PythonXlsxValueCopyEditor().revise_xlsx_copy(source, (EDIT,))
        read_request = file_request(
            LocalFileOperation.READ, path_relative=SOURCE_PATH, action_id="action_read",
        )
        write_request = file_request(
            LocalFileOperation.WRITE, path_relative=DERIVED_PATH,
            action_id="action_write", content=revised,
        )
        host = runtime(profile, [read_request, write_request])
        transport = FakePinnedHttps(deny_at=1)
        with self.assertRaises(ContractError):
            revise_and_stage_approved_xlsx_workcopy(
                runtime=host, device=profile, source_request=read_request,
                result_request_factory=lambda content, path: file_request(
                    LocalFileOperation.WRITE, path_relative=path,
                    action_id="action_write", content=content,
                ),
                edits=(EDIT,), publisher=publisher(transport), **BASE_ARGS,
            )
        # The result file exists but was never accepted for staging. An explicit
        # re-publish of the same bytes is therefore the retry, and its part
        # digests are identical, which is what the broker's exact-part replay
        # relies on. No transparent retry happens inside the publisher.
        retry = FakePinnedHttps()
        receipt = publisher(retry).publish(
            binding_ref="binding_4434_device", credential=b"device-credential-for-staging",
            command_id="command_4434_xlsx", run_id=RUN,
            artifact_id="artifact_4434_result", filename="book_revised.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            content=revised, kind="xlsx",
        )
        self.assertEqual(receipt.integrity_ref, sha256(revised).hexdigest())
        self.assertEqual([row["part_sha256"] for row in transport.calls[:1]],
                         [row["part_sha256"] for row in retry.calls[:1]])
        self.assertEqual(b"".join(base64.b64decode(row["data_b64"]) for row in sorted(
            retry.calls, key=lambda row: row["part_index"])), revised)

    def test_verifier_rejects_an_overclaimed_edit_set(self) -> None:
        source = workbook_bytes()
        one_edit = PythonXlsxValueCopyEditor().revise_xlsx_copy(source, (EDIT,))
        self.assertTrue(IndependentZipXlsxRevisionVerifier().verify_only_reviewed_edits(
            source, one_edit, (EDIT,)))
        self.assertFalse(IndependentZipXlsxRevisionVerifier().verify_only_reviewed_edits(
            source, one_edit, (EDIT, TEXT_EDIT)))

    def test_the_production_editor_fits_the_existing_revision_and_lineage_flow(self) -> None:
        """The ports in local_xlsx_revision_pdf accept the real editor and verifier."""
        source = workbook_bytes()
        result, _transport, _expected = self.run_roundtrip(source)
        pair = revise_and_render_local_xlsx_pdf(
            source=result.source, edits=(EDIT,),
            editor=PythonXlsxValueCopyEditor(),
            verifier=IndependentZipXlsxRevisionVerifier(),
            renderer=_StubRenderer(),
            workspace_ref=WORKSPACE, run_ref=RUN,
            revised_artifact_id="artifact_4434_pair_xlsx",
            pdf_artifact_id="artifact_4434_pair_pdf",
            lineage_id="lineage_4434_pair", now=NOW,
        )
        self.assertEqual(pair.public_projection()["original_preserved"], True)
        self.assertEqual(pair.revised.integrity_ref, sha256(pair.revised_bytes).hexdigest())
        self.assertEqual(pair.lineage.source.artifact_id, result.source.record.artifact_id)
        self.assertIsInstance(pair.pdf_bytes, bytes)
        self.assertEqual(load_workbook(BytesIO(pair.revised_bytes))["Quote"]["B2"].value, 91_500_000)

    def test_editor_refuses_a_missing_target_cell_and_a_formula_cell(self) -> None:
        source = workbook_bytes(formula=True)
        with self.assertRaises(OfficeFidelityRequired):
            PythonXlsxValueCopyEditor().revise_xlsx_copy(source, (EDIT,))
        plain = workbook_bytes()
        absent = ReviewedCellRevision(
            sheet_name="Quote", cell="Z99", previous_value=1, replacement_value=2,
        )
        with self.assertRaises(ContractError):
            PythonXlsxValueCopyEditor().revise_xlsx_copy(plain, (absent,))
        formula_target = ReviewedCellRevision(
            sheet_name="Quote", cell="B3", previous_value=0, replacement_value=1,
        )
        with self.assertRaises(OfficeFidelityRequired):
            PythonXlsxValueCopyEditor().revise_xlsx_copy(workbook_bytes(formula=True), (formula_target,))


class LocalXlsxEditorGuardTests(unittest.TestCase):
    """Guards that do not need a Windows disk to prove."""

    def test_dtd_or_entity_declaration_is_refused_before_parsing(self) -> None:
        parse = _parse_xml_part
        self.assertIsNotNone(parse(b"<worksheet><sheetData/></worksheet>", part_name="sheet"))
        for payload in (
            b'<!DOCTYPE x [<!ENTITY y "z">]><worksheet/>',
            b"<worksheet><!ENTITY y 'z'/></worksheet>",
            b'<!doctype x SYSTEM "http://example.test/.dtd"><worksheet/>',
        ):
            with self.subTest(payload=payload[:32]):
                with self.assertRaises(ContractError):
                    parse(payload, part_name="sheet")

    def test_part_size_bound_is_enforced(self) -> None:
        with self.assertRaises(ContractError):
            _parse_xml_part(b"<worksheet/>" + b" " * (MAX_XML_BYTES + 1), part_name="sheet")

    def test_result_path_is_only_the_derived_sibling_name(self) -> None:
        self.assertEqual(revised_path_for(r"quote\2026\book.xlsx"), r"quote\2026\book_revised.xlsx")
        for path in ("quote\\note.txt", r"C:\quote\book.xlsx", "..\\book.xlsx", "quote\\"):
            with self.subTest(path=path):
                with self.assertRaises(ContractError):
                    revised_path_for(path)

    def test_editor_inputs_are_bounded_before_any_workbook_is_opened(self) -> None:
        editor = PythonXlsxValueCopyEditor()
        for payload in (None, "", b"", b"PK\x03\x04"):
            with self.subTest(payload=repr(payload)[:24]):
                with self.assertRaises(ContractError):
                    editor.revise_xlsx_copy(payload, (EDIT,))
        with self.assertRaises(ContractError):
            editor.revise_xlsx_copy(workbook_bytes(), (EDIT, EDIT))
        with self.assertRaises(ContractError):
            editor.revise_xlsx_copy(workbook_bytes(), ())
        with self.assertRaises(ContractError):
            editor.revise_xlsx_copy(
                workbook_bytes(),
                (ReviewedCellRevision(sheet_name="Other", cell="B2",
                                       previous_value=88_000_000, replacement_value=1),),
            )

    def test_verifier_is_independent_of_the_editor_instance(self) -> None:
        source = workbook_bytes()
        revised = PythonXlsxValueCopyEditor().revise_xlsx_copy(source, (EDIT,))
        verifier = IndependentZipXlsxRevisionVerifier()
        self.assertTrue(verifier.verify_only_reviewed_edits(source, revised, (EDIT,)))
        self.assertFalse(verifier.verify_only_reviewed_edits(source, source, (EDIT,)))
        self.assertFalse(verifier.verify_only_reviewed_edits(source, b"not a workbook", (EDIT,)))
        self.assertFalse(verifier.verify_only_reviewed_edits(source, revised, ()))


if __name__ == "__main__":
    unittest.main()
