"""Core tests for the shared attachment scan verdict gate (#1572).

Behavioural cases are ported from the reviewed B54-side suite
(``apps/korean-ai-code-agent/tests/test_ops_inbound_quarantine.py``) with
the original semantics kept: fail-closed release over exactly one current,
exact-binding CLEAN scan receipt per attachment. Network-free.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from padiem_ai_core.attachment_scan import (
    MALWARE_SCAN_BYPASS_SUPPORTED,
    REAL_ATTACHMENT_SCANNER_CONFIGURED,
    AttachmentMetadata,
    AttachmentScanContractError,
    AttachmentScanVerdict,
    TrustedAttachmentScanReceipt,
    require_clean_attachment_scans,
)

NOW = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)
QUARANTINED_AT = NOW - timedelta(minutes=5)


def attachment(attachment_id: str = "att-1", *, sha: str | None = None) -> AttachmentMetadata:
    return AttachmentMetadata(
        attachment_id=attachment_id,
        file_name="report.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        sha256=sha or "a" * 64,
    )


def receipt(
    att: AttachmentMetadata,
    verdict: AttachmentScanVerdict = AttachmentScanVerdict.CLEAN,
    *,
    scanned_at: datetime | None = None,
    sha: str | None = None,
) -> TrustedAttachmentScanReceipt:
    return TrustedAttachmentScanReceipt.from_attachment(
        scan_id=f"scan-{att.attachment_id}",
        attachment=att,
        verdict=verdict,
        scanned_at=scanned_at or (QUARANTINED_AT + timedelta(seconds=30)),
        scanner_policy_ref="scanner-policy:default@1",
        authority_ref="authority:scanner@1",
        evidence_ref="evidence:scan@1",
    )


def test_real_scanner_engine_is_absent_and_no_bypass_exists() -> None:
    assert REAL_ATTACHMENT_SCANNER_CONFIGURED is False
    assert MALWARE_SCAN_BYPASS_SUPPORTED is False


def test_verdict_enum_is_bounded_to_three_trusted_values() -> None:
    assert {item.value for item in AttachmentScanVerdict} == {"clean", "malicious", "unscannable"}


def test_clean_single_attachment_releases() -> None:
    att = attachment()
    require_clean_attachment_scans((att,), (receipt(att),))


def test_missing_scan_receipt_blocks_release() -> None:
    att = attachment()
    with pytest.raises(AttachmentScanContractError, match="exactly one scan receipt"):
        require_clean_attachment_scans((att,), ())


def test_duplicate_scan_receipt_blocks_release() -> None:
    att = attachment()
    with pytest.raises(AttachmentScanContractError, match="duplicate"):
        require_clean_attachment_scans((att,), (receipt(att), receipt(att)))


def test_mismatched_receipt_hash_blocks_release() -> None:
    att = attachment()
    wrong = attachment(sha="b" * 64)
    with pytest.raises(AttachmentScanContractError, match="does not match"):
        require_clean_attachment_scans((att,), (receipt(wrong),))


def test_mismatched_receipt_size_or_mime_blocks_release() -> None:
    att = attachment()
    wrong_size = AttachmentMetadata(
        attachment_id=att.attachment_id,
        file_name=att.file_name,
        mime_type=att.mime_type,
        size_bytes=att.size_bytes + 1,
        sha256=att.sha256,
    )
    with pytest.raises(AttachmentScanContractError, match="does not match"):
        require_clean_attachment_scans((att,), (receipt(wrong_size),))
    wrong_mime = AttachmentMetadata(
        attachment_id=att.attachment_id,
        file_name=att.file_name,
        mime_type="text/html",
        size_bytes=att.size_bytes,
        sha256=att.sha256,
    )
    with pytest.raises(AttachmentScanContractError, match="does not match"):
        require_clean_attachment_scans((att,), (receipt(wrong_mime),))


def test_malicious_verdict_blocks_release() -> None:
    att = attachment()
    with pytest.raises(AttachmentScanContractError, match="only CLEAN"):
        require_clean_attachment_scans((att,), (receipt(att, AttachmentScanVerdict.MALICIOUS),))


def test_unscannable_verdict_blocks_release() -> None:
    att = attachment()
    with pytest.raises(AttachmentScanContractError, match="only CLEAN"):
        require_clean_attachment_scans((att,), (receipt(att, AttachmentScanVerdict.UNSCANNABLE),))


def test_message_without_attachments_releases_without_receipts() -> None:
    require_clean_attachment_scans((), ())


def test_receipts_for_message_without_attachments_block_release() -> None:
    att = attachment()
    with pytest.raises(AttachmentScanContractError, match="without attachments"):
        require_clean_attachment_scans((), (receipt(att),))


def test_extra_receipt_beyond_attachments_blocks_release() -> None:
    att = attachment()
    other = attachment("att-2")
    with pytest.raises(AttachmentScanContractError, match="exactly one scan receipt"):
        require_clean_attachment_scans((att,), (receipt(att), receipt(other)))


def test_stale_scan_predating_quarantine_blocks_release() -> None:
    att = attachment()
    stale = receipt(att, scanned_at=QUARANTINED_AT - timedelta(seconds=1))
    with pytest.raises(AttachmentScanContractError, match="predate quarantine"):
        require_clean_attachment_scans(
            (att,),
            (stale,),
            quarantined_at=QUARANTINED_AT,
            released_at=NOW,
        )


def test_future_scan_blocks_release() -> None:
    att = attachment()
    future = receipt(att, scanned_at=NOW + timedelta(seconds=1))
    with pytest.raises(AttachmentScanContractError, match="from the future"):
        require_clean_attachment_scans(
            (att,),
            (future,),
            quarantined_at=QUARANTINED_AT,
            released_at=NOW,
        )


def test_current_time_bounds_pass_for_fresh_scan() -> None:
    att = attachment()
    require_clean_attachment_scans(
        (att,),
        (receipt(att),),
        quarantined_at=QUARANTINED_AT,
        released_at=NOW,
    )


def test_partial_time_bounds_are_rejected() -> None:
    att = attachment()
    with pytest.raises(AttachmentScanContractError, match="together"):
        require_clean_attachment_scans(
            (att,),
            (receipt(att),),
            quarantined_at=QUARANTINED_AT,
        )


def test_naive_scan_timestamp_is_rejected() -> None:
    with pytest.raises(AttachmentScanContractError, match="timezone-aware"):
        TrustedAttachmentScanReceipt.from_attachment(
            scan_id="scan-1",
            attachment=attachment(),
            verdict=AttachmentScanVerdict.CLEAN,
            scanned_at=datetime(2026, 9, 8, 12, 0, 0),
            scanner_policy_ref="scanner-policy:default@1",
            authority_ref="authority:scanner@1",
            evidence_ref="evidence:scan@1",
        )


def test_invalid_verdict_string_is_rejected() -> None:
    with pytest.raises(AttachmentScanContractError, match="invalid attachment scan verdict"):
        TrustedAttachmentScanReceipt(
            scan_id="scan-1",
            attachment_id="att-1",
            attachment_sha256="a" * 64,
            size_bytes=1024,
            mime_type="application/pdf",
            verdict="probably_fine",
            scanned_at=NOW,
            scanner_policy_ref="scanner-policy:default@1",
            authority_ref="authority:scanner@1",
            evidence_ref="evidence:scan@1",
        )


def test_sha256_case_is_normalized_and_invalid_digests_are_rejected() -> None:
    att = AttachmentMetadata(
        attachment_id="att-1",
        file_name="report.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        sha256="A" * 64,
    )
    assert att.sha256 == "a" * 64
    with pytest.raises(AttachmentScanContractError, match="SHA-256"):
        AttachmentMetadata(
            attachment_id="att-1",
            file_name="report.pdf",
            mime_type="application/pdf",
            size_bytes=1024,
            sha256="a" * 63,
        )
    with pytest.raises(AttachmentScanContractError, match="SHA-256"):
        AttachmentMetadata(
            attachment_id="att-1",
            file_name="report.pdf",
            mime_type="application/pdf",
            size_bytes=1024,
            sha256="g" * 64,
        )
    with pytest.raises(AttachmentScanContractError, match="SHA-256"):
        TrustedAttachmentScanReceipt(
            scan_id="scan-1",
            attachment_id="att-1",
            attachment_sha256="a" * 63,
            size_bytes=1024,
            mime_type="application/pdf",
            verdict=AttachmentScanVerdict.CLEAN,
            scanned_at=NOW,
            scanner_policy_ref="scanner-policy:default@1",
            authority_ref="authority:scanner@1",
            evidence_ref="evidence:scan@1",
        )


def test_safe_projection_carries_no_content_endpoint_or_credential() -> None:
    att = attachment()
    projection = receipt(att).safe_dict()
    assert projection["attachment_content"] is False
    assert projection["scanner_endpoint"] is False
    assert projection["scanner_credential"] is False
    assert projection["verdict"] == "clean"
    meta = att.safe_dict()
    assert meta["attachment_content"] is False
    assert meta["storage_location"] is False


def test_negative_size_is_rejected() -> None:
    with pytest.raises(AttachmentScanContractError, match="non-negative"):
        AttachmentMetadata(
            attachment_id="att-1",
            file_name="report.pdf",
            mime_type="application/pdf",
            size_bytes=-1,
            sha256="a" * 64,
        )
