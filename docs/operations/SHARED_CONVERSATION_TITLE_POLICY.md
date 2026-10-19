# Chat / Claw / B66 conversation title policy (2026-10-15)

Owner decision: do not call a model to generate titles or summaries.

- PADIEM Chat and PADIEM Claw: show the first sentence of the first user turn, clipped to the existing 80-character title bound. They share the existing owner-scoped Chat history.
- B66 AI chat: reuse the same history title produced from its first user turn; its product scope remains separate.
- B66 guided quote: show the first user answer from the existing owner/workspace-scoped transcript; use 견적 상담 only if no valid user answer is present.
- No generated summary, separate summary UI, additional AI call, new database migration, or background processing.
- Preserve older stored titles without destructive backfill. Preserve established login, ownership, product scopes, search, continuation and deletion.
- All UI text is derived from stored data and inserted as textContent, never HTML.
