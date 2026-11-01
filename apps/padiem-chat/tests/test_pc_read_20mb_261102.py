"""#5882 A: a PC read answer has no 20 MB product cap of its own.

The audit (LIMITS_AUDIT_2_20261102 §4-2) found the same 20 MB number in four
places on the PC read path. Server-side (Chat here) two of them are the read
body's verification and storage bounds; both refused a body the connector had
already produced and the digest had already proved. A file larger than one
answer is now paged by the Engine from its first range, so this lane only needs
to verify the bytes it actually received.

The bound Chat still sends to an installed connector is the *connector's* read
envelope, not a product limit: an executor refuses a bound above its own, so
raising it needs a new connector version (reported separately).
"""
from __future__ import annotations

import hashlib

import app.oracle_mesh_read_return_routes as routes
from app.history import (
    ORACLE_MESH_ORIGINAL_MAX_BYTES,
    _oracle_mesh_original_max_bytes,
)

READ_ROW = {"kind": "read", "root_ref": "pc_files_read"}
OTHER_READ_ROW = {"kind": "read", "root_ref": "meshcentral_private_trial"}
COMMAND_ROW = {"kind": "command", "root_ref": "pc_files_read"}


def _wire(text: str) -> dict:
    raw = text.encode("utf-8")
    return {
        "content_utf8": text,
        "content_bytes": len(raw),
        "content_sha256": hashlib.sha256(raw).hexdigest(),
    }


def test_exactly_twenty_mb_is_a_normal_whole_answer():
    text = "x" * routes.PC_FILES_READ_MAX_BYTES
    assert routes._verified_read_result_text(READ_ROW, _wire(text)) == text


def test_one_byte_over_the_old_cap_is_verified_not_refused():
    text = "x" * (routes.PC_FILES_READ_MAX_BYTES + 1)
    assert routes._verified_read_result_text(READ_ROW, _wire(text)) == text


def test_a_hundred_mb_mock_answer_is_verified_not_refused():
    text = "가" * 40_000_000  # 120 MB of UTF-8: larger than any old cap.
    verified = routes._verified_read_result_text(READ_ROW, _wire(text))
    assert verified is not None and len(verified) == len(text)


def test_a_tampered_body_is_still_refused():
    wire = _wire("x" * 10)
    wire["content_bytes"] = 9
    assert routes._verified_read_result_text(READ_ROW, wire) is None
    wire = _wire("x" * 10)
    wire["content_sha256"] = "0" * 64
    assert routes._verified_read_result_text(READ_ROW, wire) is None


def test_other_read_lanes_are_unchanged_by_this_removal():
    # This deployment sets no module-wide text bound for other read lanes; the
    # PC read lane's 20 MB cap was the only read-specific number, and it is
    # gone. If that shared constant ever gains a value, this pins the change.
    assert routes._MAX_FILE_TEXT_BYTES is None
    text = "x" * 7_000_000
    assert routes._verified_read_result_text(OTHER_READ_ROW, _wire(text)) == text


def test_the_store_has_no_pc_read_cap_and_keeps_the_others():
    assert _oracle_mesh_original_max_bytes(READ_ROW) is None
    assert _oracle_mesh_original_max_bytes(COMMAND_ROW) == ORACLE_MESH_ORIGINAL_MAX_BYTES
    assert _oracle_mesh_original_max_bytes(OTHER_READ_ROW) == ORACLE_MESH_ORIGINAL_MAX_BYTES


def test_the_poll_bound_is_the_connector_envelope_and_unchanged():
    row = {"kind": "read", "root_ref": routes._PC_FILES_READ_ROOT_REF}
    assert routes._oracle_mesh_poll_max_bytes(row) == routes.PC_FILES_READ_MAX_BYTES
    # A read that is not this lane's still carries no product bound.
    assert routes._oracle_mesh_poll_max_bytes(
        {"kind": "read", "root_ref": "meshcentral_private_trial"},
    ) is None
