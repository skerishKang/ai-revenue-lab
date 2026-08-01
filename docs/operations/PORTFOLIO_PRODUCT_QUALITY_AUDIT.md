# Portfolio Product Quality Audit and Upgrade Program

- Status: portfolio operating program
- Owner: Web CTO under owner authority
- Applies to: every canonical, proposed, deployed, or revived AI Revenue Lab Business
- Intent: `../portfolio/AI_REVENUE_LAB_OPERATING_INTENT.md`
- Visual standard: `COMPETITIVE_REFERENCE_AND_VISUAL_QUALITY_POLICY.md`
- Backend standard: `BACKEND_MVP_OPERATING_POLICY.md`

## 1. Purpose

AI Revenue Lab will re-audit the entire Business portfolio before the next major upgrade wave.

The audit exists because technical completion, deployment, and checklist compliance do not prove that a product is visually mature, commercially convincing, or suitable for an investor demonstration.

The program should preserve strong domain logic and backend work while replacing weak product presentation, generic UI, shallow references, and incomplete demo journeys.

## 2. Audit unit

Audit one Business at a time using the authoritative deployed version or latest accepted head.

Record:

- Business number and product name;
- current canonical or proposed status;
- authoritative repository path, PR, and exact head;
- current deployment URL when applicable;
- current demo, MVP, backend, and commercial stage;
- target customer and product promise;
- direct competitors and benchmark products;
- existing visual and functional strengths;
- defects and missed opportunities;
- upgrade classification;
- next highest-value action.

## 3. Classification

### A — externally credible

The product can be shown to customers or investors with targeted refinements only.

Requirements:

- clear and differentiated product story;
- mature visual system;
- credible content and interactions;
- intentional desktop and mobile design;
- main value proposition demonstrated;
- no material embarrassment beside selected benchmarks.

### B — strong structure, major visual upgrade required

The product thesis, functionality, or backend is sound, but the UI looks generic, immature, sparse, overly cautious, or disconnected from market references.

Default action:

```text
Visual Upgrade v2
```

Preserve backend and domain logic unless a visual change requires a bounded frontend contract adjustment.

### C — product journey and visual system require redesign

The idea is viable, but information architecture, product storytelling, state structure, content, and visual language do not form a convincing product.

Default action:

```text
Product Upgrade v2
```

Reuse proven functions and data contracts selectively.

### D — thesis or market position requires reconsideration

The Business is duplicative, unclear, commercially weak, or no longer aligned with the portfolio.

Default action:

```text
REFRAME / COMBINE / PAUSE / STOP
```

Do not spend design effort before resolving the product decision.

## 4. Audit scorecard

Score from 1 to 5:

| Area | Question |
|---|---|
| Product clarity | Is the user, problem, and result obvious? |
| Commercial relevance | Is there a credible customer, use moment, and offer? |
| Competitive position | Does it understand and improve on current alternatives? |
| Visual identity | Is it distinctive, mature, and category-appropriate? |
| Image/media quality | Does the product use strong visual assets where relevant? |
| Typography/composition | Does it look professionally designed? |
| Content realism | Does it feel populated, specific, and usable? |
| Main journey | Can the core value be demonstrated end to end? |
| Interaction/motion | Are interactions meaningful and memorable? |
| Mobile quality | Is mobile intentionally designed? |
| Backend credibility | Does live or simulated behavior support the product story? |
| Investor-demo quality | Can it be presented externally without apology? |

Suggested interpretation:

```text
4.2–5.0: A candidate
3.2–4.1: B candidate
2.2–3.1: C candidate
below 2.2: D candidate
```

Final classification remains an expert judgment.

## 5. Evidence package

Each audit should include:

- current desktop and mobile captures;
- key journey video where applicable;
- reference and competitor captures;
- scorecard;
- strengths worth preserving;
- exact defects with screen locations;
- proposed upgrade direction;
- rough effort and dependency level;
- business priority recommendation.

## 6. Upgrade priority

Prioritize Businesses that combine:

- strong backend or functional work;
- weak or embarrassing visual presentation;
- near-term investor or customer relevance;
- existing deployment that enables before/after proof;
- strong image, content, or interaction potential;
- plausible pilot or revenue path.

Do not prioritize only by Business number or age.

## 7. Upgrade issue contracts

### Visual Upgrade v2

Use when the product structure is sound.

May include:

- new reference board and art direction;
- photography, generated media, illustration, 3D, and motion;
- typography and grid overhaul;
- component and layout redesign;
- richer synthetic content;
- responsive redesign;
- product storytelling improvements;
- bounded interaction changes needed for presentation.

### Product Upgrade v2

Use when the journey also needs work.

May include:

- revised information architecture;
- new primary journey;
- different screen/state system;
- simulated or live vertical slice;
- data-contract reuse or adaptation;
- product-positioning revision;
- visual overhaul.

## 8. Existing Production rule

Do not overwrite an accepted Production baseline before the upgrade passes review.

Use:

```text
current deployed baseline
→ new issue and branch
→ benchmark and upgrade
→ independent technical and visual review
→ owner approval
→ authorized deployment
→ before/after Production verification
```

A rejected upgrade leaves the existing version unchanged.

## 9. Portfolio waves

Use controlled waves rather than attempting fifty simultaneous redesigns.

### Wave 0 — policy and inventory

- approve the new operating policies;
- inventory canonical and proposed Businesses;
- identify authoritative heads and deployments;
- capture current visual evidence.

### Wave 1 — high-value visible upgrades

Select Businesses with strong functions and immediate investor/customer value.

### Wave 2 — image-led categories

Travel, family, memory, media, fan, creator, fashion, commerce, local life, and entertainment.

### Wave 3 — operational and enterprise products

Verification, connectors, workflow, governance, data, and portfolio systems.

### Wave 4 — product consolidation

Reframe, combine, pause, or stop overlapping and weak Businesses.

## 10. Review verdicts

Use:

```text
PORTFOLIO_AUDIT_COMPLETE
VISUAL_CLASS_A
VISUAL_CLASS_B
PRODUCT_CLASS_C
PRODUCT_CLASS_D
VISUAL_UPGRADE_V2_REQUIRED
PRODUCT_UPGRADE_V2_REQUIRED
EXTERNALLY_CREDIBLE
INVESTOR_DEMO_READY
```

Avoid declaring a Business “done” solely because it is deployed or technically stable.

## 11. Operating expectation

The audit should produce visible before/after improvement, not only more reports.

For each upgrade wave, the Portfolio Console or evidence index should make it possible to compare:

- previous screen;
- benchmark screen;
- upgraded screen;
- main journey;
- technical status;
- customer or investor response;
- next commercial step.

## 12. Default instruction

```text
Preserve what is technically strong.
Replace what is visually weak.
Reframe what does not deserve further investment.
```