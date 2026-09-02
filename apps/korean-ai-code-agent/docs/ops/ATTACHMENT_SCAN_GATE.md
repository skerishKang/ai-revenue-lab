# Attachment Scan Gate

Issue: #1572
Parent: #1411
Base quarantine: #1501

Inbound attachments remain quarantined until both independent gates pass:

```text
AttachmentPolicy (MIME / size / count)
+
TrustedAttachmentScanReceipt (exact ID / SHA-256 / size / MIME)
+
verdict = CLEAN
+
scan time within quarantine → release window
→ RELEASED_FOR_REVIEW
```

`MALICIOUS`, `UNSCANNABLE`, missing, duplicate, mismatched, pre-quarantine, or future scan receipts fail closed.

The scan receipt stores references and hashes only. It contains no attachment body, scanner endpoint, scanner credential, or arbitrary scanner payload.

This slice does not configure or call a real scanning provider. A real scanner adapter must be selected and wired separately before live inbound attachment release.

```text
REAL_ATTACHMENT_SCANNER_CONFIGURED = NO
MALWARE_SCAN_BYPASS_SUPPORTED = NO
AUTOMATIC_BUSINESS_RECORD_CREATION = NO
PRODUCTION_MUTATION = NO
```
