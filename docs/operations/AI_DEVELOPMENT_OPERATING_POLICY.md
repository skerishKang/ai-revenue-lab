# AI Development Operating Policy

- Status: **CANONICAL REPOSITORY OPERATING POLICY**
- Effective reset: 2026-08-14
- Design authority: `PORTFOLIO_DESIGN_OPERATING_SYSTEM.md`
- Evidence authority: `EVIDENCE_REQUIREMENTS.md`
- Deployment authority: `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md`

## 1. Purpose

AI Revenue Lab separates product authority, design decisions, implementation, validation, CTO review, owner decisions, merge and Production so that fast AI-assisted work does not turn into repeated broad rework.

The repository does not require a fixed `UI → UX → backend` product sequence. The Web CTO selects the smallest evidence slice that answers the current uncertainty.

A separate rule applies when the work contains a **new art direction or material visual redesign**: prove the visual direction cheaply before propagating it broadly.

## 2. Required roles

1. **User / Product Owner** — product goal, priorities, material product/business decisions, explicit owner visual acceptance where applicable.
2. **Web CTO** — current remote audit, work contract, architecture/safety boundaries, visual/evidence gates, final technical review.
3. **Web Developer** — authorized implementation, implementation self-check, Draft PR/report.
4. **Independent Local Validator** — independent exact-head browser/OS/hardware/local-runtime validation when required.

One actor may perform several non-independent stages, but:

```text
IMPLEMENTATION_ACTOR
!=
INDEPENDENT_LOCAL_VALIDATOR
```

for the same revision when independent validation is required.

## 3. Product-evidence model

Possible evidence targets include:

```text
PRODUCT_FRAMED
COMPETITIVE_DEMO
INVESTOR_DEMO
MVP_VERTICAL_SLICE
SERVICE_LED_PILOT
RUNTIME_PILOT
COMMERCIAL_HARDENING
OPERATING_PRODUCT
```

The work order identifies what is needed now: visual desirability, UX, deterministic simulation, service-led operation, local runtime, live backend/provider, auth/persistence, security or commercial hardening.

UI, UX, backend/runtime, security, deployment, market-reference, commercial and owner-visual verdicts remain separate.

## 4. Mandatory design-gate overlay for visual redesign

When the work is a new visual system, owner-rejected redesign or broad multi-route visual reset, use:

```text
PRODUCT FRAME
→ REFERENCE TRANSLATION
→ ANCHOR SCREEN
→ ANCHOR_DIRECTION_LOCKED
→ 2–3 ARCHETYPES
→ ARCHETYPE_SYSTEM_PASS
→ FULL_EXPANSION_ALLOWED
→ FULL-SURFACE CONTACT SHEET
→ FULL_SURFACE_VISUAL_PASS
```

UX/backend work may proceed separately when authorized, but an unproven art direction must not be applied across the whole product.

The Web CTO must reject a work order that says, in effect, “redesign all pages now and we will see if the concept works afterward,” unless the product is so small that all distinct surfaces are themselves the archetype set.

## 5. Reference discipline

For material visual work, references are implementation inputs only after they are translated into:

```text
OBSERVE
ADOPT
REJECT
TRANSLATE
TARGET SURFACE
VERIFY
```

Business 06 World Feed is the positive portfolio methodology reference because it established a visual baseline and explicit adopted/rejected patterns before UX expansion. Its actual look is not a portfolio template.

## 6. Work identity before implementation

Record:

- repository/default branch;
- exact current base SHA;
- branch;
- Issue/owner/work-order authority;
- selected evidence stage;
- current visual gate if applicable;
- allowed/forbidden paths;
- non-goals;
- required automated checks;
- independent validation requirement;
- owner-only decision requirement;
- merge/deployment authority;
- acceptance criteria.

`latest main` is not revision identity.

## 7. Web CTO responsibilities

The Web CTO:

- reads current remote state rather than trusting previous reports;
- fixes exact scope and evidence target;
- enforces reference/anchor/archetype gates for material visual work;
- defines data/security/deployment/non-goal boundaries;
- inspects actual diff and current exact head;
- checks CI and validation sufficiency;
- reviews rendered visual evidence rather than treating CI as taste evidence;
- rejects stale-head evidence unless applicability is documented;
- prevents legacy visual debt from being mislabeled as a new design system;
- assigns final technical `READY / CONDITIONALLY_READY / NOT_READY`.

These statuses never manufacture owner approval or commercial approval.

## 8. Web Developer responsibilities

The developer:

- starts from the authorized exact base or reports drift;
- changes only authorized paths;
- implements only up to the current authorized visual/product gate;
- does not expand all routes when the work order authorizes only an anchor/archetype slice;
- runs implementation self-checks and configured CI;
- records exact base/head, files, diff, commands, exits, pass/fail/skip counts and limitations;
- identifies legacy/cascade debt encountered;
- does not self-assign independent validation or final CTO readiness.

