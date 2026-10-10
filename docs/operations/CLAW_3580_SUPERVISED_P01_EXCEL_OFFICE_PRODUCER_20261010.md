# Hark P01 Windows Excel XLSX/PDF producer — 2026-10-10

Scope: #3580, #3933, #3936. **Source composition and one synthetic interactive Windows Excel canary only**, not customer-ready Production.

## Now implemented

`build_resident_host` accepts an explicit, trusted `office_file_requests` + `office_file_authorization_port` pair (and optional custom supervised renderer). It composes the existing Windows `WindowsSelectedRootFileRuntime` with `ApprovedWindowsOfficePairProducer`; a missing grant, an unapproved non-Office command, competing producer implementations, or a renderer without a P01 file-authority port fails closed. Nothing is taken from the model reply, browser filename or arbitrary directory enumeration. The default `main()` supplies neither input, so Production remains inert.

Only after the existing P01 Windows command has **executed and the canonical Broker has acknowledged the exact completed result** does Resident call this provider through the previously merged post-ACK path. The provider independently checks command/run/device/revision/sequence correlation, obtains an exact `LocalFileRequest(READ)` from the trusted host (or None), invokes the **existing P01 selected-root file runtime** so its real authorization grant, selected root, canonical path traversal and symlink protections apply, and builds `LocalXlsxArtifactHandoff` from original XLSX bytes. The renderer produces a derived PDF and `LocalXlsxPdfOutput`/lineage without mutating the XLSX. Both are revalidated and sent only via the existing 48KiB Broker HTTPS publisher. A five-minute broker-vs-device timestamp skew tolerance does not bypass the file grant, which is still validated against the current device clock.

`SupervisedWindowsExcelPdfRenderer` spawns a **single Windows Job-bound child** running `kagent.windows_excel_pdf_child` for one source copy. The Python executable is fixed to the trusted interpreter, shell is disabled, the child's environment is a narrow Windows/Python allowlist, input/output paths reside in a short-lived private temporary directory, output is bounded to 8MiB, and timeouts are bounded to 5–120 seconds (default 45). It invokes the previously existing `WindowsInteractiveExcelPdfRenderer` inside the child, reuses its macro/link suppression, returns only validated PDF bytes and removes temporary inputs/outputs. Timeout or child error terminates the Job and yields a generic refusal, not a raw path/COM message. Google Drive OAuth and broker credentials are not passed to the Office child.

**Caveat:** Excel is a COM out-of-process server and can be launched outside the Python child's Job by the COM service. Kill-on-close for the Python child is proven, but complete COM process shutdown on forced timeout is **not proven for unattended Production**. Activation requires an interactive Office license/session, timeout/hung-COM cleanup checks, P01 grant proof and operator rollout. Do not claim that the child Job itself always kills an escaped EXCEL.EXE.

## Exact verification

- On a connected Windows machine with Excel and pywin32 installed, **real Excel PDF export succeeded twice** using only freshly generated synthetic XLSX files, not customer quotes. In the final environment-allowlisted run: 4,861-byte XLSX → 20,542-byte valid PDF, digest prefix `c88489521a1da696`.
- Focused local integration/compatibility suite: **52 PASS / 1 SKIPPED** (resident real coordinator+ACK with fake broker transport, P01 selected-root capture, original-preserving PDF material, foreign device/run/refusal, simulated timeout and child-kill, default disabled).
- The real Office canary is user-approved local-only and is not included in CI; CI does not claim installed Excel.
- No live customer XLSX read, Google Drive WRITE, Production deployment, Secrets change, paid model invocation, new Windows server, or Cloudflare feature activation.

## Still required for Production completion

1. The trusted Desktop/P01 selected-root file planning authority must supply a **real exact command-correlated READ request and actual independently verified Windows file grant** when binding `build_resident_host`. The production `main()` intentionally does not infer, auto-create or enable them.
2. Prove approved file read and supervised Excel PDF output on actual paired resident command with the real Broker and DO private staging opt-in; test cancellation/hung COM and no orphan Office processes before activation.
3. Separately consented Control Plane Google Drive READ/WRITE injection, cross-worker durable per-file idempotency and reconciliation, Claw file cards, PDF preview/download, same-/next-conversation lineage E2E.
4. Keep #3580, #3933, #3936, #3928 **OPEN** until those proofs pass.

All tests here are hermetic except the explicitly initiated synthetic local Excel canary.
