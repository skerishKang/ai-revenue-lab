# #3580 — Private durable Engine-approved Office READ evidence ledger

Date: 2026-10-11 KST

## Source milestone and limitations

The existing first-party Engine approval verification / continuation-consumption
logic from #4215 now has an **optional**, server-injected SQLite-backed
`ApprovedOfficeReadReceiptSink` implementation:
`app.hark_office_p01_durable_ledger.PrivateDurableOfficeReadLedger`.

This implementation cannot approve user actions, grant local file permissions,
read any file, dispatch a Broker command or upload to Google Drive. Nothing is
enabled in default production wiring. No new public HTTP route is provided.

## Actual contract

The server-owned `trusted_binding_resolver` must look up an already-authenticated
owner/workspace/session, device/selected-root and exact Broker command identity
before accepting the Engine's **real** verified READ receipt.

- Receipt `run_id`, `device_id`, `root_ref` and SHA-256 file-request fingerprint must match the trusted command.
- Owner, workspace, session, device, selected root, Broker binding/command/tool
  request/request/revision identity, command digest and sequence form the immutable
  private lookup key; the source of these fields is the *trusted host*, not JSON.
- SQLite transaction stores canonical ApprovalPause, VerifiedApprovalDecision and
  exact ToolInvocation arguments, with 5-minute maximum TTL bounded by P01 pause
  expiry; no document bytes are stored.
- Each request fingerprint and decision ID can be recorded once. A concurrent
  `BEGIN IMMEDIATE` transaction permits precisely one matching command redemption,
  even across reopened store handles; a lost redemption response must NOT be retried
  or mistaken for renewed consent.
- A foreign owner/workspace/session/command/device/root/run or expired receipt returns
  no authority evidence. Tampered stored receipt fails canonical revalidation.
- Engine existing 503-fail-closed handling applies if required durable storage
  fails after continuation consumption.

**This ledger is only evidence transport, never Windows authorization.**
The Resident must independently recompute the canonical file fingerprint and
enforce existing local selected-root permission + original P01 decision via
`P01LocalPermissionWindowsFileAuthorizationPort`. The real authenticated
Broker/Resident transport is NOT composed by this PR.

## Remaining integration blockers

1. Provide an authenticated B62 Hark Office candidate source, real owner/session
   and Broker command correlation, and inject a production-appropriate durable
   binding resolver. Do not accept a browser-provided binding.
2. Expose the private one-shot evidence to an authenticated Broker-to-Resident
   transport with device credential/command integrity checks. No unauthenticated
   retrieval endpoint.
3. Derive real `LocalFileRequest` and pre-existing
   `WindowsFileAuthorityEvidence` for exactly the selected command, then inject
   the resulting trusted source into `office_p01_plan_source` with Windows
   policy enforcement unchanged.
4. Run one same-owner/session synthetic-file, real-broker-ACK Windows XLSX->Excel
   COM PDF->Broker material integration proof; subsequently obtain separate user
   approval for actual customer files, Drive WRITE and production deployment.

Keep #3580 open and do not describe this as completed production E2E.
