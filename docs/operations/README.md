# Operations Documents

- `../portfolio/AI_REVENUE_LAB_OPERATING_INTENT.md` — canonical reason the Lab and Portfolio Console exist.
- `UI_UX_BACKEND_PHASE_GATES.md` — mandatory scope and approval separation: product framing → UI → UX → backend decision → backend implementation.
- `NEW_BUSINESS_UI_FIRST_PLAYBOOK.md` — reusable Phase 1 visual-UI policy for every new or revived Business.
- `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md` — default direct-Production execution, smoke acceptance, optional Preview exceptions, and rollback.
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
explicit deployment authorization
→ validated exact main
→ dedicated Production
→ immediate Production acceptance
→ retain or rollback
```

- Deployment default: `DIRECT_PRODUCTION_AFTER_EXPLICIT_AUTHORIZATION`
- Preview: `OPTIONAL_NOT_REQUIRED`
- Rollback: `MANDATORY_PREPARED_GATE`

Preview or staging is used only for a concrete product, data, billing, authorization, compliance, external-review, or owner-requested reason.

## Operator standard

- Prefer authenticated connectors, API, and CLI automation over repeated owner Dashboard work.
- Verify current interfaces and permission contracts before instructing the owner.
- Do not invent controls, permission names, or menu labels.
- Group genuinely owner-only actions into one bounded request.
- Keep credentials and private identity out of chat, source, logs, and evidence.

Issue #154 stays open while AI Revenue Lab continues creating or revisiting Businesses. Each Business is tracked separately across UI, UX, backend, deployment, and business-evidence states.
