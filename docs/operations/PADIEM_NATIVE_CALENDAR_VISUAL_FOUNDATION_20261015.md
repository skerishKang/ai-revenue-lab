# PADIEM native Calendar: visual foundation (2026-10-15)

## Scope and authority
Canonical native product: [#2834](https://github.com/skerishKang/ai-revenue-lab/issues/2834). This release updates the existing B62 Calendar presentation. It does not create another calendar store, another identity authority, another OAuth connection, or any new write route.

## User experience
- Calendar navigation opens the **Month** grid by default. All dates remain visible even if the user's list is empty or a scoped API read fails. A read failure continues to show the existing error/retry indicator and does not invent events.
- **Month**: Monday-first calendar with adjacent-month dates and a bounded per-date preview. Selecting a date opens **Day**.
- **Week**: seven columns for the selected week and existing calendar events; selecting a day opens **Day**.
- **Day**: 00:00?23:00 hourly timeline plus an all-day/undated-time area; event placement uses the item's explicit timezone and start timestamp when present, never a guessed time.
- **Today** and **Upcoming** preserve existing list presentations.
- Previous/next/current-period controls continue using the existing timezone-aware range projection.
- The Calendar uses Chat/Claw's glass visual language, content left alignment, portrait breathing room, and isolated mobile scroll for seven-column grids.
- Existing record/appointment create forms, item detail, and trusted Claw link-back routes remain in place.

## Existing data reuse
Read paths: `GET /api/calendar/today`, `GET /api/calendar/upcoming`, `GET /api/calendar/items`, and bounded item details. Existing explicit timezone and server-derived workspace authorization contracts are unchanged. Writes remain only the already-reviewed native work-log/appointment forms. The shared native calendar backend is the reference source for the user's Chat and Claw workspace.

## Out of scope and follow-up
- AI model natural-language create/read/update/cancel scheduling tool registration and verified execution from Chat and Claw: **not implemented in this visual foundation**. Implement separately against native PADIEM Calendar authority, never against an invented client-side store.
- Native appointment update/delete semantics and scheduler/reminders: require their own implementation and authority; do not advertise as shipped.
- Google/Naver Calendar import/export: optional future integration under the existing separate connector program; not required for native product.
- An underlying Production API read failure requires HTTP status/source diagnostics independently of visual layout. Empty/failed reads do not imply the user's schedule is empty.

## Release
Implementation is in `apps/padiem-chat/static/calendar.js`, `calendar.css` and the existing static entry markup. Focused calendar suite: 19 PASS at source head before merge. Production deployment must use the protected B62 exact-main workflow preserving all live service bindings and secrets. Record final run ID in #2834 without asserting AI scheduling or live API read acceptance.

## Phase 2 - native calendar management and layout (2026-10-15)

- Calendar kicker displays the same cyan 6-pixel dot as Chat/Claw. The long introductory text and persistent top-of-page creation accordions are visually removed.
- Selecting a month date or week column opens the existing native appointment editor with the date prefilled. Selecting a day-hour slot also prefills time. Existing native events support edit and delete, with confirmation for deletion.
- The Month/Week/Day calendar display has a stable fixed viewport and scrolls internally. Day view initially scrolls to 09:00 while all 24 hours remain accessible.
- Server endpoints: PUT/DELETE /api/calendar/appointments/{appointment_id} and PUT/DELETE /api/calendar/work-logs/{log_id}. They use existing native D1 tables and the authenticated server-derived owner/workspace, verify the specific existing item's ownership, validate the replacement via existing domain contracts and preserve created_at.
- Foreign/nonexistent items fail closed (404); anonymous writes fail closed (401). The client never supplies owner_id, workspace_id or tenant_id.
- Failed read views distinguish sign-in required (401) from bounded 4xx or 5xx error statuses, without exposing raw server content.
- A PUBLIC ANONYMOUS request to /api/calendar/items returned 401, as expected. The earlier screenshot of a signed-in browser's failed read remains UNRESOLVED until an authenticated request's status and response are observed; this release does not claim that underlying failure is fixed.
- Chat/Claw AI natural-language calendar tooling remains follow-up #4745. No second store, new external connector grant, autonomous scheduling, or reminder delivery was added.
