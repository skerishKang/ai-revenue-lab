# StoryMemory v3.3.6 — Production Authenticated Runtime Activation

Date: 2026-08-26 (Asia/Seoul)
Business: B61 StoryMemory
Base: v3.3.5
Deployment: DEFERRED_TO_BI_PORTAL
Portal target: /b61/

## Purpose

Activate the validated Neon main hybrid contract at runtime without moving canonical book bodies into Neon. Static JSON remains authoritative text; authenticated Neon main is used for metadata/index/knowledge/user state.

## Runtime contract

- Static body mode: `authoritative`
- Remote metadata mode: `authenticated`
- Remote user-state mode: `authenticated`
- Canonical identity: `canonical_locator`
- Legacy DB-body remote reads: **disabled by default**
- Expected main registry: 6 active content versions / 185 content-unit rows
- No database password, service key, or user token is embedded.

## Changes

- Removed obsolete `entities.summary` Data API selection.
- Knowledge reads now include canonical-locator evidence fields for mentions, relationships, and answer cards.
- Added authenticated `content_versions` / `content_unit_index` runtime status queries.
- `source_passages` / `passage_translations` loaders are preserved only as explicit legacy compatibility methods and throw `LEGACY_DB_BODY_REMOTE_DISABLED` by default.
- Bible remote-body fallback is also disabled unless an adapter is explicitly created in legacy mode.
- Auth Bridge installation/session now activates remote metadata mode automatically after a real token provider is available; logout disables remote-ready state.
- Cloud Memory payloads preserve canonical locator, sequence, unit, semantic page, content version, and source preview.
- Cloud Annotation writes require real `canonical_locator`; legacy annotations without an authoritative locator are skipped rather than assigned a synthetic production locator.
- Reader progress writes use the stored exact canonical locator and no longer synthesize page-based production identity.
- Work resolution reads actual main `works` rows and uses canonical work keys. Unseeded future works are skipped rather than written into a demo work.

## QA

- Inline JavaScript syntax: 6/6 PASS.
- Production runtime mock Data API contract: PASS.
  - observed registry: 6 active versions / 185 units
  - expected registry match: true
  - legacy body requests during normal runtime QA: 0
  - canonical knowledge fields: PASS
  - Annotation canonical payload: PASS
  - Progress canonical-only policy: PASS
  - Auth session auto-activation hook: PASS
- Static Reader regression: PASS — 6 works / 12,628 passages; Odyssey Book 17 exact locator `odyssey:book:17:s1:row:004`, sequence 1600004.
- Hybrid AI regression: PASS — bounded evidence, spoiler cutoff, KNOWN_FACT route, static-only SUPPORTED_TEXT fallback, `full_book_body_sent=false`.
- v3.3.5 `dist/content/**` byte regression: 192 files; changed/missing/extra = 0.
- Direct Neon main QA already established 23 StoryMemory tables / 1 view, curated RLS 10/10, 6 active versions / 185 units / source_passages 0.
- Live authenticated browser E2E is not claimed because this execution environment has no real signed-in browser session and local/file browser navigation is administrator-blocked.

## Boundaries

- No full-book-body Neon import.
- No `passage_translations` production table.
- No new Cloudflare Pages project or deployment.
- No existing Pages rename/repurpose/delete.
- No DNS/custom-domain change.
- No BI Portal or Portfolio Console mutation.
- No B61 source/workspace move or rename.
