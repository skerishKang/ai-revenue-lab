# Development Evidence Requirements

- Status: **CANONICAL**
- Parent design authority: `PORTFOLIO_DESIGN_OPERATING_SYSTEM.md`

## 1. Revision identity

Every implementation, validation and final-review report records:

- repository/default branch;
- exact starting base SHA;
- target branch;
- exact reported/tested/reviewed head SHA;
- base/head relationship where relevant;
- repository/worktree state or branch-only write method.

Evidence belongs to the exact revision it tested unless applicability to a newer revision is explicitly reviewed.

## 2. Scope evidence

Record:

- selected evidence stage and visual gate if applicable;
- allowed/forbidden paths;
- exact changed-file list;
- reason for each changed file;
- diff statistics/reference;
- explicit non-goals;
- unrelated-change absence.

## 3. Visual thesis and reference evidence

For a new art direction/material redesign, record before broad implementation:

- current `B##_VISUAL_DIRECTION.md` or equivalent visual thesis;
- product job/core transformation;
- reference list;
- for each load-bearing reference: `OBSERVE / ADOPT / REJECT / TRANSLATE / SURFACE / VERIFY`;
- anti-patterns;
- legacy reuse/replace decision.

A mood word or reference URL list alone is insufficient.

## 4. Anchor evidence

`ANCHOR_DIRECTION_LOCKED` requires at minimum:

- exact anchor route/state;
- Desktop screenshot (normally 1440px-class viewport unless product-specific evidence says otherwise);
- 390px Mobile screenshot;
- direct visual review notes;
- actual typography/fallback behavior where material;
- focal asset/core-object evidence where applicable;
- primary action/result hierarchy;
- overflow/clipping/load failures;
- responsive composition verdict.

The evidence must make clear what was accepted/locked and what remains unproven.

## 5. Archetype system evidence

`ARCHETYPE_SYSTEM_PASS` requires:

- anchor plus 2–3 structurally different archetype screens, or every distinct type for a smaller product;
- Desktop and Mobile screenshots for each;
- side-by-side/contact-sheet review;
- cross-state typography verdict;
- hierarchy/density verdict;
- material/color/asset continuity verdict;
- interaction-language verdict;
- explicit generic-SaaS/card/form fallback check;
- `MATCH / PARTIAL / MISS` against the Product Visual Thesis.

A set of individually acceptable screenshots does not pass if they do not look like one product together.

## 6. Full-surface visual evidence

For a multi-screen redesign, `FULL_SURFACE_VISUAL_PASS` requires an artifact containing every core user-facing route/state on Desktop and Mobile.

Review the contact sheet for:

- product identity continuity;
- typography consistency;
- hierarchy and density;
- core-object/component grammar;
- image/asset treatment;
- old-version/cascade leakage;
- mobile composition;
- unfinished-looking empty space;
- inaccessible or obscured controls;
- routes that revert to generic UI.

A load-bearing `MISS` blocks the pass unless the owner explicitly accepts it.

## 7. Typography evidence

When typography is material, record:

- intended display/body/reading roles;
- actual delivery/fallback strategy;
- rendered Desktop/Mobile screenshots;
- suspicious font fallback or mixed serif/sans behavior;
- Korean title line-height/tracking/line-shape review;
- body measure/line-height review.

Do not claim a family is rendered only because it appears first in `font-family`.

## 8. Visual cascade/source evidence

For a substantial redesign, record the active style entrypoints/load order and identify:

- superseded visual generations still active;
- duplicate typography/component authorities;
- material `!important` escalation;
- route-specific emergency layers;
- external font/image dependencies;
- planned/actual consolidation.

This is required when implementation-cascade debt could explain visual inconsistency.

## 9. Implementation evidence

The Web Developer report includes:

- exact base/head and branch;
- behavior/contracts changed;
- current visual gate and whether expansion was authorized;
- automated commands, status and pass/fail/skip counts;
- CI references when configured;
- self-check/browser evidence clearly labelled non-independent;
- known defects/deferred work/environment limits.

## 10. Independent validation evidence

When required, record:

- expected/actual tested head;
- validator role relative to implementation;
- OS/runtime/browser/hardware environment;
- source-modification status;
- commands/exits;
- required journeys/results;
- Desktop/Mobile/reduced-motion/focus evidence when relevant;
- console/page/request/overflow/asset failures;
- artifacts and reproducible failure evidence.

If the validator changes product source, the run is not independent validation of the resulting revision.

## 11. Runtime/provider evidence

Distinguish deterministic mock, source-equivalent local execution, exact-head local execution, live provider/API, Preview/staging and Production.

Record provider/runtime identity, request/route evidence, timeout/retry/fallback boundaries, cost/security basis and whether secrets were required. Never expose credentials.

## 12. Production evidence

Follow `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md` and record the relevant subset of:

- resulting main/release SHA;
- deployment/version ID;
- project/Worker identity;
- root/source directory;
- canonical hostname;
- critical browser/API journey;
- console/page/network failures;
- auth/access behavior;
- revision linkage;
- known-good recovery source.

HTTP 200 alone is not revision identity.

## 13. CTO final-review evidence

The final review records:

- exact reviewed head and current main/base relationship;
- changed files/scope verdict;
- acceptance matrix;
- current visual gate;
- anchor/archetype/contact-sheet evidence as applicable;
- CI/independent-validation sufficiency;
- security/privacy/regression considerations;
- owner-only decisions;
- remaining conditions;
- final technical `READY / CONDITIONALLY_READY / NOT_READY`.

## 14. Evidence rejection conditions

Do not rely on these as completion evidence:

- test results without revision identity;
- another head's screenshots without applicability review;
- automated GREEN without direct visual review for a visual claim;
- only the Entry screenshot for a multi-screen redesign;
- screenshots from the wrong project/deployment;
- a list of reference names with no translation/verification;
- implementer self-check represented as independent validation;
- a strong anchor represented as whole-product design-system proof;
- hidden failed/skipped counts;
- unverified Production claims;
- evidence containing secrets/private data.
