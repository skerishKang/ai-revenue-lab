# Direct Production Deployment and Rollback Policy

- Status: portfolio operating policy
- Authority: #326
- Supersedes: Preview-first deployment model (all prior versions)
- Applies to: all AI Revenue Lab Cloudflare Pages projects and Workers that serve authorized Production traffic

## 1. Purpose

Define the default deployment model for every AI Revenue Lab Business: deploy verified `main` directly to a dedicated Production environment, run immediate acceptance checks, and roll back on critical failure.

Preview is optional and may be used only when a Business-specific issue explicitly requires it (Section 13).

## 2. Scope

- Cloudflare Pages projects connected to this repository
- Cloudflare Workers that serve Production traffic
- Deployment authorization, execution, acceptance, and rollback
- Environment variables, encrypted secrets, KV namespace bindings
- Production Access boundaries

This policy does not cover:

- Phase approval (UI, UX, backend — see `UI_UX_BACKEND_PHASE_GATES.md`)
- Source validation or testing (see the applicable playbook)
- Incident response unrelated to deployment

## 3. Terminology

| Term | Definition |
|---|---|
| Production | The environment serving the canonical public domain for a Business |
| Preview | An ephemeral Cloudflare deployment on a hash-based hostname (<hash>.<project>.pages.dev) |
| Smoke acceptance | Immediate post-deployment verification of critical Production behavior |
| Rollback authority | The known-good Production deployment ID and configuration that will be restored on failure |
| Exact head | The specific Git SHA that was reviewed, approved, and deployed |
| Dedicated project | A Cloudflare Pages or Worker project scoped to exactly one Business |

## 4. Default deployment model

```text
validated source
→ approved exact-head merge
→ direct Production deployment
→ Production acceptance
→ keep or rollback
```

Preview is not part of this flow. A platform defect in Preview must not block direct Production deployment when a safe rollback path exists.

## 5. Deployment authorization boundary

- `UI_APPROVED` does not authorize merge or deployment
- `UX_APPROVED` does not authorize merge or deployment
- Deployment requires separate user authorization
- When the user authorizes deployment, the default target is the dedicated Business Production project
- Deployment does not imply UI, UX, backend, or product approval
- A green deployment under the wrong Cloudflare project is invalid evidence

## 6. Exact-head validation

Before Production deployment, verify:

- `origin/main` is current and matches the expected SHA
- The deployed source is byte-equivalent to the approved exact head
- No new commits were silently introduced
- Scope and changed files match what was reviewed

## 7. Merge contract

When a PR is involved:

- Use expected-head-fixed merge (not squash or rebase that rewrites history)
- The merged SHA must match the reviewed exact head
- The PR must not be marked Ready or merged until deployment authorization is confirmed

## 8. Dedicated Cloudflare project ownership

Every Production-bearing Business uses its own dedicated project:

```text
Cloudflare Pages project: ai-revenue-<business-stable-slug>
Repository: skerishKang/ai-revenue-lab
Production branch: main
Root directory: apps/<product>/ or reference/<business>/ as applicable
```

- Never deploy to another Business's project
- Never reuse an unrelated project
- Never deploy a project that does not match the Business identity

## 9. Production secrets and bindings

Production secrets and KV bindings are configured only through an authorized Production activation issue.

- Use `"type":"secret_text"` for encrypted secrets
- Do not create default Preview secrets, KV, or Access applications
- Record secret names (not values) and KV namespace title in deployment evidence
- Never echo, log, screenshot, or commit secret values

## 10. Production smoke acceptance

Immediately after deployment, verify the applicable subset:

- TLS and certificate validity
- Access/auth boundary (unauthenticated redirected, authenticated allowed)
- Root and critical route HTTP status (200, not 5xx)
- Exact deployed SHA matches the approved source
- No credential, token, email, or internal path leakage
- Required API endpoints return correct schema and status codes
- Cache and stale-fallback behavior when applicable
- Static assets load without 404 or 5xx
- Console errors: 0, CSP violations: 0
- Business-critical desktop and mobile flows

## 11. Rollback preparation

Before every Production change:

1. Record the current Production deployment ID
2. Record the current Production configuration (secrets, KV, Access)
3. Store the rollback baseline outside the deployment session

Rollback authority must be verifiable without the deployment session that created it.

## 12. Mandatory rollback triggers

Rollback immediately (no additional user approval required) when:

