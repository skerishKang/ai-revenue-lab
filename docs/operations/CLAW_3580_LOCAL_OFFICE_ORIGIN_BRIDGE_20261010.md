# Hark Local Runner completed Office artifact origin bridge — 2026-10-10

Issue scope: #3580, #3933, #3929, #3936. Not a Production E2E completion.

## Existing verified path / new source milestone

`LocalRunnerResultSource.complete_approved_office_run` is a **trusted host callback only**, not an HTTP route. It binds the Office producer to the same active `BrokerAuthorityLocalRunnerResultPort` used by the real #3139 Local Runner return leg. A browser cannot choose its own conversation, tenant or command ID in this flow.

`LocalOfficeOriginBridge` derives the destination conversation and workspace solely from the current owner-scoped D1 Claw run, requires that run to be `completed`, checks current conversation ownership, retrieves the command correlation stored by the server when the broker command was enqueued, then queries the **canonical broker terminal result** for that exact command, run, owner and workspace. All six correlation fields must match. Only `acknowledged` + `exited` + `exit_code=0` qualifies. No broker error text is returned. Expired, unbound, foreign, failed, timed out, workspace-switched or tampered commands stop before any provider operation.

After that, the previously merged `ClawOfficeDriveCompletion` independently verifies actual XLSX/PDF bytes, lineage, per-file Control Plane-approved Drive intents, original hashes, approved folder, upload receipt, and two owner-run-scoped D1 registrations. Broker status alone **never** authorizes Drive writes or proves any document bytes.

The Worker passes `claw_office_drive_completion` to the Local Runner result source only when one was explicitly composed from a trusted Drive uploader. The shipped Worker still does **not** compose an approved Drive uploader; the new callback remains inert/fail-closed in Production.

## Focused verification

- New Local Office origin bridge tests + previous Drive/D1 and PDF preview/download tests: **29 PASS** in unittest.
- Existing Local Runner result/broker binding pytest: **25 PASS**.
- Real SQLite schema uses the previously existing migrations 020 and 026 (fresh test database only), canonical in-memory Office XLSX/PDF and fake Drive transport. No production DB schema write, no live provider, no browser OAuth token.
- Checks include current owner, D1 conversation/workspace, exact stored broker command correlation, broker success vs fail/timeout/expired/foreign, missing correlation, wrong source SHA, absent injected uploader, provider error redaction and no double-upload.

## Remaining true operational blockers

1. Real Desktop/Local Runner execution must return a trusted, bounded **artifact manifest AND an authorized binary transfer** for immutable XLSX/PDF material. Canonical Broker currently returns command identity/termination only; no file payload and no PDF fidelity attestation. Do not accept a model string or arbitrary browser file path as authority.
2. Actual Office edit/export must be invoked in a supervised, permissioned Windows process (existing interactive Excel renderer is opt-in/inert). Verify formula recalculation, styles/images and output PDF pagination independently.
3. Control Plane must provide a current WRITE grant and READ grant with owner+workspace, explicit user consent per write, target folder proof, cross-worker durable idempotency/reconciliation. Browser Google login is not such proof.
4. Claw file-card UI, real same-thread and next-thread content retrieval, and Production E2E still require proof. Never mark the parent issues closed or call the workflow operational from source-only tests.

No new HTTP endpoint, Secrets modification, Google Drive user-file write, paid model call, Production deploy or D1 migration apply in this PR.
