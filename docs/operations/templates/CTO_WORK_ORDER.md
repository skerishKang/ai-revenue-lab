# Web CTO Work Order

## Authority / revision

- Issue / owner request:
- Repository:
- Default branch:
- Exact current base SHA:
- Target branch:
- Product-evidence stage:

## Objective

State the smallest user/product outcome this revision must prove.

## Product / visual gate

For user-facing visual work record:

- Material new art direction/redesign? yes/no:
- Existing direction/reference material read:
- Current visual gate:
- Anchor route/state:
- Planned archetypes (2–3 distinct types):
- `FULL_EXPANSION_ALLOWED` already? yes/no:
- If visual gate is `NOT_REQUIRED`, reason:

For a material redesign, do not authorize full-route styling before `ARCHETYPE_SYSTEM_PASS`.

## Reference Translation Sheet

When required:

| Reference | Observe | Adopt | Reject | Translate | Surface | Verify |
|---|---|---|---|---|---|---|
| | | | | | | |

## Scope

- Allowed paths:
- Forbidden paths:
- Non-goals:
- Existing behavior/contracts to preserve:
- Legacy UI allowed to replace:
- External systems allowed:
- Data/secret boundary:

## Source/cascade plan

For material frontend redesign:

- Current active visual entrypoints:
- Superseded layers expected to leave active load path:
- Typography delivery/fallback plan:
- Asset source/usage manifest:
- Compatibility hooks that must remain behavior-only:

## Evidence dimensions

Mark `REQUIRED`, `NOT_REQUIRED`, or `DEFERRED_WITH_REASON`:

- Technical implementation:
- Anchor visual evidence:
- Archetype system evidence:
- Full-surface contact sheet:
- Korean typography:
- Mobile composition:
- UX/journey:
- Backend/runtime:
- Security/privacy:
- Market/reference:
- Commercial/business:
- Production:

## Role plan

- Web CTO:
- Web Developer:
- Independent Local Validator required? yes/no + reason:
- Owner-only decision required? yes/no + reason:

Implementation actor and independent Local Validator must not be the same actor for the same revision.

## Acceptance criteria

1.
2.
3.

For visual work, include the exact gate that this revision must reach. Do not use vague criteria such as `looks premium`.

## Required checks

- Automated commands:
- CI/checks:
- Browser/local validation:
- Required Desktop viewport(s):
- Required Mobile viewport(s):
- Side-by-side/contact-sheet artifact:
- Exact-head evidence:
- Cascade/font/asset evidence:
- Production acceptance, if authorized:

## Failure handling

If visual work fails, classify before authorizing a new concept/version:

```text
CONCEPT_FAILURE
REFERENCE_TRANSLATION_FAILURE
ANCHOR_COMPOSITION_FAILURE
ARCHETYPE_SYSTEM_FAILURE
TYPOGRAPHY_FAILURE
ASSET_FAILURE
LEGACY_SHELL_FAILURE
IMPLEMENTATION_CASCADE_FAILURE
MOBILE_COMPOSITION_FAILURE
```

## Merge / deployment authority

- Merge authorization source:
- Art-direction gate satisfied for proposed scope? yes/no/N/A:
- Expected head required:
- Deployment risk/lane:
- Preview/staging exception: none unless explicitly authorized.
