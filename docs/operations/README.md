# Operations Documents

- `UI_UX_BACKEND_PHASE_GATES.md` — mandatory sequence and approval gates: product framing → UI → UX → backend decision → backend implementation.
- `NEW_BUSINESS_UI_FIRST_PLAYBOOK.md` — reusable Phase 1 visual-UI policy for every new or revived Business.
- `CODE_STRUCTURE_AND_ASSET_VERSIONING_POLICY.md` — portfolio-wide deterministic asset version queries, 500-line source-file ceiling, and domain-based folder/file naming.
- `CLOUDFLARE_PAGES_GIT_CONNECTION_RUNBOOK.md` — separates Git state, Pages project connection, hosted review, and product production release.
- `DOCUMENTATION_AUDIT_2026-07-26.md` — repository audit of GitHub, Pages, preview, staging, and production terminology.
- `incidents/2026-07-26-cloudflare-pages-git-connection-confusion.md` — records the World Feed hosting-guidance failure and corrective actions.
- `docs/portfolio/BUSINESS_CANDIDATE_BACKLOG.md` — idea-preservation backlog and proposed Business map.
- Permanent open tracking issue: `#154 Portfolio UI Factory: permanent open queue for new Business reference demos`.

## Current portfolio mode

`UI_ONLY`

For newly introduced Businesses:

- build and approve the visual UI first;
- use a dedicated, correctly connected hosted-review site when the user needs browser inspection;
- treat hosted review as evidence infrastructure, not product production deployment;
- verify Pages project, repository, branch, root directory, exact SHA, visible identity, and assets before sharing a URL;
- reject successful deployments from an unrelated Pages project as invalid evidence;
- apply deterministic version queries to browser-served local CSS, JavaScript, and other cache-sensitive stable asset paths;
- keep each newly authored source file at or below 500 physical lines;
- preserve existing oversized files without forcing risky unrelated refactors, but do not grow them without explicit justification;
- organize new code by product domain or responsibility with clear folder and file names;
- open a separate UX issue only after `UI_APPROVED`;
- consider backend work only after `UX_APPROVED` and a separate user-authorized backend decision;
- do not mix UI, UX, authentication, databases, live models, hosting connection, and product release in one undifferentiated operation.

## Terminology rule

Cloudflare's setting named `Production branch` means the primary branch for that Pages project. It does not grant AI Revenue Lab product-production approval.

Use these distinct terms:

- Git branch and exact head;
- Pages project and Git connection;
- branch preview;
- hosted review;
- product production release.

## Code-structure rule

For all new Business and project work:

- version-query tokens must be deterministic and changed when the referenced asset bytes change;
- random values and request-time timestamps are prohibited as cache-busting tokens;
- new authored source files above 500 lines are blocked unless an explicit exception is approved;
- existing files already above 500 lines are grandfathered but should not increase;
- folders and files must describe domain ownership or responsibility rather than chronology, worker identity, or vague labels such as `new`, `final`, `temp`, or `misc`.

Issue #154 stays open while AI Revenue Lab continues creating or revisiting Businesses. Each Business is tracked separately across UI, UX, backend, hosted-review, asset-versioning, and code-structure states.