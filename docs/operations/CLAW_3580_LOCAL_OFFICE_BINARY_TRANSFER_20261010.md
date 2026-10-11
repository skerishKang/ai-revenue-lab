# Hark P01/Office: bounded Local Runner binary transport (2026-10-10)

Scope: #3580 / #3933 / #3936. Source implementation; **not an active Production E2E**.

## Implemented device-to-server transport

The same canonical, already-deployed **outbound-only HTTPS pinned broker client** now understands the `office-part` operation. The opt-in `LocalOfficeChunkPublisher` sends an immutable approved Office output as 48 KiB base64 pieces with filename, MIME, total size, exact SHA-256, chunk count/index and per-chunk digest. It supplies the existing protected device credential to the canonical authenticated Broker service. Neither a browser nor an LLM can choose the owner/workspace or a Google Drive destination. There is no new Windows server.

The existing edge Worker and private Service Binding derive the route allowlist from `DEVICE_HTTP_ROUTES`. The DO authenticates each request with the **existing canonical device binding**; a missing/expired/revoked device credential fails. The new `BrokerOfficeChunkStore` uses DO SQLite for immutable parts and metadata. It accepts **only** the canonical exact command, run, binding and account/workspace, where the real broker already recorded `acknowledged`, `exited`, `exit_code=0`, admission and evidence. Both XLSX and PDF support up to **8 MiB each**, at most two types per command. Partial bytes are never served.

The server's **private-only** `read_office_artifact_part` RPC checks the same broker owner/run and validates the complete ordered original (bytes, per-part SHA-256, whole SHA-256, size, PDF/OOXML signature) before the first part can be returned. Immutable verified records cache the full verification. Records expire in 24 hours and their SQL parts are pruned; a stale broker ACK cannot seed a new file. Current device binding/revocation and credential generation are checked on every read.

B62's `LocalRunnerResultSource.read_staged_office_output` derives conversation and workspace from its own D1 run and stored command correlation, independently requires a successful canonical Broker terminal fact, and retrieves the complete original through the private binding. There is **no public byte download endpoint** for this source: end-user downloads remain the separate owner-scoped authenticated Claw artifact API from #4148, after a separately consented Drive write and D1 registration.

## Feature remains fail-closed

**Default: disabled.** The broker DO only creates a staging store when its operator has deliberately configured `LOCAL_AGENT_OFFICE_CHUNK_TRANSFER_ENABLED=true`. That setting was **not** added or changed in any Production environment. Without it, the authenticated route returns a bounded `503 office_transfer_not_configured`; the private reader returns unavailable. The publisher is **not** automatically invoked by the Windows resident process. Merely importing code, pairing a browser, or seeing a P01 model reply cannot enable it.

## Verification vs actual capability

- Real PDF bytes exceeding 48 KiB traverse two JSON requests from the physical publisher interface through the canonical authenticated device service, are stored in **real SQLite**, and are reassembled on the private read side with matching digest.
- Real openpyxl XLSX bytes stage independently from PDF and recover exactly.
- Fake network transport in automated tests; no actual HTTPS traffic, Secrets, OAuth, user Drive WRITE, paid model or Production deployment.
- Tests cover auth rejection, absence of opt-in, missing/uncompleted run, stale or revoked binding, expiry/garbage collection, owner isolation, incomplete chunk, conflicting retry, modified stored chunk, changed metadata, missing private read port and D1-scoped broker success.

## Strict remaining E2E gates

1. Bind the existing **authorized Windows resident Office producer** to `LocalOfficeChunkPublisher.publish` after supervised Excel export. Current Windows Excel COM renderer remains opt-in and is not automatically invoked.
2. Exercise real approved device credentials with the live Broker HTTP path, activate feature in a separately approved rollout, verify SQLite persistence across a Durable Object restart, readback through Worker Service Binding, with an owner-scoped D1 result.
3. After separately approved Google Drive WRITE and independently approved READ, reconcile exact staged bytes/lineage with `LocalRevisedXlsxPdf`, then invoke the merged `ClawOfficeDriveCompletion` to create immutable D1 PDF/XLSX entries; do not treat successful staging as authorization to upload.
4. Verify Claw file card, PDF preview, download, same-/next-thread reuse and XLSX versioning in Production with explicit customer permission.

Do not close #3580/#3933/#3936/#3928 on source or hermetic integration tests. No migration 026 reapplication. No changes to B14/B66 ownership.
