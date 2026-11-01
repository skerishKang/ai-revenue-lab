# StoryMemory v3.4.10-rc2 — Six-Work Direct UI Exposure Fix

- Candidate: `v3.4.10-rc2`
- Build: `sm093-six-work-ui-exposure-fix`
- Deployment: `DEFERRED_TO_BI_PORTAL`
- Baseline: `StoryMemory_CloudflarePreview_v3.4.10-rc1.zip`
- Baseline SHA256: `27bb8caba09e45d665737b006bbba3d8b90a863d54c37712b0ed3ed601a41e9c`

## Root cause

The Library card array exposed only Iliad and Odyssey as static-reader identities. The existing Aeneid, Metamorphoses, Paradise Lost, and Divine Comedy static assets had no Library card, title-to-content identity, `STORYMEMORY_STATIC_WORK_KEYS` entry, or prose unit navigator entry. The existing `openBook` handoff already routed non-Bible cards to `reader`; the missing identity/mapping prevented the static binding chain from reaching those assets.

## Bounded repair

`dist/index.html` only:

- appended four existing static works to the Library card list while preserving the original seven card order and numeric selection indexes;
- added existing work identities to `STORYMEMORY_CONTENT_REGISTRY` and title resolution;
- added existing `DB`/static work-key mappings;
- added existing manifest unit counts to `STORYMEMORY_PROSE_UNIT_CATALOG`;
- added only existing cinematic labels/timings for the four cards.

No `dist/content/**`, translation data, canonical locator, source hash, Neon, Cloudflare, Portal, DNS, deployment, or Git mutation was made.

## Preserved boundaries

- RC1 hydration fix remains: `restoreSessionFromUnifiedStore({navigate:true});`
- Bible WEB, Crime and Punishment, Pride and Prejudice, and Alice in Wonderland remain `EXPECTED_PRE_SM093_FALLBACK`.
- No new source corpus or readiness flip was added.