| Trigger | Evidence |
|---|---|
| Root or critical route returns 5xx or is unreachable | curl HTTP status |
| Access/auth bypass or lockout | Unauthenticated access succeeds, or authenticated access fails |
| Repeated required API 5xx | Three consecutive failures |
| Invalid response schema or materially incorrect data | Schema validation failure |
| Credential or secret leakage | Token, key, email, or internal path in public response |
| Broken runtime or static shell | Page fails to render or critical JS/CSS missing |
| Unusable critical desktop or mobile flow | Primary user journey broken |

Rollback procedure:

1. Restore the prior deployment using `POST /deployments/{id}/rollback` or equivalent API
2. Remove any new secrets or KV bindings introduced as part of the failed deployment
3. Verify restored deployment passes smoke acceptance
4. Record rollback execution evidence

## 13. Optional Preview exceptions

Preview is optional, not prohibited. Use Preview only when a Business-specific issue explicitly requires it, for example:

- Destructive database or migration rehearsal
- External stakeholder review that must not touch Production
- High-risk auth or billing change
- Regulatory or compliance requirement
- User explicitly requests a Preview URL

When Preview is used:

- Create Preview secrets, KV, and Access only for the duration of the Preview phase
- Remove Preview bindings before Production activation
- Record the Preview scope and cleanup in the issue

Do not spend extended time repairing Preview-only infrastructure when Production has a safe direct-deploy and rollback path. Escalate platform defects separately.

## 14. Preview/platform blocker handling

If Preview is unavailable or defective:

1. Record the platform defect in a separate issue
2. Do not treat Preview failure as a Production blocker
3. If the defect is platform-wide (not Business-specific), proceed with direct Production deployment

Exception: if the issue explicitly requires Preview (Section 13), the Preview blocker must be resolved before proceeding. If the blocker cannot be resolved, the user must re-authorize the deployment path.

## 15. API/CLI-first owner interaction

- Prefer authenticated API/CLI operations over repeated owner Dashboard clicks
- Ask for owner action only when the platform genuinely requires a one-time browser-authenticated operation
- Never invent Dashboard controls, API permission names, or menu labels
- Before instructing the owner, inspect the actual current UI/API or authoritative documentation
- Do not repeatedly ask the user to perform configuration that the scoped API token can perform
- Batch owner-only actions into one request when possible
- Never request passwords, OTPs, tokens, cookies, or private keys in chat
- Use scoped short-lived tokens when available
- Report sensitive material as presence only (exists / does not exist), never the value

## 16. Evidence requirements

Every Production deployment must record:

- Exact deployed source SHA
- Production deployment ID and URL
- Smoke acceptance results (pass/fail per applicable check)
- Rollback baseline deployment ID
- Rollback execution status (not needed / executed / failed)

Evidence must not include:

- Secret values, tokens, or private keys
- Account IDs, email addresses, or personal data
- Access cookies or session tokens

## 17. Disposition vocabulary

| Status | Meaning |
|---|---|
| `DIRECT_PRODUCTION_POLICY_DOCUMENTED` | Canonical policy exists and reflects owner decision |
| `PREVIEW_OPTIONAL_NOT_REQUIRED` | Preview is no longer a mandatory gate |
| `ROLLBACK_FIRST_OPERATIONS_ACTIVE` | Rollback baseline recorded before every deployment |
| `PRODUCTION_ACCEPTANCE_PASSED` | Smoke acceptance verified after deployment |
| `PRODUCTION_ACCEPTANCE_FAILED` | Smoke acceptance failed; rollback executed |
| `BLOCKED_PREVIEW_TLS_HANDSHAKE` | Preview TLS defect recorded as platform issue |

## 18. Business-specific exceptions

### Portfolio Console (Business — Operations)

```text
Project: ai-revenue-portfolio-console
Production branch: main
Default: direct main → Production
Preview: not required
Hash Preview TLS defect: #324 — not a Production blocker
Production secrets/KV: configured through authorized Production activation
```

### Other Businesses

Each Business may have its own deployment constraints recorded in its workspace documentation. Where this policy conflicts with a Business-specific document, this policy takes precedence unless the Business explicitly records an exception approved by the owner.

## 19. Risk matrix

| Level | Description | Required gates |
|---|---|---|
| D0 | Documentation only, no deploy | Source validation |
| D1 | Static UI/content deployment | Source validation, exact head, Production smoke, rollback ready |
| D2 | Frontend runtime / API consumer | D1 + deterministic tests, browser tests, exact API contract |
| D3 | Backend / secrets / cache / auth | D2 + full tests, secret boundary, rollback deployment + config, security checks, destructive-operation review |
| D4 | Migration / billing / destructive data | D3 + Preview/staging may become explicitly required, separate owner authorization, recovery rehearsal |

Preview is a default candidate only at D4 and when explicitly required (Section 13).