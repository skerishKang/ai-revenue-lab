# Competitive Reference and Visual Quality Policy

- Status: portfolio operating policy
- Owner: Web CTO under owner authority
- Applies to: demos, MVPs, visual upgrades, customer packages, and investor-facing product evidence
- Intent: `../portfolio/AI_REVENUE_LAB_OPERATING_INTENT.md`

## 1. Purpose

This policy prevents technically correct AI Revenue Lab products from looking generic, immature, overly cautious, or disconnected from the market.

The standard is not “good for an AI prototype.” The standard is a product that can be shown to customers, investors, partners, and technically sophisticated reviewers without embarrassment.

## 2. Benchmark requirement

Before major design work, identify:

- three to five direct or adjacent commercial products;
- two to four best-in-class visual or interaction references;
- one strong mobile reference when mobile matters;
- category conventions that customers already understand;
- one concrete dimension where the new product will exceed the references.

Reference research must include actual screen evidence, not only product names or abstract principles.

## 3. Reference board

Create `REFERENCE_BOARD.md` or an equivalent evidence artifact containing:

- URL, product, screen, and capture date;
- screenshot or precise screen description;
- layout and hierarchy notes;
- imagery and media notes;
- typography and density notes;
- interaction and motion notes;
- mobile behavior notes;
- adopted pattern;
- rejected pattern;
- corresponding state in the new product;
- improvement thesis.

A reference dossier that cannot point to the resulting screen is incomplete.

## 4. Pattern reconstruction

Rapid pattern-level reconstruction is permitted and encouraged for learning and prototyping.

Appropriate reconstruction includes:

- layout proportions;
- navigation behavior;
- interaction sequence;
- content rhythm;
- information density;
- filtering, comparison, and review behavior;
- conversion and onboarding structure;
- animation timing and spatial behavior.

The final product must establish an original identity. Do not publish copied trademarks, protected brand art, proprietary illustrations, or substantial verbatim copy without an authorized basis.

## 5. Image and media doctrine

### 5.1 Default hierarchy

Prefer:

1. owner or product-owned photography and video;
2. properly licensed commercial or open assets;
3. high-quality generated photography, illustration, 3D, video, and motion;
4. commissioned repository-local artwork;
5. diagrams, charts, icons, and simple SVGs as support.

Simple SVG diagrams are not a universal safe substitute for visual storytelling.

### 5.2 Image-led products

For media, travel, family, memory, fan, fashion, creator, education, culture, local-life, commerce, and entertainment Businesses:

- at least two major states should normally be image-led;
- a meaningful hero or primary visual should occupy substantial screen area;
- imagery must advance the product story or result;
- thumbnails must not be the only evidence of image use;
- generated assets should share a consistent art direction;
- the interface should show realistic content volume and variation.

### 5.3 Operational products

Verification engines, connector hubs, workflow tools, governance systems, and consoles may be system-led rather than photography-led.

They still require:

- mature information density;
- purposeful visualization;
- differentiated component grammar;
- realistic records and state transitions;
- precise motion and hierarchy;
- avoidance of generic card dashboards.

## 6. Typography and composition

Visual review must assess:

- typeface suitability and fallback behavior;
- headline scale and line length;
- body readability;
- label and metadata hierarchy;
- whitespace and density;
- focal point;
- grid and alignment;
- content rhythm;
- color and contrast;
- depth, texture, material, and shadow where appropriate;
- desktop and mobile composition as separate designs.

“No clipping” is not a typography verdict. “No overflow” is not a composition verdict.

## 7. Content realism

Use believable product content:

- realistic names, dates, amounts, locations, versions, and statuses;
- complete collections rather than three repeated placeholders;
- category-specific language;
- before/after results;
- human decisions and exceptions;
- evidence of use over time;
- meaningful empty and failure states when relevant.

Synthetic content may be rich and realistic. It should not read like developer fixtures.

## 8. Motion and interaction

Each product should identify one or more interactions that communicate its category advantage.

Evaluate:

- purpose;
- timing;
- continuity;
- spatial logic;
- responsiveness;
- reduced-motion equivalence;
- touch and keyboard behavior;
- replay stability when applicable;
- whether the motion makes the product more understandable or memorable.

Decorative motion without product meaning does not satisfy the requirement.

## 9. Market-quality score

Score each dimension from 1 to 5:

| Dimension | 1 | 3 | 5 |
|---|---|---|---|
| Product clarity | unclear | understandable | immediate and compelling |
| Visual identity | generic | coherent | distinctive and memorable |
| Reference fidelity | unrelated | some patterns visible | benchmark influence and improvement are obvious |
| Image/media quality | placeholder | adequate | premium and story-driving |
| Typography/composition | immature | serviceable | professional editorial/product quality |
| Content realism | fixture-like | believable | rich, specific, market-ready |
| Interaction/motion | absent/decorative | useful | category-defining |
| Mobile quality | compressed desktop | usable | intentionally designed |
| Investor/customer credibility | classroom prototype | credible demo | fundable/buyable impression |
| Original advantage | none | stated | visible and convincing |

Minimum verdicts:

```text
VISUAL_QUALITY_PASS: no dimension below 3; average >= 3.5
MARKET_REFERENCE_PASS: reference fidelity >= 4
INVESTOR_DEMO_PASS: credibility >= 4 and product clarity >= 4
```

Scores do not replace expert judgment. They expose weak areas and prevent technical checklists from masquerading as design approval.

## 10. Review evidence

Required for substantial reviews:

- desktop captures of all major states;
- approximately 390px mobile captures;
- motion video or deterministic evidence;
- benchmark screenshots or reference board;
- before/after captures for upgrades;
- image-source records;
- actual content inventory;
- scorecard and written verdict;
- exact head and deployment baseline when applicable.

## 11. Upgrade policy

A previously approved UI may be upgraded when it no longer meets the market standard.

Use a new issue, branch, and Draft PR. Preserve the deployed baseline until the new head is approved.

Upgrade work may change:

- art direction;
- imagery;
- typography;
- layout grammar;
- motion;
- content density;
- navigation and product storytelling;
- frontend behavior necessary to present the upgraded product.

Preserve valid backend and domain behavior unless the upgrade issue explicitly includes product-journey changes.

## 12. Prohibited shortcuts

Do not approve a product because:

- it has the required number of states;
- it uses repository-local SVG files;
- there are no console errors;
- the CSS is responsive;
- the worker listed several reference names;
- warnings and synthetic labels are plentiful;
- every section is contained in a rounded card;
- the implementation is technically complex.

These are implementation facts, not visual excellence.

## 13. Owner and reviewer standard

The owner decides acceptable creative, commercial, legal, and reputational risk.

Reviewers should identify concrete defects and opportunities. They should not reduce ambition through generic caution or repeatedly lecture the owner on basic risk categories.

The default recommendation should preserve or increase product value while handling the specific risk through practical means.