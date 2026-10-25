"""#4434: the closed XLSX revision approval envelope the PC will accept.

Nothing here reads a file or grants access. These tests pin the one shape a
revision command may carry to a customer PC: two complete pause/decision pairs
(one read, one write), a literal edit list, and the result bytes named by digest
before they exist. The Chat worker and the Broker must produce this key for key;
until something does, no command resolves with a revision receipt and the lane
stays off, so admitting the shape changes no behaviour.

Real workbook bytes and the real file-request fingerprint function are used, so
the digest the envelope names is the one the existing authority recomputes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from kagent.contracts import ContractError
from kagent.local_agent_command_material import (
    XLSX_REVISION_POLICY_REF, XLSX_REVISION_RECEIPT_FORMAT,
    validate_xlsx_revision_receipt,
)
from kagent.local_xlsx_python_copy_editor import (
    IndependentZipXlsxRevisionVerifier, PythonXlsxValueCopyEditor,
)
from kagent.windows_local_filesystem import (
    LocalFileOperation, LocalFileRequest, file_request_fingerprint,
    windows_file_tool_invocation,
)
from kagent.local_agent_permissions import LocalCapability

from test_4434_local_xlsx_workcopy_roundtrip import (
    EDIT, TEXT_EDIT, file_request, workbook_bytes,
)

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
DEVICE = "device_4434_receipt"
ROOT = "quote_root"
RUN = "run_4434_receipt"
COMMAND = "cmd_4434_receipt"
REQUEST = "req_4434_receipt"
SOURCE_PATH = "quote\\book.xlsx"
RESULT_PATH = "quote\\book_revised.xlsx"


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def _pair(*, request: LocalFileRequest, side: str, edits: bool) -> dict:
    """One canonical pause/decision/arguments triple for one file request."""

    invocation = windows_file_tool_invocation(request)
    tool_id = "local.filesystem.read" if side == "source" else "local.filesystem.write"
    scope = ["filesystem.read"] if side == "source" else ["filesystem.write"]
    return {
        "approval_pause": {
            "pause_id": f"pause_{side}",
            "run_id": request.run_id,
            "agent_runtime_id": "agent_4434",
            "tool_id": tool_id,
            "invocation_sha256": _digest_of(invocation),
            "requirement": "user_confirmation",
            "step_index": 1 if side == "source" else 2,
            "created_at": _iso(NOW - timedelta(minutes=2)),
            "expires_at": _iso(NOW + timedelta(minutes=3)),
            "approval_scope": scope,
        },
        "approval_decision": {
            "decision_id": f"decision_{side}",
            "pause_id": f"pause_{side}",
            "outcome": "approved",
            "authority_ref": "claw_connector_xlsx_revision_request_v1",
            "evidence_ref": f"evidence_{side}",
            "decided_at": _iso(NOW - timedelta(minutes=1)),
        },
        "exact_tool_arguments": {
            "action_id": request.action_id,
            "run_id": request.run_id,
            "device_id": request.device_id,
            "root_ref": request.root_ref,
            "operation": "read" if side == "source" else "write",
            "path_relative": request.path_relative,
            "requested_at": _iso(request.requested_at),
            "request_fingerprint": file_request_fingerprint(request),
            "content_bytes": 0 if side == "source" else len(request.content or b""),
            "content_sha256": None if side == "source" else _sha(request.content or b""),
            "directory_enumeration": False,
            "recursive_delete": False,
            "admin_elevation": False,
        },
    }


def _sha(data: bytes) -> str:
    from hashlib import sha256

    return sha256(data).hexdigest()


def _digest_of(invocation) -> str:
    from padiem_ai_core.agent_approval import tool_invocation_digest

    return tool_invocation_digest(invocation)


def _requests(edits=(EDIT, TEXT_EDIT)):
    """The real read/write pair over real workbook bytes."""

    source_bytes = workbook_bytes()
    revised = PythonXlsxValueCopyEditor().revise_xlsx_copy(source_bytes, edits)
    read = file_request(LocalFileOperation.READ, path_relative=SOURCE_PATH,
                        action_id="act_read", device_id=DEVICE, root_ref=ROOT,
                        run_id=RUN, at=NOW)
    write = file_request(LocalFileOperation.WRITE, path_relative=RESULT_PATH,
                         action_id="act_write", content=revised, device_id=DEVICE,
                         root_ref=ROOT, run_id=RUN, at=NOW)
    return source_bytes, revised, read, write


def receipt(*, edits=(EDIT, TEXT_EDIT), **overrides) -> dict:
    _, revised, read, write = _requests(edits)
    built = {
        "format": XLSX_REVISION_RECEIPT_FORMAT,
        "evidence_ref": "evidence_command",
        "command_id": COMMAND,
        "request_id": REQUEST,
        "local_policy_ref": XLSX_REVISION_POLICY_REF,
        "expires_at": _iso(NOW + timedelta(minutes=3)),
        "source_approval": _pair(request=read, side="source", edits=edits),
        "result_approval": _pair(request=write, side="result", edits=edits),
        "revision": {
            "sheet_name": "Quote",
            "edits": [{"cell": e.cell, "previous_value": e.previous_value,
                       "replacement_value": e.replacement_value} for e in edits],
            "result_path_relative": RESULT_PATH,
        },
    }
    built.update(overrides)
    return built


class XlsxRevisionReceiptShapeTests(unittest.TestCase):
    def test_the_canonical_pair_is_admitted_and_reports_the_write_digest(self) -> None:
        admitted = validate_xlsx_revision_receipt(receipt())

        self.assertEqual(admitted["format"], XLSX_REVISION_RECEIPT_FORMAT)
        write_args = admitted["result_approval"]["exact_tool_arguments"]
        self.assertEqual(write_args["path_relative"], RESULT_PATH)
        # The digest named here is the one the editor actually produces, so the
        # approved write and the verified bytes are comparable later.
        self.assertEqual(write_args["content_sha256"], _sha(
            PythonXlsxValueCopyEditor().revise_xlsx_copy(workbook_bytes(), (EDIT, TEXT_EDIT))))
        self.assertGreater(write_args["content_bytes"], 0)

    def test_the_result_bytes_are_verified_against_the_edits_by_the_same_editor(self) -> None:
        source_bytes, revised, _, _ = _requests()
        verifier = IndependentZipXlsxRevisionVerifier()

        self.assertTrue(verifier.verify_only_reviewed_edits(
            source_bytes, revised, (EDIT, TEXT_EDIT)))
        # An under-declared edit set is refused: B2 changed but is not reviewed,
        # so the bytes the receipt names would not be the bytes verified.
        self.assertFalse(verifier.verify_only_reviewed_edits(
            source_bytes, revised, (TEXT_EDIT,)))
        self.assertFalse(verifier.verify_only_reviewed_edits(
            source_bytes, revised, (EDIT,)))

    def test_the_command_fields_are_bounded_refs_correlated_later(self) -> None:
        """The shape layer admits any well-formed ref; the plan source correlates.

        Mirrors the TXT envelope: a receipt that names a foreign command is not
        rejected here, it is rejected when it is bound to an admitted command.
        """
        for key, value in (
            ("command_id", "cmd_other"), ("request_id", "req_other"),
            ("evidence_ref", "evidence_other"),
        ):
            mutated = receipt(**{key: value})
            with self.subTest(key=key):
                self.assertEqual(validate_xlsx_revision_receipt(mutated)[key], value)

    def test_the_constants_that_cannot_be_reused_are_enforced(self) -> None:
        for key, value in (
            ("format", "claw-txt-read-approval.v1"),
            ("local_policy_ref", "padiem_txt_selected_root_read_policy_v1"),
        ):
            mutated = receipt(**{key: value})
            with self.subTest(key=key), self.assertRaises(ContractError):
                validate_xlsx_revision_receipt(mutated)
        borrowed = receipt()
        borrowed["result_approval"]["approval_decision"]["authority_ref"] = (
            "claw_connector_txt_request_v1")
        with self.assertRaises(ContractError):
            validate_xlsx_revision_receipt(borrowed)

    def test_the_write_half_names_the_capability_the_authority_recomputes(self) -> None:
        _, _, _, write = _requests()

        self.assertIs(write.capability, LocalCapability.FILESYSTEM_WRITE)
        admitted = validate_xlsx_revision_receipt(receipt())
        self.assertEqual(admitted["result_approval"]["approval_pause"]["approval_scope"],
                         ["filesystem.write"])

class XlsxRevisionReceiptRefusalTests(unittest.TestCase):
    def test_extra_or_missing_top_level_keys_are_refused(self) -> None:
        broadened = receipt()
        broadened["device_credential_b64"] = "aGVsbG8="
        with self.assertRaises(ContractError):
            validate_xlsx_revision_receipt(broadened)
        for key in sorted(receipt()):
            narrowed = receipt()
            del narrowed[key]
            with self.subTest(key=key), self.assertRaises(ContractError):
                validate_xlsx_revision_receipt(narrowed)

    def test_one_decision_cannot_authorize_both_file_accesses(self) -> None:
        """The existing P01 authority consumes one decision per file access."""

        shared = receipt()
        shared["result_approval"]["approval_decision"]["decision_id"] = (
            shared["source_approval"]["approval_decision"]["decision_id"])
        with self.assertRaises(ContractError):
            validate_xlsx_revision_receipt(shared)

        shared_pause = receipt()
        shared_pause["result_approval"]["approval_pause"]["pause_id"] = (
            shared_pause["source_approval"]["approval_pause"]["pause_id"])
        shared_pause["result_approval"]["approval_decision"]["pause_id"] = (
            shared_pause["source_approval"]["approval_pause"]["pause_id"])
        with self.assertRaises(ContractError):
            validate_xlsx_revision_receipt(shared_pause)

    def test_the_read_half_cannot_be_asked_to_write(self) -> None:
        swapped = receipt()
        swapped["source_approval"]["exact_tool_arguments"]["operation"] = "write"
        with self.assertRaises(ContractError):
            validate_xlsx_revision_receipt(swapped)

        mislabelled = receipt()
        mislabelled["result_approval"]["approval_pause"]["tool_id"] = "local.filesystem.read"
        mislabelled["result_approval"]["approval_pause"]["approval_scope"] = ["filesystem.read"]
        with self.assertRaises(ContractError):
            validate_xlsx_revision_receipt(mislabelled)

    def test_the_source_half_must_stay_a_pre_read_intent(self) -> None:
        loaded = receipt()
        loaded["source_approval"]["exact_tool_arguments"]["content_bytes"] = 1024
        with self.assertRaises(ContractError):
            validate_xlsx_revision_receipt(loaded)

        empty_result = receipt()
        empty_result["result_approval"]["exact_tool_arguments"]["content_bytes"] = 0
        with self.assertRaises(ContractError):
            validate_xlsx_revision_receipt(empty_result)

    def test_paths_outside_the_selected_root_are_refused(self) -> None:
        for path in ("..\\other\\book.xlsx", "\\share\\book.xlsx",
                     "C:\\reports\\book.xlsx", "quote/book.txt"):
            escaped = receipt()
            escaped["revision"]["result_path_relative"] = path
            escaped["result_approval"]["exact_tool_arguments"]["path_relative"] = path
            with self.subTest(path=path), self.assertRaises(ContractError):
                validate_xlsx_revision_receipt(escaped)

    def test_the_named_result_path_must_be_the_approved_write_path(self) -> None:
        divergent = receipt()
        divergent["revision"]["result_path_relative"] = "quote\\other_revised.xlsx"
        with self.assertRaises(ContractError):
            validate_xlsx_revision_receipt(divergent)

    def test_edits_must_be_distinct_bounded_literals(self) -> None:
        cases = {
            "empty": [],
            "repeated": [{"cell": "B2", "previous_value": 88000000, "replacement_value": 90000000},
                         {"cell": "B2", "previous_value": 88000000, "replacement_value": 91000000}],
            "formula": [{"cell": "B2", "previous_value": 88000000, "replacement_value": "=B1*2"}],
            "float": [{"cell": "B2", "previous_value": 88000000, "replacement_value": 1.5}],
            "boolean": [{"cell": "B2", "previous_value": 88000000, "replacement_value": True}],
            "bad_cell": [{"cell": "b2", "previous_value": 88000000, "replacement_value": 1}],
            "extra_key": [{"cell": "B2", "previous_value": 88000000,
                           "replacement_value": 1, "path": "quote\\book.xlsx"}],
            "empty_replacement": [{"cell": "B2", "previous_value": 88000000,
                                   "replacement_value": ""}],
        }
        for name, edits in cases.items():
            mutated = receipt()
            mutated["revision"]["edits"] = edits
            with self.subTest(case=name), self.assertRaises(ContractError):
                validate_xlsx_revision_receipt(mutated)

    def test_the_result_fingerprint_is_the_one_the_authority_will_recompute(self) -> None:
        """Positive binding: the envelope names the fingerprint the port derives.

        The shape layer admits a digest of the right form; the plan source is what
        refuses when it no longer matches the request it recomputes.
        """
        _, _, _, write = _requests()
        admitted = validate_xlsx_revision_receipt(receipt())

        self.assertEqual(
            admitted["result_approval"]["exact_tool_arguments"]["request_fingerprint"],
            file_request_fingerprint(write),
        )
        malformed = receipt()
        malformed["result_approval"]["exact_tool_arguments"]["request_fingerprint"] = "zz" * 32
        with self.assertRaises(ContractError):
            validate_xlsx_revision_receipt(malformed)

    def test_pause_window_and_decision_ordering_are_enforced(self) -> None:
        late = receipt()
        late["result_approval"]["approval_decision"]["decided_at"] = _iso(
            NOW + timedelta(minutes=30))
        with self.assertRaises(ContractError):
            validate_xlsx_revision_receipt(late)

        inverted = receipt()
        inverted["source_approval"]["approval_pause"]["created_at"] = _iso(NOW)
        inverted["source_approval"]["approval_pause"]["expires_at"] = _iso(NOW - timedelta(seconds=1))
        with self.assertRaises(ContractError):
            validate_xlsx_revision_receipt(inverted)

    def test_deny_is_never_an_admitted_outcome(self) -> None:
        denied = receipt()
        denied["result_approval"]["approval_decision"]["outcome"] = "denied"
        with self.assertRaises(ContractError):
            validate_xlsx_revision_receipt(denied)

    def test_the_receipt_admits_no_path_authority_or_credential_fields(self) -> None:
        """Only the closed keys survive; nothing names a device root or secret."""

        admitted = validate_xlsx_revision_receipt(receipt())

        self.assertEqual(
            set(admitted),
            {"format", "evidence_ref", "command_id", "request_id", "local_policy_ref",
             "expires_at", "source_approval", "result_approval", "revision"},
        )
        for args in (admitted["source_approval"]["exact_tool_arguments"],
                     admitted["result_approval"]["exact_tool_arguments"]):
            # Relative to the selected root only: no drive, no UNC, no absolute path.
            path = args["path_relative"]
            self.assertFalse(path.startswith("\\"))
            self.assertNotIn(":", path)
            self.assertNotIn("..", path)
            self.assertTrue(path.lower().endswith(".xlsx"))
            self.assertNotIn("credential", repr(args))


if __name__ == "__main__":
    unittest.main()
