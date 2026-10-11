# Hark-style PADIEM Claw — WEB-FIRST delivery order (owner decision)

**Decision date:** 2026-10-11 KST

**Status:** AUTHORITATIVE PRIORITY, not a claim of shipped functionality.

**Applies to:** #3928 (web UX epic), #3580 (files/artifacts), #3933 (Office editing), #3936 (browser E2E), related B62/B54/P01 work.

## Binding owner decision

**Complete the owner-authenticated B62 web journey first.** Hark is the external UX benchmark; the deliverable is **PADIEM Chat/Claw web product**, not modification of the unrelated hark.com service. Do not default to Windows, local filesystem, Resident, Excel COM, or connected-PC prerequisites. Never make the browser show an approval button for an unconfigured backend, and do not label source CI as functional live web delivery.

**Windows Resident = optional fallback only** when the user explicitly chooses local-PC files, or a format/fidelity capability demonstrably requires local Excel/Office and the server cannot safely perform it. All earlier merged Windows code (#4171, #4175, #4215, #4219, #4222) is preserved and disabled unless its preexisting P01/local device authorization is satisfied. It is *not* a reason to hold web-first delivery or expand Windows infrastructure ahead of web acceptance.

## Ordered implementation — do not invert

| Phase | Primary implementation | Exit gate | Windows prerequisite? |
| --- | --- | --- | --- |
| W0 | Reconcile current B62 authenticated web UX, #3523 text-first/first answer, existing file cards, and exact current Office APIs; mark unconfigured/placeholder states accurately | Working first reply and owner-scoped run/approval truth; inventory of actual connected sources | **NO** |
| W1 | Browser-driven **user-selects-file upload** and authorized **Google Drive picker/list** as two distinct web sources; trusted B62 owner/workspace/session correlation; bounded XLSX metadata/candidates (not whole-PC discovery) | Authenticated browser can select exact available workbook and see sanitized filename/size/source without raw path or file content leakage; source missing/unauthorized produces truthful disabled/error state | **NO** |
| W2 | Selected web file read/working-copy/P01 approval orchestration with existing Engine first-party decision; display exact requested operation and source; deny, expiry, replay, foreign-owner rejection | Browser selection -> canonical server-side owner-scoped P01 decision -> only explicitly approved processing; immutable original; exact account/run/source binding | **NO** |
| W3 | Server-supported deterministic XLSX analysis/edit/export; preserve original + version lineage; **server PDF only where fidelity verified**, otherwise explain unsupported and offer optional fallback | Synthetic fixture source hash unchanged, output formula/amount/format checks, real owner-scoped artifact bytes registered; no fake renderer presented as production | **NO**, unless capability gate indicates fallback |
| W4 | Real stage events, owner-scoped XLSX/PDF cards, verified in-browser preview/download, multistep follow-up and failures on PC/mobile | Same actual web run across select -> approve -> process -> artifact -> preview -> download -> follow-up; scoped negative and error tests; no customer file used absent approval | **NO** |
| F1 (later) | **Optional** authenticated Broker -> Windows Resident for user-chosen *local-only* files or unsupported Office fidelity | Separate exact owner/device/root/command/run grant, original P01 verification and local permission, ACK, Excel COM PDF, secure material handoff | **YES**, *only for fallback* |
| F2 (separate approval) | Optional external Google Drive WRITE/upload | Separate explicit user consent, provider OAuth WRITE authority, exact artifact and destination; no silent upload | **NO** |

### Source-choice routing rule

- **Web upload** (user explicitly selects a file): B62 web upload to owner/workspace-scoped temporary material. The browser must not invent a Windows local-file READ request for uploaded bytes; the server uses an authorized web-file pipeline and scoped processing consent.
- **Google Drive** (connected account, permitted READ): use the existing OAuth-scoped provider authorization; a file selection never implies WRITE or Drive export consent. If the source is unavailable, show the absence instead of redirecting silently to Windows.
- **Local computer** (user explicitly selects the local-only execution path): use existing P01 + Windows Resident code; never scan the user's PC or create file access from a mere Engine receipt.
- **PDF/fidelity fallback**: choose from actually available and approved server tools. If none can preserve document requirements, show supported limits and require an explicit optional Windows decision, not a fake success.

## Ownership, dependencies and safety

- **B62** owns web composer, authenticated chooser, file selection, cards, preview/download. **B54** owns generic tasks and follow-up. **P01 Engine/Core** owns approval truth/continuation. **B14** supplies only user-selected model routing; no hidden model substitution. **B66** remains a separate quote product and is not copied into Claw.
- Real file operations must bind exact owner/workspace/session/run/source and require P01 consent where applicable. No synthetic authority in real routes; no raw absolute paths in browser responses.
- Use existing Drive READ, artifact and preview routes where possible. Do not assume Google Drive WRITE, server conversion fidelity, or the Office chooser candidate source is configured: **as of this decision, full W1-W4 is not demonstrated**.
- Do not execute Production deployment, customer-file reads/uploads, Secrets changes, paid model calls, or unauthorized Drive WRITE under this decision. Normal code/PR/CI work remains allowed.
- Keep #3580/#3928/#3933/#3936 **OPEN** until relevant *web-first* acceptance is independently proven. #3523 first response is a prerequisite for claims of live conversational web completion, not a reason to prioritize Windows.
- Where historical issue body/runbooks say the **next** step is Resident, this decision overrides *sequencing only*, not any historic technical proof or security guard. Keep previous source milestones as historical evidence.

## First concrete web development slice

Inspect `apps/padiem-chat/app/claw_office_chooser_routes.py`, B62 web UI, existing upload/Drive READ services, `history_store` owner/workspace handoff, and #3932 owner-scoped PDF preview. Implement a **real trusted web candidate source for uploaded/Drive-authorized workbooks** (not a local-PC-only source), with explicit source choice, account isolation, exact selection/approval, bounded failure behavior and focused API/browser tests. Prefer existing typed/authorized components over a second approval or storage authority.

Acceptance evidence must always distinguish `SOURCE_TEST_PASS`, `BROWSER_WEB_E2E_PASS`, `WINDOWS_FALLBACK_PASS`, `PRODUCTION_LIVE_APPROVED_PASS`. Never conflate them.
