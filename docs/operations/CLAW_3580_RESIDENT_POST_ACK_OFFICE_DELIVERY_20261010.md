# Hark Windows Resident: post-ACK Office bytes transfer (#3580, 2026-10-10)

## What was implemented

The already-existing `LocalAgentResidentRuntimeHost.run_once` now accepts an **optional, trusted, injected** `office_staging` port. Its single actual P01 command coordinator first completes material resolution → admission → Windows execution → durable result → canonical Broker ACK. Only **after** the broker ACK succeeds can the optional staging step load the *same binding's* protected device credential and invoke `ResidentOfficePairPublisher.on_acknowledged`. The helper checks exact command/run/binding/revision/sequence/tool-request correlation, exit=0, exited termination, and the canonical receipt. No alternate executor, upload server, approval authority or Office worker was added.

The only permissible file source is a **trusted host-injected** `TrustedApprovedOfficePairPort.completed_pair`. It returns the already-authorized `LocalXlsxArtifactHandoff` and the original-preserving `LocalXlsxPdfOutput`, or None for non-Office commands. These artifacts are not inferred from directory contents, stdout, filenames supplied by browsers or LLM text. Scope, source and transformed lineage and exact canonical SHA-256 material are revalidated. Both unchanged XLSX and its derived PDF are sent via the previously merged `LocalOfficeChunkPublisher` (48 KiB each) to the canonical outbound HTTPS Broker device route. No Drive WRITE grant is inferred.

The resident composition `build_resident_host(..., approved_office_pairs=...)` makes the opt-in explicit. The shipped `main()` does **not** inject this port: there is no independent proof that a supervised live Office producer and its selected-root/P01 READ authorization are currently wired into the resident. The default stays inert. The Broker DO itself separately defaults OFF unless `LOCAL_AGENT_OFFICE_CHUNK_TRANSFER_ENABLED=true` is configured through an approved rollout (not changed here).

## Failure semantics

- Failure or refusal of P01 execution / non-successful terminal result: no Office supplier call or transfer.
- Canonical ACK is required before bytes leave the machine. No broad filesystem scan.
- Foreign workspace, wrong run, mutated bytes or lineage: refuse **before** sending either file.
- A failed stage is a diagnostic `office/STAGING_REFUSED` and **never** rewrites the already acknowledged command as unexecuted. No automatic process re-execution or retry; staged parts may be incomplete and must never be represented as a completed Drive output.
- Two-file staging is **not atomic**. If PDF fails after XLSX, the XLSX part may exist in private temporary storage for its 24-hour TTL; the Drive completion boundary must require the full pair. The previously merged server private read still verifies each whole file. A durable transfer/replay queue is future work.

## Verification

Run targeted `apps/korean-ai-code-agent/tests/test_3580_resident_office_post_ack_delivery.py` plus the existing `test_local_agent_runtime_host.py`, `test_local_agent_resident_process_3140.py`, `test_local_xlsx_pdf_output_3580.py` and `test_local_office_chunk_publisher_3580.py`. These are hermetic (fake pinned transport; no HTTP, paid models, user files, or Drive writes). The unconfigured live Desktop code cannot make Office automatically available merely by merging this source.

## Remaining operational blockers

1. **Supervised Office producer:** a real trusted local P01 selected-root READ/Excel PDF conversion producer must return the pair to the resident and prove cancellation/timeouts, Office dependencies/license, approval and session binding. Not auto-enabled.
2. **Broker opt-in and real roundtrip:** separate operator-approved Cloudflare deployment/feature flag + live device TLS ↔ Broker ↔ DO restart proof. No production settings were changed.
3. **Drive consent and UX:** independently consented server READ/WRITE, D1 idempotent reconciliation, UI file card/PDF preview/download and same/next conversation lineage E2E are still absent.

Keep #3580, #3933, #3936, #3928 OPEN. Source merge is not a claim of complete customer-facing Hark.
