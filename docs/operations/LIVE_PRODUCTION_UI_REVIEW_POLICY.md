# Live Production UI Review Policy

- Status: **CANONICAL**
- Effective reset: 2026-08-14
- Parent design authority: `PORTFOLIO_DESIGN_OPERATING_SYSTEM.md`
- Deployment authority: `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md`

## 1. Decision

Owner review may still use the actual Production surface for internal web Businesses, but **Production must not be used as a substitute for proving a new art direction across an entire site.**

Two lanes now exist:

```text
A. FOCUSED_CHANGE_INSIDE_LOCKED_SYSTEM
B. NEW_ART_DIRECTION_OR_MATERIAL_REDESIGN
```

## 2. Lane A — focused change inside an established system

For a small UI-only change inside a design system whose current visual direction is already stable, the normal live loop remains:

```text
implementation
→ exact-head technical/visual validation
→ authorized merge
→ Git-connected Production deploy
→ owner reviews live result
→ retain / focused fix / restore
```

Examples:

- spacing correction;
- localized typography fix;
- one responsive defect;
- bounded component polish;
- visual bug with no art-direction change.

Standing UI-only merge authority may apply when the work contract and repository policy allow it.

## 3. Lane B — new art direction or material redesign

For a new product visual system, owner-rejected redesign, or broad multi-route visual reset, the sequence is:

```text
visual thesis + references
→ anchor Desktop/Mobile
→ ANCHOR_DIRECTION_LOCKED
→ 2–3 archetypes Desktop/Mobile
→ ARCHETYPE_SYSTEM_PASS
→ FULL_EXPANSION_ALLOWED
→ remaining-route implementation
→ full-surface Desktop/Mobile contact sheet
→ technical + visual review
→ authorized merge
→ Git-connected Production deploy
→ owner reviews live whole-product result
```

### Hard rule

Do not merge a broad, unproven multi-route art direction merely so the owner can discover on Production whether the first concept works.

The expensive part of the failure must happen before full propagation.

## 4. Anchor review is not whole-site approval

An owner may like an anchor screen while rejecting the rest of the product. Record that honestly.

```text
ANCHOR_DIRECTION_LOCKED
```

means the direction is suitable for system testing. It does not imply:

```text
ARCHETYPE_SYSTEM_PASS
FULL_SURFACE_VISUAL_PASS
OWNER_UI_APPROVED
```

## 5. Owner review mechanism

The owner may review an anchor/archetype through exact-head rendered evidence, an authorized limited surface, or current product tooling appropriate to the work order. A separate public Preview/staging deployment is not automatically required.

Do not create an unrelated Cloudflare Preview simply for convenience. If a Business-specific risk requires Preview/staging, record the explicit exception.

## 6. Final owner UI approval

Technical validation, design-system pass, merge and deployment do not equal owner approval.

Only after the owner actually reviews the applicable current result and explicitly accepts it may the product be recorded as:

```text
OWNER_UI_APPROVED
```

Otherwise use:

```text
OWNER_REVIEW_REQUIRED
OWNER_UI_REJECTED
REDESIGN_REQUIRED
```

## 7. Rejection handling

Diagnose before choosing the recovery level.

If the anchor itself is rejected:

- return to visual thesis/reference/anchor work;
- do not expand that direction.

If the anchor is liked but later surfaces fail:

- keep the anchor;
- classify archetype/system/typography/legacy/cascade failure;
- rebuild the weak system translation;
- do not invent a new concept by default.

If a focused Production change is rejected:

- prepare a bounded fix or reviewed restoration to last known good.

## 8. Standing merge authority exclusions

Standing UI-only live-review merge authority does **not** by itself cover:

- new art-direction resets before required design gates;
- broad visual refactors with unreviewed cross-state impact;
- backend/database changes;
- auth/authz changes;
- secrets/bindings/infrastructure;
- persistence/billing/destructive migration;
- external/successor Businesses;
- material security/trust-boundary changes.

## 9. Production evidence

After an authorized merge, verify:

- resulting exact main/release SHA;
- correct Cloudflare/project identity;
- deployment success/version;
- canonical Production URL;
- intended user-facing surface;
- primary browser journey when applicable;
- known-good recovery source.

Wrong-project Preview checks never count as intended Business deployment evidence.

## 10. B01 transition example

The 2026-08-14 B01 live review is the reason for this reset:

- the owner is satisfied with the current Entry direction;
- the remaining participant pages are not visually satisfactory;
- therefore Entry is treated as B01's local anchor, not whole-site approval;
- B01 must now prove Library, Write and Read as distinct archetypes before another broad participant-route expansion;
- the active V3/V4/V5/V6/V7 cascade should be consolidated during system recovery rather than extended with a new V8 concept.

## 11. Canonical markers

```text
FOCUSED_LIVE_REVIEW_ALLOWED
ART_DIRECTION_GATE_BEFORE_FULL_EXPANSION
ANCHOR_IS_NOT_WHOLE_SITE_APPROVAL
ARCHETYPE_PASS_BEFORE_BROAD_PROPAGATION
FINAL_OWNER_APPROVAL_AFTER_APPLICABLE_CURRENT_REVIEW
FIX_SYSTEM_TRANSLATION_BEFORE_INVENTING_NEW_CONCEPT
```
