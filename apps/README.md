# Product Workspaces

Each directory under `apps/` is an independent revenue experiment with its own implementation, tests, configuration, and evidence.

| Workspace | Portfolio number | Status | Primary hypothesis |
|---|---:|---|---|
| `personal-edition` | 1 | Active implementation | A user will pay for a recurring polished publication that visibly adapts to prior feedback. |
| `living-travel` | 2 | Active design | Travel content becomes more valuable when each edition adapts to the reader's latest interests and situation. |
| `world-feed` | 3 | Active research | Abundant free AI can turn global-local information into a different personal world edition for each user. |
| `living-fiction` | 4 | Active design | Shared fictional worlds can support rapid feedback-responsive and optionally personal narrative branches. |
| `personal-video-archive` | 13 | Incubation contract | Users will repeatedly return to user-controlled topic feeds when video discovery is cleaner and watched videos become durable private reflections and plans. |

Portfolio numbering records the broader business sequence. The workspace table may not contain every numbered business when another concept is still documented elsewhere or has not yet received an isolated repository workspace.

## Business 13 boundary

`personal-video-archive` is video-first and private-record-first.

Its initial product contract authorizes topic search, public video metadata, outbound canonical YouTube links, viewing states, ratings, reflections, plans, tags, and timestamp notes. It does not authorize YouTube comments, social feeds, video downloading or rehosting, historical watch-history import, transcript scraping, advertising, or speculative AI summaries in Phase 1.

See:

- `personal-video-archive/README.md`
- `personal-video-archive/PRODUCT_CONTRACT.md`
- `personal-video-archive/LOCAL_HANDOFF.md`
- GitHub Issue #60

## Boundary

A product may not place implementation files in the repository root. Product-specific code belongs inside its own workspace.

Common code is not extracted until at least two working products demonstrate the same requirement and an architecture decision approves the extraction.
