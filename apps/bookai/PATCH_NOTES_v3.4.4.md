# StoryMemory v3.4.4 — SM-087 Source-Agnostic Library + Source Viewer UI

## Scope
v3.4.4 adapts the existing StoryMemory Library/Reader presentation to the v2.1 Universal Context Companion contract. It does not replace the Book experience: the 3D shelf, exact canonical resume, paper reader, and page-curl remain the Book Source skin.

## Added
- `storymemory-source-ui-1.0` UI adapter.
- Library `Books / Sources` mode switch plus `Source 추가` entry.
- Non-book Source deck with shared progress / last-position / Trust / Pack grammar.
- Native CENTER viewer variants for document/contract, workbook, and transcript/timestamp material.
- Source-aware LEFT Context Rail with stable locator navigation, memory action, and locator copy.
- RIGHT AI Companion binding to current Source locator, Trust Mode, attached Pack count, and source-type quick questions.
- Session-local user-private import for already-extracted document/workbook/transcript text.
- Workbook Tutor presentation and retrieval policy keeps restricted answer blocks hidden.
- Mobile behavior continues to use the existing Reader mobile Memory/AI drawer grammar instead of forcing three permanent columns.

## Preserved
- Book Library 3D shelf and extraction motion.
- Book Reader paper/page-curl interaction.
- Odyssey exact resume and Book17 canonical locator bridge.
- `storymemory-universal-source-runtime.js` bytes from v3.4.3.
- Static corpus: 6 works / 185 units / 12,628 passages; `dist/content` bytes unchanged.
- Trust Modes and Precision Pack runtime from SM-083/SM-084.

## Explicit non-claims
SM-087 does not claim:
- raw binary PDF OCR or acquisition,
- live URL/YouTube network fetch,
- media STT/transcript acquisition,
- durable cloud upload/storage for the new Source import surface,
- live authenticated browser acceptance in this execution environment.

## Browser gate
Headless Chromium in the current execution environment fails to complete even a minimal `data:text/html` page invocation. Browser screenshot/interaction acceptance is therefore `PENDING_ENVIRONMENT_BLOCKER`, not falsely marked PASS. Deterministic UI/runtime contract tests and syntax/static-byte regressions are PASS.

## Deployment boundary
- NEON_MUTATION = NONE
- CLOUDFLARE_PORTAL_DNS_MUTATION = NONE
- BOOK21_PLUS_MANUAL_KNOWLEDGE = NONE
- DEPLOYMENT = DEFERRED_TO_BI_PORTAL
- PORTAL_TARGET_ROUTE = /b61/
