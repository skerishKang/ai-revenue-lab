"""#4434: the Broker admits the same XLSX revision envelope the PC admits.

One closed format, two implementations. These tests pin the bilateral constants
and the same accept/refuse decisions key for key, so neither side can quietly
widen what may ride a command to a customer PC. No file is read and no approval is
granted: this is shape admission at the store boundary.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from local_agent_broker_material_store import (
    XLSX_REVISION_AUTHORITY_REF, XLSX_REVISION_POLICY_REF,
    XLSX_REVISION_RECEIPT_FORMAT, validate_xlsx_revision_receipt,
)

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
DEVICE = "device_4434_store"
ROOT = "quote_root"
RUN = "run_4434_store"
COMMAND = "cmd_4434_store"
REQUEST = "req_4434_store"
SOURCE_PATH = "quote\\book.xlsx"
RESULT_PATH = "quote\\book_revised.xlsx"


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def envelope() -> dict:
    return {
        "format": XLSX_REVISION_RECEIPT_FORMAT,
        "evidence_ref": "evidence_command",
        "command_id": COMMAND,
        "request_id": REQUEST,
        "local_policy_ref": XLSX_REVISION_POLICY_REF,
        "expires_at": _iso(NOW + timedelta(minutes=3)),
        "source_approval": {
            "approval_pause": {
                "pause_id": "pause_source", "run_id": RUN,
                "agent_runtime_id": "agent_4434",
                "tool_id": "local.filesystem.read",
                "invocation_sha256": "a" * 64, "requirement": "user_confirmation",
                "step_index": 1,
                "created_at": _iso(NOW - timedelta(minutes=2)),
                "expires_at": _iso(NOW + timedelta(minutes=3)),
                "approval_scope": ["filesystem.read"],
            },
            "approval_decision": {
                "decision_id": "decision_source", "pause_id": "pause_source",
                "outcome": "approved",
                "authority_ref": XLSX_REVISION_AUTHORITY_REF,
                "evidence_ref": "evidence_source",
                "decided_at": _iso(NOW - timedelta(minutes=1)),
            },
            "exact_tool_arguments": {
                "action_id": "act_read", "run_id": RUN, "device_id": DEVICE,
                "root_ref": ROOT, "operation": "read", "path_relative": SOURCE_PATH,
                "requested_at": _iso(NOW - timedelta(minutes=1)),
                "request_fingerprint": "b" * 64, "content_bytes": 0,
                "content_sha256": None, "directory_enumeration": False,
                "recursive_delete": False, "admin_elevation": False,
            },
        },
        "revision": {
            "sheet_name": "Quote",
            "edits": [{"cell": "B2", "previous_value": 88000000, "replacement_value": 91500000}],
            "result_path_relative": RESULT_PATH,
            "write_action_id": "act_write",
            "write_requested_at": _iso(NOW),
        },
    }


def test_the_canonical_envelope_is_admitted():
    admitted = validate_xlsx_revision_receipt(envelope())

    assert admitted["revision"]["result_path_relative"] == RESULT_PATH
    assert admitted["source_approval"]["exact_tool_arguments"]["operation"] == "read"


#: Each case is refused at the store boundary. The Resident refuses the identical
#: set — tests/test_4434_xlsx_revision_receipt_contract.py pins that half, and a
#: third test pins the shared constants by reading this file's source.
@pytest.mark.parametrize(
    "path,value,expect",
    [
        (("format",), "claw-txt-read-approval.v1", "format mismatch"),
        (("local_policy_ref",), "padiem_txt_selected_root_read_policy_v1", "policy mismatch"),
        (("source_approval", "approval_pause", "tool_id"), "local.filesystem.write", "tool mismatch"),
        (("source_approval", "approval_pause", "approval_scope"), ["filesystem.write"], "scope mismatch"),
        (("source_approval", "exact_tool_arguments", "operation"), "write", "operation mismatch"),
        (("source_approval", "exact_tool_arguments", "content_bytes"), 2048, "pre-read intent"),
        (("source_approval", "exact_tool_arguments", "content_sha256"), "0" * 64, "pre-read intent"),
        (("source_approval", "approval_decision", "outcome"), "denied", "outcome mismatch"),
        (("source_approval", "approval_decision", "authority_ref"), "claw_connector_txt_request_v1", "authority mismatch"),
        (("revision", "result_path_relative"), "..\\x\\book.xlsx", "selected root"),
        (("revision", "result_path_relative"), "C:\\x\\book.xlsx", "selected root"),
        (("revision", "result_path_relative"), "quote\\book.txt", "selected root"),
        (("revision", "write_action_id"), "act_read", "distinct actions"),
        (("revision", "edits"), [], "bounded non-empty"),
        (("revision", "edits"), [{"cell": "B2", "previous_value": 1, "replacement_value": 1},
                                 {"cell": "B2", "previous_value": 1, "replacement_value": 2}],
         "repeated"),
        (("revision", "edits"), [{"cell": "B2", "previous_value": 1, "replacement_value": "=SUM(1)"}],
         "bounded literal"),
        (("revision", "edits"), [{"cell": "B2", "previous_value": 1, "replacement_value": 1.5}],
         "literal"),
        (("revision", "edits"), [{"cell": "b2", "previous_value": 1, "replacement_value": 2}],
         "A1 reference"),
    ],
)
def test_malformed_revision_envelopes_are_refused_at_the_store(path, value, expect):
    def mutate(candidate):
        node = candidate
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
        return candidate

    broken = mutate(envelope())
    with pytest.raises(ValueError, match=expect):
        validate_xlsx_revision_receipt(broken)



def test_a_write_approval_cannot_ride_the_wire():
    """Extra write-side material is refused, not ignored, at the store."""

    for extra in ({"result_approval": {"approval_pause": {}, "approval_decision": {},
                                       "exact_tool_arguments": {}}},
                  {"revision": {**envelope()["revision"], "result_content_sha256": "0" * 64}}):
        smuggled = {**envelope(), **extra}
        with pytest.raises(ValueError):
            validate_xlsx_revision_receipt(smuggled)
