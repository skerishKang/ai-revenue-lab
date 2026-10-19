# Hark #3580 — P01-approved selected-root quote candidate discovery (2026-10-10)

## Function

The operator selects an existing Windows Local Agent root. Hark may propose a filename substring, but never scans the whole PC or invents a new root.

NEW separate canonical local.filesystem.list.quote-candidates invocation: immutable request includes exact device, root, run, action, time, max 40 visible candidates, optional name_contains filter and nonrecursive metadata-only policy. Exact SHA-256 binds the invocation. It requires a canonical, separately APPROVED P01 pause/decision for this listing invocation, verified against local filesystem.read policy. A previous process.execute or file READ approval is not valid listing consent.

Only direct children are scanned; bounded to 4096 entries, no recursion. Only regular .xls/.xlsx files at most 1MiB (the existing selected-root READ cap). Skip symlinks/reparse, subfolders, other extensions, Office lock files and oversized files. Show filename, type, size, modified time and opaque candidate token, with limited/count when results exceed 40. Never open contents. Requests and approvals are one-shot in the host process.

Selecting an opaque token generates only a new LocalFileRequest(READ) intent with the canonical device/root/run, never a grant. A separate existing P01 file READ approval and original WindowsSelectedRootFileRuntime are required before reading any XLS/XLSX bytes. No change to the general filesystem CRUD runtime's DIRECTORY_ENUMERATION_SUPPORTED=False assertion.

## Evidence

Windows synthetic fixtures: root-only metadata, keyword filter, denied/expired/foreign/incorrect-tool/incorrect-scope P01 refusal, local policy DENY, one-shot decision, candidate selection and no implicit content read. On existing real CGI sample folder, a selected-root filtered scan using synthetic test-only canonical P01 evidence found 3 candidate workbooks (one legacy XLS and two XLSX), reporting read_authorized=False. No real user approval was proven or simulated as live.

## Still required

Production B62 user-facing list approval, Engine decision authority, trusted cross-boundary delivery into Resident, real per-file user-approved READ, Broker paired upload, legacy XLS original/PDF lineage, separately approved Drive WRITE and Claw preview. No Production, Secrets, credential, customer-file or Drive mutation performed. Keep #3580/#3933/#3936 OPEN.