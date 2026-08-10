# AI Revenue Lab — Visual Audit → Documentation → Implementation → Conformance Protocol

Status: `AUTHORITATIVE_DRAFT_FOR_OWNER_REVIEW`

This protocol replaces the prior habit of opening each numbered Business and immediately deciding `KEEP / polish / redesign` while implementation is still in motion.

The new sequence is intentionally separated into four gates.

```text
GATE A — READ-ONLY PORTFOLIO AUDIT
        ↓
GATE B — VISUAL DIRECTION DOCUMENT FREEZE
        ↓
GATE C — NUMBERED IMPLEMENTATION
        ↓
GATE D — INDEPENDENT VISUAL CONFORMANCE QA
```

No Business proceeds to implementation merely because its automated QA is green.

---

## 1. Global pause rule

While Gate A/B is active for the portfolio:

- do not continue numbered product redesign implementation;
- do not merge visual changes merely to keep sequence momentum;
- do not reinterpret `OWNER_UI_APPROVED=false` as approval;
- do not alter external / integrated-successor products from this repository;
- do not leave temporary audit/deploy workflows in main;
- do not restart already-known functional/backend work unless a visual audit identifies a real contract conflict.

Existing live surfaces remain review evidence, not automatic baselines to preserve.

---

# GATE A — Read-only portfolio audit

## 2. Scope resolution before visual judgment

For each numbered Business, first classify authority:

```text
INTERNAL_LIVE_PRODUCT
INTERNAL_REVIEW_SURFACE
EXTERNAL_IMPLEMENTATION
EXPANDED_SUCCESSOR
INTEGRATED_SUCCESSOR
NON_WEB
UNKNOWN_REQUIRES_RESOLUTION
```

Use the current repository truth layer, current review-surface registry, authoritative PR/Issue lineage and actual live URL.

External/successor/non-web items are documented but are not redesigned internally.

---

## 3. Mandatory evidence per internal web Business

Audit the real rendered surface at minimum:

- Desktop: `1440 × 1100` or the product's established desktop QA viewport;
- Mobile: `390 × 844`;
- canonical root;
- Guide/onboarding when present;
- primary action state;
- primary result/payoff state;
- one important recovery/error/feedback state when applicable.

The reviewer must inspect screenshots directly.

Automation may collect geometry and errors, but a numeric pass is insufficient.

Record:

- exact `origin/main` FULL SHA at audit start;
- exact product/review authority SHA if not current main;
- canonical Production/review URL;
- whether live bytes match the expected authority where required;
- screenshots examined;
- visual observations;
- interaction/state observations;
- Desktop vs Mobile differences.

---

## 4. Audit questions

Every Business audit must answer:

### Product identity

- What is the product's actual job?
- What is the core transformation?
- Is that transformation visible, or only explained in text?

### First viewport

- What dominates the first 3–5 seconds?
- Is the core object visible?
- Is the first action clear?
- Could this first viewport plausibly belong to another numbered Business?

### References

- What references were originally provided or researched?
- Which reference qualities are visible now?
- Which were diluted, lost or incorrectly generalized?

### Visual system

- Is there one coherent world across states?
- Is the hierarchy authored or templated?
- Is imagery/material meaningful or decorative?
- Are repeated portfolio motifs making this product generic?

### Utility

- Is the core interaction visually obvious?
- Is useful information subordinate to decoration or whitespace?
- Does a new user understand `START → ACTION → RESULT`?

### Typography

- Are Korean display sizes and line breaks controlled?
- Is line-height visually safe?
- Does Mobile retain readable hierarchy?

### Mobile

- Does chrome cover/push content?
- Is the first real work/action visible soon enough?
- Does the composition re-author rather than merely stack?

### Verdict

Choose only after viewing actual evidence:

```text
KEEP
FOCUSED_POLISH
REDESIGN
EXTERNAL_NO_INTERNAL_BUILD
NON_WEB
```

---

# GATE B — Visual Direction document freeze

## 5. Required output

Every internal web Business must receive:

```text
docs/operations/ui-ux/businesses/B##_VISUAL_DIRECTION.md
```

before implementation.

The document becomes the implementation contract for visual work.

It must contain:

- authority/evidence snapshot;
- current diagnosis;
- Product Visual Thesis;
- Reference Translation Sheet;
- preserved functional/state contracts;
- explicit visual territory;
- key screens and desired composition;
- focal asset plan;
- typography plan;
- Mobile composition plan;
- motion grammar;
- How-to-use path;
- anti-patterns;
- differentiation against related Businesses;
- `KEEP / FOCUSED_POLISH / REDESIGN` decision;
- observable acceptance criteria.

Do not freeze vague prose such as “make it premium and cinematic.”

Acceptance criteria must be screenshot-observable.

---

## 6. Portfolio collision review

After the individual documents are drafted and before implementation begins, update:

