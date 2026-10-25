"""#4434: the closed XLSX revision envelope, and what it is forbidden to contain.

CENTRAL fixed the attestation timing: the READ is attested when the command is
admitted, and the WRITE is attested only after the PC has produced and
independently verified the result bytes, through the existing canonical P01
evidence route keyed by that exact fingerprint. So this envelope carries one
approval — the read — plus the revision instruction, and nothing that would pass
a locally produced or web-supplied fingerprint off as a decision.

Nothing here reads a file or grants access. Real workbook bytes and the real
fingerprint and invocation-digest functions are used, so the digest the read half
names is the one the existing authority recomputes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import unittest

from padiem_ai_core.agent_approval import tool_invocation_digest

from kagent.contracts import ContractError
from kagent.local_agent_command_material import (
    XLSX_REVISION_POLICY_REF, XLSX_REVISION_RECEIPT_FORMAT,
    validate_xlsx_revision_receipt,
)
from kagent.local_xlsx_python_copy_editor import (
    IndependentZipXlsxRevisionVerifier, OfficeFidelityRequired, PythonXlsxValueCopyEditor,
)
from kagent.local_xlsx_workcopy_roundtrip import revised_path_for
from kagent.windows_local_filesystem import (
    LocalFileOperation, LocalFileRequest, file_request_fingerprint,
    windows_file_tool_invocation,
)

from test_4434_local_xlsx_workcopy_roundtrip import (
    EDIT, TEXT_EDIT, eligible_workbook_bytes, file_request,
)

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
DEVICE = "device_4434_receipt"
ROOT = "quote_root"
RUN = "run_4434_receipt"
COMMAND = "cmd_4434_receipt"
REQUEST = "req_4434_receipt"
SOURCE_PATH = "quote\\book.xlsx"
RESULT_PATH = revised_path_for(SOURCE_PATH)
WRITE_ACTION = "act_write_4434"


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def _read_request() -> LocalFileRequest:
    return file_request(LocalFileOperation.READ, path_relative=SOURCE_PATH,
                        action_id="act_read", device_id=DEVICE, root_ref=ROOT,
                        run_id=RUN, at=NOW)


def _source_approval(request: LocalFileRequest) -> dict:
    """The one half that can honestly be attested before the file is touched."""

    invocation = windows_file_tool_invocation(request)
    return {
        "approval_pause": {
            "pause_id": "pause_source",
            "run_id": request.run_id,
            "agent_runtime_id": "agent_4434",
            "tool_id": "local.filesystem.read",
            "invocation_sha256": tool_invocation_digest(invocation),
            "requirement": "user_confirmation",
            "step_index": 1,
            "created_at": _iso(NOW - timedelta(minutes=2)),
            "expires_at": _iso(NOW + timedelta(minutes=3)),
            "approval_scope": ["filesystem.read"],
        },
        "approval_decision": {
            "decision_id": "decision_source",
            "pause_id": "pause_source",
            "outcome": "approved",
            "authority_ref": "claw_connector_xlsx_revision_request_v1",
            "evidence_ref": "evidence_source",
            "decided_at": _iso(NOW - timedelta(minutes=1)),
        },
        "exact_tool_arguments": {
            "action_id": request.action_id,
            "run_id": request.run_id,
            "device_id": request.device_id,
            "root_ref": request.root_ref,
            "operation": "read",
            "path_relative": request.path_relative,
            "requested_at": _iso(request.requested_at),
            "request_fingerprint": file_request_fingerprint(request),
            "content_bytes": 0,
            "content_sha256": None,
            "directory_enumeration": False,
            "recursive_delete": False,
            "admin_elevation": False,
        },
    }


def receipt(**overrides) -> dict:
    request = _read_request()
    built = {
        "format": XLSX_REVISION_RECEIPT_FORMAT,
        "evidence_ref": "evidence_command",
        "command_id": COMMAND,
        "request_id": REQUEST,
        "local_policy_ref": XLSX_REVISION_POLICY_REF,
        "expires_at": _iso(NOW + timedelta(minutes=3)),
        "source_approval": _source_approval(request),
        "revision": {
            "sheet_name": "Quote",
            "edits": [{"cell": item.cell, "previous_value": item.previous_value,
                       "replacement_value": item.replacement_value}
                      for item in (EDIT, TEXT_EDIT)],
            "result_path_relative": RESULT_PATH,
            "write_action_id": WRITE_ACTION,
            "write_requested_at": _iso(NOW),
        },
    }
    built.update(overrides)
    return built


def _mutate(envelope: dict, path: tuple, value) -> dict:
    node = envelope
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return envelope


class XlsxRevisionEnvelopeTests(unittest.TestCase):
    def test_the_canonical_envelope_is_admitted(self) -> None:
        admitted = validate_xlsx_revision_receipt(receipt())

        self.assertEqual(admitted["format"], XLSX_REVISION_RECEIPT_FORMAT)
        args = admitted["source_approval"]["exact_tool_arguments"]
        self.assertEqual(args["operation"], "read")
        self.assertEqual(args["path_relative"], SOURCE_PATH)
        self.assertEqual(admitted["revision"]["result_path_relative"], RESULT_PATH)
        self.assertEqual(admitted["revision"]["write_action_id"], WRITE_ACTION)

    def test_the_read_half_carries_the_fingerprint_the_authority_recomputes(self) -> None:
        request = _read_request()

        self.assertEqual(
            validate_xlsx_revision_receipt(receipt())["source_approval"]
            ["exact_tool_arguments"]["request_fingerprint"],
            file_request_fingerprint(request),
        )

    def test_the_envelope_names_no_write_approval_and_no_result_digest(self) -> None:
        """The write half arrives from the evidence route, not from the wire."""

        self.assertEqual(
            set(validate_xlsx_revision_receipt(receipt())),
            {"format", "evidence_ref", "command_id", "request_id", "local_policy_ref",
             "expires_at", "source_approval", "revision"},
        )
        self.assertEqual(
            set(validate_xlsx_revision_receipt(receipt())["revision"]),
            {"sheet_name", "edits", "result_path_relative", "write_action_id",
             "write_requested_at"},
        )

    def test_a_supplied_write_approval_is_refused_rather_than_ignored(self) -> None:
        """A fingerprint nobody attested cannot be smuggled in as a decision."""

        for path, value in (
            (("result_approval",), {"approval_pause": {}, "approval_decision": {},
                                    "exact_tool_arguments": {}}),
            (("revision", "result_content_sha256"), "0" * 64),
            (("revision", "result_content_bytes"), 4994),
            (("revision", "write_approval"), {"outcome": "approved"}),
        ):
            smuggled = _mutate(receipt(), path, value)
            with self.subTest(path=path), self.assertRaises(ContractError):
                validate_xlsx_revision_receipt(smuggled)

    def test_the_read_half_must_stay_a_pre_read_intent(self) -> None:
        for field, value in (("content_bytes", 1024), ("content_sha256", "0" * 64)):
            loaded = receipt()
            loaded["source_approval"]["exact_tool_arguments"][field] = value
            with self.subTest(field=field), self.assertRaises(ContractError):
                validate_xlsx_revision_receipt(loaded)

    def test_the_write_action_must_be_distinct_from_the_read_action(self) -> None:
        reused = receipt()
        reused["revision"]["write_action_id"] = "act_read"
        with self.assertRaises(ContractError):
            validate_xlsx_revision_receipt(reused)

    def test_the_result_name_must_stay_inside_the_selected_root(self) -> None:
        for path in ("..\\other\\book.xlsx", "\\share\\book.xlsx", "C:\\x\\book.xlsx",
                     "quote/book.txt"):
            escaped = receipt()
            escaped["revision"]["result_path_relative"] = path
            with self.subTest(path=path), self.assertRaises(ContractError):
                validate_xlsx_revision_receipt(escaped)

    def test_only_the_admitted_constants_travel_on_the_envelope(self) -> None:
        for key, value in (
            ("format", "claw-txt-read-approval.v1"),
            ("local_policy_ref", "padiem_txt_selected_root_read_policy_v1"),
        ):
            mutated = receipt(**{key: value})
            with self.subTest(key=key), self.assertRaises(ContractError):
                validate_xlsx_revision_receipt(mutated)

        borrowed = receipt()
        borrowed["source_approval"]["approval_decision"]["authority_ref"] = (
            "claw_connector_txt_request_v1")
        with self.assertRaises(ContractError):
            validate_xlsx_revision_receipt(borrowed)

        read_tool = receipt()
        read_tool["source_approval"]["approval_pause"]["tool_id"] = "local.filesystem.write"
        read_tool["source_approval"]["approval_pause"]["approval_scope"] = ["filesystem.write"]
        read_tool["source_approval"]["exact_tool_arguments"]["operation"] = "write"
        with self.assertRaises(ContractError):
            validate_xlsx_revision_receipt(read_tool)

    def test_run_device_and_root_are_self_consistent_in_shape_and_correlated_later(self) -> None:
        """The envelope cannot vouch for its own ownership; the command does.

        A triple pointing at another run/device/root is a well-formed shape, so
        the shape layer admits it, and the plan source refuses it the moment it is
        bound to an admitted command. That refusal is pinned in the consumer tests
        rather than claimed here.
        """
        for path, value in (
            (("source_approval", "exact_tool_arguments", "run_id"), "run_other"),
            (("source_approval", "exact_tool_arguments", "device_id"), "device_other"),
            (("source_approval", "exact_tool_arguments", "root_ref"), "root_other"),
        ):
            foreign = _mutate(receipt(), path, value)
            with self.subTest(path=path):
                args = validate_xlsx_revision_receipt(foreign)["source_approval"][
                    "exact_tool_arguments"]
                self.assertEqual(args[path[-1]], value)

    def test_command_and_request_refs_are_bounded_refs_correlated_later(self) -> None:
        for key, value in (("command_id", "cmd_other"), ("request_id", "req_other"),
                           ("evidence_ref", "evidence_other")):
            self.assertEqual(validate_xlsx_revision_receipt(receipt(**{key: value}))[key], value)

    def test_pause_window_and_outcome_are_enforced(self) -> None:
        late = receipt()
        _mutate(late, ("source_approval", "approval_decision", "decided_at"),
                _iso(NOW + timedelta(minutes=30)))
        with self.assertRaises(ContractError):
            validate_xlsx_revision_receipt(late)

        denied = receipt()
        _mutate(denied, ("source_approval", "approval_decision", "outcome"), "denied")
        with self.assertRaises(ContractError):
            validate_xlsx_revision_receipt(denied)

        orphan = receipt()
        _mutate(orphan, ("source_approval", "approval_decision", "pause_id"), "pause_other")
        with self.assertRaises(ContractError):
            validate_xlsx_revision_receipt(orphan)


class XlsxRevisionEditsTests(unittest.TestCase):
    def test_edits_must_be_distinct_bounded_literals(self) -> None:
        cases = {
            "empty": [],
            "repeated": [{"cell": "B2", "previous_value": 88000000, "replacement_value": 1},
                         {"cell": "B2", "previous_value": 88000000, "replacement_value": 2}],
            "formula": [{"cell": "B2", "previous_value": 88000000, "replacement_value": "=B1*2"}],
            "float": [{"cell": "B2", "previous_value": 88000000, "replacement_value": 1.5}],
            "boolean": [{"cell": "B2", "previous_value": 88000000, "replacement_value": True}],
            "bad_cell": [{"cell": "b2", "previous_value": 88000000, "replacement_value": 1}],
            "extra_key": [{"cell": "B2", "previous_value": 88000000, "replacement_value": 1,
                           "path": SOURCE_PATH}],
            "empty_replacement": [{"cell": "B2", "previous_value": 88000000,
                                   "replacement_value": ""}],
        }
        for name, edits in cases.items():
            mutated = receipt()
            mutated["revision"]["edits"] = edits
            with self.subTest(case=name), self.assertRaises(ContractError):
                validate_xlsx_revision_receipt(mutated)

    def test_the_declared_edits_produce_bytes_the_independent_verifier_accepts(self) -> None:
        """The edits on the wire are the edits the PC will run and re-check."""

        source = eligible_workbook_bytes()
        revised = PythonXlsxValueCopyEditor().revise_xlsx_copy(source, (EDIT, TEXT_EDIT))

        self.assertIs(IndependentZipXlsxRevisionVerifier().verify_only_reviewed_edits(
            source, revised, (EDIT, TEXT_EDIT)), True)
        # Nothing on the envelope names these bytes; the write attestation does.
        self.assertNotIn(sha256(revised).hexdigest(), repr(
            validate_xlsx_revision_receipt(receipt())))


class XlsxRevisionRouteIndependenceTests(unittest.TestCase):
    def test_the_envelope_never_routes_and_the_classifier_always_does(self) -> None:
        """A revision envelope cannot promote a fidelity-sensitive workbook."""

        from kagent.xlsx_fidelity_route import XlsxRoute, classify_xlsx
        from openpyxl import Workbook
        from io import BytesIO

        styled = BytesIO()
        book = Workbook()
        book.active.title = "Quote"
        book.active["B2"] = 88_000_000
        book.active["C2"] = "text kept"
        book.save(styled)
        book.close()
        styled_bytes = styled.getvalue()

        self.assertIs(classify_xlsx(styled_bytes, local_only=True).route,
                      XlsxRoute.OFFICE_FALLBACK)
        # The same edits, carried by an admitted envelope, are still refused.
        with self.assertRaises(OfficeFidelityRequired):
            PythonXlsxValueCopyEditor().revise_xlsx_copy(
                styled_bytes, (EDIT,))


if __name__ == "__main__":
    unittest.main()
