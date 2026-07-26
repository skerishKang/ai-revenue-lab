# Operations Documents

- `UI_UX_BACKEND_PHASE_GATES.md` — mandatory sequence and approval gates: product framing → UI → UX → backend decision → backend implementation.
- `NEW_BUSINESS_UI_FIRST_PLAYBOOK.md` — reusable Phase 1 visual-UI policy for every new or revived Business.
- `CLOUDFLARE_PAGES_GIT_CONNECTION_RUNBOOK.md` — separates Git state, Pages project connection, hosted review, and product production release.
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

Issue #154 stays open while AI Revenue Lab continues creating or revisiting Businesses. Each Business is tracked separately across UI, UX, backend, and hosted-review states.