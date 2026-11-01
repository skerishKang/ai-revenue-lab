# StoryMemory v3.4.7 — SM-090 Pack Version / Rating / Fork Lifecycle

- Adds Marketplace M5 lifecycle runtime: immutable published-version history, version proposals/review boundary, version-scoped ratings, source-locator feedback, and private fork lineage.
- Published Pack content is never silently mutated by community/user edits. Corrections become feedback or a forward-only version proposal; release remains a registry/host review action.
- Forks default to LOCAL PRIVATE drafts and do not inherit VERIFIED status. Durable registry persistence is allowed only after an artifact writer returns a real artifact URI and fingerprint.
- Rating is version-scoped. Public aggregate rating summary is separated from private user identity/review rows.
- Neon Main now stores lifecycle metadata only: pack_version_proposals, pack_ratings, pack_feedback + pack_rating_summary.
- No Source body, entity/relation/answer-card, Book21+ knowledge, or embedding precompute was added.
- M6 paid entitlement/settlement and M7 expert/official verification remain out of scope.
- Deployment remains DEFERRED_TO_BI_PORTAL at /b61/.
