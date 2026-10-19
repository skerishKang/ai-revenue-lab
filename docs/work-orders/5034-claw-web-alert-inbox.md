# #5034 — Claw web alert inbox implementation handoff

STATUS: DRAFT_SCOPE_ONLY
OWNER: LOCAL (to be assigned)
BASE_MAIN: cb5e3b7546ec3395d6dad54d67a2c64b003ae6c4
SOURCE_ISSUE: https://github.com/skerishKang/ai-revenue-lab/issues/5034

## Goal

Reuse the existing Claw per-user/workspace alert store and run-to-alert links to deliver a usable web alert inbox for completed/failed jobs. Keep existing Chat/Claw/B66 authorization boundaries.

## Implementation slices

1. Inspect existing #2058 / #2328 / #2341 inbox contracts, served Claw UI, and product routing; avoid a second store.
2. Wire server-derived completion/failure event references to a single alert per event/run. Alert dispatch failure must not repeat the underlying job.
3. Expose inbox list, unread state, mark-read action, and authorized deep-link to originating conversation/run. Enforce owner/workspace and product scope both when listing and when following the link.
4. Run focused tests for exactly-once, foreign-owner rejection, stale target, read status, and account switching.
5. Web Push is a second increment in #5034; document remaining steps and separate actual device delivery verification from inbox tests.

## Out of scope

PC/Drive/mobile connectors, file transfer, tool dispatch, scheduling engine, new account role system, new provider integrations, production push-key creation, deployment, and any business policy decisions.

## Completion contract

LOCAL should implement on this branch or replace it with a minimal implementation PR, then report changed files, focused tests, CI, merge/deploy/live status separately. This document alone is **not** an implementation or acceptance.