## 9. Visual implementation discipline

For a redesign:

- weak legacy shells may be replaced when the visual thesis requires it;
- redesign is not synonymous with recoloring/material skinning;
- a successful landing page does not prove inner-route coherence;
- a later-route failure must be diagnosed before a new version/concept is created;
- superseded visual generations should leave the active rendering path once the new system is proven;
- repeated `!important` override escalation is a debt signal, not completion.

Follow `CODE_STRUCTURE_AND_ASSET_VERSIONING_POLICY.md`.

## 10. Local Validator responsibilities

When independent validation is required, the validator records:

- expected/actual exact head;
- environment;
- repository/source-modification state;
- commands/exits;
- journeys/results;
- browser/device evidence;
- console/page/network/asset/overflow failures;
- artifacts and reproduction evidence.

If the validator changes product source, the modified run is not independent validation of that new revision.

## 11. CI and automated checks

CI is required when configured/relevant but is never universal completion evidence.

- static/lint tests do not prove visual hierarchy;
- browser mechanics do not prove cross-state art direction;
- screenshots of Entry do not prove a whole site;
- mock/provider tests do not prove live provider behavior;
- HTTP 200 does not prove reviewed Production revision.

Use the evidence type that matches the claim.

## 12. Revision invalidation

Evidence belongs to the exact tested revision. A new commit affecting the judged behavior/surface may invalidate prior evidence.

Before merge, re-read:

- current `main`;
- PR exact head;
- changed files/diff;
- CI/checks;
- comments/review threads;
- required visual/UX/runtime/security evidence;
- applicable anchor/archetype/full-surface status.

Use expected-head protection where available.

## 13. Safety and scope rules

- no ordinary direct `main` feature mutation;
- no unrelated dirty-file inclusion;
- no out-of-scope mutation without contract update;
- no test/assertion/security weakening merely to pass;
- no hidden failure/skip/warning;
- no secrets, credentials, private evidence or personal data in public source/logs/artifacts;
- no hidden validator source edits;
- no wrong-project Preview/deployment as product evidence;
- no unverified live-revision claim.

## 14. Owner visual authority

The CTO may reject objective defects: overflow, clipping, unreadable contrast, broken hierarchy, functional controls, responsive breakage, inconsistent typography/cross-state system, visible legacy leakage and product-contract mismatch.

Only explicit current owner acceptance creates `OWNER_UI_APPROVED`.

```text
ANCHOR_DIRECTION_LOCKED != OWNER_UI_APPROVED
ARCHETYPE_SYSTEM_PASS != OWNER_UI_APPROVED
FULL_SURFACE_VISUAL_PASS != OWNER_UI_APPROVED
READY != OWNER_UI_APPROVED
DEPLOYED != OWNER_UI_APPROVED
```

## 15. Backend and service-led evidence

Select the smallest appropriate mode:

```text
NO_BACKEND
DETERMINISTIC_SIMULATION
SERVICE_LED
LOCAL_RUNTIME
LIVE_VERTICAL_SLICE
PILOT_RUNTIME
COMMERCIAL_HARDENING
```

Backend may start early when it proves product value. Do not build it as ceremony.

Authentication is not mandatory for every MVP; authorization is mandatory whenever private records can be read/mutated.

## 16. Merge and Production

For focused changes inside a stable design system, the live Production owner-review loop may be appropriate after exact-head validation.

For a new art direction/material redesign, follow `LIVE_PRODUCTION_UI_REVIEW_POLICY.md`: anchor and archetype proof precede broad expansion/whole-product live review.

After authorized merge, verify the configured Git-connected Production against the resulting main/release revision.

## 17. Historical records

Historical phase, UI approval, direction-freeze and audit records remain truthful evidence of their time. They do not override this current operating policy.

In particular, a historical product direction document is now an implementation input/hypothesis until it satisfies the current anchor/archetype process for new material visual work.

## 18. Supporting documents

- Design OS: `PORTFOLIO_DESIGN_OPERATING_SYSTEM.md`
- Visual standard: `ui-ux/UI_UX_VISUAL_DIRECTION_STANDARD.md`
- Workflow states: `WORKFLOW_STATUS_MODEL.md`
- Evidence: `EVIDENCE_REQUIREMENTS.md`
- UI/UX/backend dimensions: `UI_UX_BACKEND_PHASE_GATES.md`
- Frontend structure: `CODE_STRUCTURE_AND_ASSET_VERSIONING_POLICY.md`
- New/rebuilt Business playbook: `NEW_BUSINESS_UI_FIRST_PLAYBOOK.md`
- Live visual review: `LIVE_PRODUCTION_UI_REVIEW_POLICY.md`
- Templates: `templates/`
