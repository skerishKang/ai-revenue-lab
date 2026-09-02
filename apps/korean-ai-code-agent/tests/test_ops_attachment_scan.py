from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import unittest

from kagent.contracts import ContractError
from kagent.ops_attachment_scan import (
    MALWARE_SCAN_BYPASS_SUPPORTED,
    REAL_ATTACHMENT_SCANNER_CONFIGURED,
    AttachmentScanVerdict,
    TrustedAttachmentScanReceipt,
    require_clean_attachment_scans,
)
from kagent.ops_communications import AttachmentMetadata


NOW = datetime(2026, 9, 3, 2, 0, tzinfo=timezone.utc)
SHA = hashlib.sha256(b"document").hexdigest()


def attachment(**kwargs) -> AttachmentMetadata:
    values = dict(
        attachment_id="att_1",
        file_name="quote.pdf",
        mime_type="application/pdf",
        size_bytes=128,
        sha256=SHA,
    )
    values.update(kwargs)
    return AttachmentMetadata(**values)


def receipt(item: AttachmentMetadata, **kwargs) -> TrustedAttachmentScanReceipt:
    values = dict(
        scan_id="scan_1",
        attachment=item,
        verdict=AttachmentScanVerdict.CLEAN,
        scanned_at=NOW,
        scanner_policy_ref="scanner_policy_v1",
        authority_ref="scanner_authority_1",
        evidence_ref="scanner_evidence_1",
    )
    values.update(kwargs)
    return TrustedAttachmentScanReceipt.from_attachment(**values)


class AttachmentScanTests(unittest.TestCase):
    def test_clean_receipt_is_exact_metadata_bound_and_safe(self):
        item = attachment()
        scan = receipt(item)
        self.assertTrue(scan.matches(item))
        rendered = scan.safe_dict()
        self.assertEqual(rendered["attachment_sha256"], item.sha256)
        self.assertEqual(rendered["verdict"], "clean")
        self.assertFalse(rendered["attachment_content"])
        self.assertFalse(rendered["scanner_endpoint"])
        self.assertFalse(rendered["scanner_credential"])
        require_clean_attachment_scans((item,), (scan,))

    def test_missing_extra_duplicate_and_nonclean_receipts_fail_closed(self):
        item = attachment()
        with self.assertRaises(ContractError):
            require_clean_attachment_scans((item,), ())
        with self.assertRaises(ContractError):
            require_clean_attachment_scans((), (receipt(item),))
        first = receipt(item)
        second = receipt(item, scan_id="scan_2", evidence_ref="scanner_evidence_2")
        with self.assertRaises(ContractError):
            require_clean_attachment_scans((item,), (first, second))
        for verdict in (AttachmentScanVerdict.MALICIOUS, AttachmentScanVerdict.UNSCANNABLE):
            with self.assertRaises(ContractError):
                require_clean_attachment_scans((item,), (receipt(item, verdict=verdict),))

    def test_hash_size_and_mime_mismatch_fail_closed(self):
        item = attachment()
        variants = (
            attachment(sha256=hashlib.sha256(b"changed").hexdigest()),
            attachment(size_bytes=129),
            attachment(mime_type="text/plain"),
        )
        for variant in variants:
            with self.assertRaises(ContractError):
                require_clean_attachment_scans((item,), (receipt(variant),))

    def test_scanner_is_not_claimed_and_bypass_is_unsupported(self):
        self.assertFalse(REAL_ATTACHMENT_SCANNER_CONFIGURED)
        self.assertFalse(MALWARE_SCAN_BYPASS_SUPPORTED)


if __name__ == "__main__":
    unittest.main()
