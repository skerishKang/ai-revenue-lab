# Operations Documents

- `../portfolio/AI_REVENUE_LAB_OPERATING_INTENT.md` — canonical reason the Lab and Portfolio Console exist.
- `UI_UX_BACKEND_PHASE_GATES.md` — mandatory scope and approval separation: product framing → UI → UX → backend decision → backend implementation.
- `NEW_BUSINESS_UI_FIRST_PLAYBOOK.md` — reusable Phase 1 visual-UI policy for every new or revived Business.
- `EXTERNAL_DEVELOPMENT_PROJECTS_POLICY.md` — external-development projects are list/link only inside AI Revenue Lab; do not create internal placeholder, anchor, UI/UX, or backend folders unless the owner explicitly authorizes source migration.
- `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md` — Git-connected automatic Production execution, smoke acceptance, explicitly owner-authorized Preview exceptions, and reviewed fix/revert recovery.
- `../portfolio/BUSINESS_CANDIDATE_BACKLOG.md` — idea-preservation backlog and proposed Business map.
- Permanent open tracking issue: `#154 Portfolio UI Factory: permanent open queue for new Business reference demos`.

## Current portfolio mode

`UI_ONLY`

For newly introduced Businesses:

- build and approve the visual UI first;
- open a separate UX issue only after `UI_APPROVED`;
- consider backend work only after `UX_APPROVED` and a separate user-authorized backend decision;
- do not mix UI, UX, authentication, databases, live models, and deployment authority in one issue.

The phase gates exist to prevent scope and evidence confusion. They are not intended to maximize ceremony or delay work that has already been authorized.

## Deployment default

```text
explicit merge and Production authorization
→ approved merge to the configured Production branch
→ automatic Production deployment by the existing Git integration
→ immediate Production acceptance
→ retain or merge a reviewed fix/revert PR
```

- Deployment default: `AUTOMATIC_GIT_CONNECTED_PRODUCTION`
- Preview: `DISABLED_UNLESS_EXPLICITLY_OWNER_AUTHORIZED`
- Source recovery: `FIX_OR_REVERT_PR_AND_AUTOMATIC_DEPLOYMENT`

For Git-connected Pages:

- no Wrangler/direct upload;
- no API deployment creation or retry;
- no Dashboard retry;
- no Preview creation or promotion;
- no staging substitution;
- no empty trigger commit;
- no cancellation and replacement of a Git-triggered deployment.

Preview or staging is not an operator option. It may be introduced only by a new explicit owner decision or by an already approved Business-specific contract that names the exception.

## Operator standard

- Prefer authenticated connectors, API, and CLI **for inspection and authorized configuration only**, not for deployment creation.
- Verify current interfaces and permission contracts before instructing the owner.
- Do not invent controls, permission names, or menu labels.
- Group genuinely owner-only actions into one bounded request.
- Keep credentials and private identity out of chat, source, logs, and evidence.
- Never ask the owner to choose an alternate deployment mechanism when a Git-triggered automatic deployment is queued, stuck, or failed.

Issue #154 stays open while AI Revenue Lab continues creating or revisiting Businesses. Each Business is tracked separately across UI, UX, backend, deployment, and business-evidence states.