```text
PORTFOLIO_VISUAL_DIFFERENTIATION_MATRIX.md
```

Check for collisions in:

- dark/light visual world;
- editorial/archive metaphor;
- terminal/control-room metaphor;
- magazine/feed metaphor;
- left-rail/right-workspace composition;
- card grids;
- oversized condensed type;
- color palettes;
- motion patterns;
- numbered ledger/navigation motifs.

If several products converge, revise their direction documents before code is changed.

---

# GATE C — Numbered implementation

## 7. Required reading order for implementers

Every UI implementer must read, in order:

1. `UI_UX_VISUAL_DIRECTION_STANDARD.md`
2. `VISUAL_AUDIT_AND_IMPLEMENTATION_PROTOCOL.md`
3. `PORTFOLIO_VISUAL_DIFFERENTIATION_MATRIX.md`
4. the target `B##_VISUAL_DIRECTION.md`
5. authoritative target Issue/PR/product contract
6. actual current Desktop/Mobile screenshots or live surface

Implementation instructions should explicitly say that the Business direction document is authoritative for art direction while functional/backend/state contracts remain preserved unless separately authorized.

---

## 8. Implementation boundaries

### KEEP

No cosmetic churn. Change only if required to preserve or document current quality.

### FOCUSED_POLISH

Touch only the documented bounded defects. Do not accidentally redesign the whole product.

### REDESIGN

A genuine redesign may replace visual shells, assets, layout systems and motion grammar, but must preserve required feature/state/backend contracts.

A redesign is not complete because the diff is large. It is complete only if the promised perceptual difference is visible.

---

## 9. Reference implementation ledger

The implementation PR must include a compact ledger:

| Reference translation | Target surface | Implemented evidence |
|---|---|---|
| Example pattern | Entry | screenshot/artifact path |

This prevents reference work from disappearing between research and implementation.

---

## 10. Technical QA remains mandatory

Depending on the Business, verify:

- expected routes/states;
- no unexpected backend/Auth/DB/API changes;
- no horizontal overflow;
- no console/page errors;
- no broken required assets;
- no unauthorized external runtime requests;
- keyboard operation and visible focus;
- reduced-motion behavior;
- Desktop and Mobile viewport behavior;
- product-specific state/recovery contracts.

But do not mark visual completion from these checks alone.

---

# GATE D — Independent visual conformance QA

## 11. Reviewer independence

The post-implementation reviewer should evaluate the result against the frozen direction document, not against the implementer's PR description.

The reviewer must answer: **Did the promised design actually appear on screen?**

---

## 12. Conformance matrix

For each load-bearing criterion, assign:

```text
MATCH
PARTIAL
MISS
NOT_APPLICABLE
```

Required dimensions:

| Dimension | What to inspect |
|---|---|
| Reference fidelity | Are the translated reference qualities actually visible? |
| Product distinctiveness | Does it clearly differ from neighboring Businesses? |
| First viewport | Identity + core object + first action within 3–5 seconds |
| Hierarchy | Does the eye move through the intended product sequence? |
| Asset quality | Are focal visuals product-grade and meaningful? |
| Korean typography | Scale, wrapping, tracking, line-height, body readability |
| Interaction clarity | Is the current task/action obvious? |
| Mobile composition | Proper reorder/crop/chrome/action hierarchy at 390px |
| Cross-state coherence | One authored product world across routes/states |
| How-to-use clarity | `START → ACTION → RESULT` is understandable |

Any load-bearing `MISS` means the implementation is not visually complete.

---

## 13. Before/After perceptual check

For `REDESIGN`, the reviewer must compare old vs new evidence side by side conceptually and answer:

- Is the difference obvious without reading the PR?
- Did the redesign change visual material/hierarchy, not only CSS values?
- Does the new version better express the product's unique job?
- Are provided references more visible after the redesign?

If substantial code changed but the user would reasonably ask “what changed?”, classify the redesign as insufficient.

---

## 14. Production review

Where project policy requires Production review:

```text
validated implementation
→ merge
→ exact-main deploy
→ verify live bytes/state
→ inspect actual Production Desktop/Mobile
→ owner review
```

The owner alone may provide final visual approval.

```text
OWNER_UI_APPROVED=false
```

must not be changed by automation or reviewer inference.

---

# Portfolio execution order after this protocol

## 15. Current transition plan

The prior numbered implementation/audit sequence is paused.

The next program sequence is:

```text
1. establish common visual governance documents
2. re-audit all internal web Businesses read-only
3. write/freeze every B##_VISUAL_DIRECTION.md
4. complete portfolio differentiation review
5. begin implementation again at B01
6. independently verify B01 against its document
7. proceed number-by-number only after conformance is proven
```

Business 01 is the first redesign candidate under the new protocol.

Business 06 is retained as a positive methodology case study, not as a universal visual template.
