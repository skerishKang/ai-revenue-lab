# #3580 — Verified Engine Office READ evidence -> Resident P01 plan bridge

> **WEB-FIRST sequencing supersession (2026-10-11):** This source-complete Resident adapter remains preserved for **optional later local-PC/Excel fallback**. Owner priority is authenticated B62 web upload/Drive READ -> P01 -> server-capable result/preview. It is **not** a prerequisite for web MVP. See [web-first decision](CLAW_HARK_WEB_FIRST_OWNER_PRIORITY_20261011.md).

Date: 2026-10-11 KST

## Milestone

`VerifiedEngineOfficeReadPlanSource` implements the existing
`TrustedP01OfficePlanSource.approved_plan` protocol, so a **trusted,
authenticated, one-shot evidence redeemer** can deliver actual Engine-first-party
verified Office READ evidence into the already-shipped
`TrustedP01OfficeFilePlanBridge` -> `P01LocalPermissionWindowsFileAuthorizationPort`
-> `ApprovedWindowsOfficePairProducer` -> Broker post-ACK pair publisher.

The adapter is inert until a trusted deployment injects an authenticated
command-binding resolver and private evidence redeemer into Resident's existing
`office_p01_plan_source` builder parameter. No new browser or local permission
grant API exists. No code in this PR opens customer files or changes production.

## Security contract

- The Broker command must already be admitted, completed with exact successful
  acknowledgement, and correlated to its bound device, run, request, revision,
  sequence and tool request BEFORE any evidence redemption.
- The private resolver MUST authenticate owner/workspace/session and return the
  previously persisted exact command scope. Returning a simple value from
  untrusted browser JSON is forbidden.
- The private redeemer MUST enforce the #4219 durable ledger's owner/session,
  device, root, request fingerprint, Broker command identity, TTL and one-shot
  transaction, using an authenticated server/Broker-to-device channel.
- The adapter rehydrates the canonical LocalFileRequest and RECOMPUTES its
  SHA-256 fingerprint plus the exact Windows ToolInvocation digest, comparing
  both with the original Engine ApprovalPause. Any changed path, root, run,
  device, operation, timestamp or filename fails closed.
- Only actual canonical APPROVED P01 USER_CONFIRMATION in filesystem.read scope
  with an unexpired decision is eligible. Local evidence is bounded to five
  minutes and the original pause expiry. No additional approval is minted.
- Existing Windows selected-root runtime still independently evaluates local
  permission, file path containment and P01 evidence. Files are only staged
  after Broker ACK.

## Offline test boundaries and remaining work

Focused Windows tests use a TEMPORARY synthetic XLSX, a fixture P01 decision,
an existing canonical in-memory Broker and a fake Excel/PDF and pinned HTTPS
transport. These demonstrate the adapter's local contract and byte staging,
**not** real user consent, actual Excel COM, customer file access or
production transport.

Still required for #3580:
- Authenticated Hark Office chooser source and exact owner+workspace+session
  Broker command binding.
- Server-to-Resident authenticated one-shot evidence retrieval, implementing
  the private redeemer contract without exposing Engine decisions to browsers.
- One same-run actual FIRST-PARTY Engine verified decision through the authentic
  Broker and Windows file runtime with real Excel COM/PDF and Hark preview.
- Separate explicit approval for Production deployment, actual customer-file
  handling and Drive WRITE.

#3580 remains OPEN; no synthetic fixture counts as customer E2E acceptance.
