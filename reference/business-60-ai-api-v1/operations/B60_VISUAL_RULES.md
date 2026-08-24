# B60 Visual Rules

Status: **CANONICAL VISUAL RULES**  
Effective: **2026-08-25**  
Tracks: #704  
Current implementation reference: PR #703 / `product-v13-editorial-radar.*`

These rules exist to stop future sessions from drifting back into generic AI/SaaS design.

## 1. Visual identity

Target character:

> **Editorial × Discovery × Urgency**

The page should feel closer to a technology/editorial publication that curates opportunities than to a provider console, coupon farm, or generic AI startup landing page.

## 2. Image-first, but not image-for-image's-sake

Prefer visuals that increase credibility or make the item easier to recognize:

1. official product/release imagery when reuse is appropriate;
2. actual product screenshots;
3. official announcement/social imagery when appropriate;
4. relevant real photography;
5. licensed/royalty-free raster photography with provenance;
6. generated imagery only when there is a concrete editorial reason and the owner requests/accepts it.

Store/record provenance for public-facing assets.

## 3. Explicit prohibitions

Do not use new decorative/simple SVG filler as the visual language of the editorial surface.

Avoid by default:

- generic robot-head icons
- AI brain/circuit SVGs
- meaningless glowing nodes/network graphics
- decorative isometric server art
- repeated stock-like abstract AI icons
- black/purple gradient + glass-card wall
- excessive neon borders/glows
- every card having the same rounded rectangle layout
- fake “AI future” decoration unrelated to the opportunity

Existing legacy assets can remain in dormant/secondary historical layers unless specifically removed; this rule controls the current editorial surface.

## 4. Benefit first

The strongest visual text should normally be the user benefit, for example:

```text
$5 크레딧 / 30일
이번 주 무료
무료 모델
10,000 neurons / day
1M context
```

Provider branding is secondary.

Do not let logos become the main content.

## 5. Editorial rhythm

Do not render all items as a uniform grid.

Use hierarchy:

- one large lead image/story when justified;
- secondary board/list items;
- mixed card proportions;
- quiet database-like always-free section;
- typography-only or compact rows where imagery adds no value;
- different densities for urgent vs evergreen information.

The information should feel edited, not dumped.

## 6. Color and shape

Current V13 uses warm paper/ink with limited accent colors. Future changes may evolve the palette, but preserve these principles:

- restrained palette;
- high legibility;
- strong editorial typography;
- square/crisp structures are acceptable;
- avoid automatic rounded-card SaaS styling;
- accents communicate hierarchy/status rather than decoration.

## 7. Korean copy

Prefer natural Korean labels over awkward English/Korean mixtures.

Canonical user-facing labels include:

- 지금 무료
- 상시 무료
- 종료 임박
- 최근 확인
- 확인 중
- 무료 크레딧
- 무료 모델
- 기간 한정 무료

English can remain for model/provider/product proper nouns and useful technical terminology.

## 8. Mobile rule

On mobile, imagery must not delay the benefit excessively.

The first meaningful item should ideally read as:

```text
image/recognition
→ benefit
→ title/condition
→ action/source
```

Do not use a full-screen decorative image that forces the user to scroll before learning what is free.

## 9. Truth/status in the visual layer

Design may create urgency only from verified data.

- verified expiry → countdown/ending treatment allowed
- unverified expiry → checking/pending treatment
- verified official source → confidence marker allowed
- uncertain claim → do not visually impersonate certainty

Visual drama must never outrun evidence.

## 10. Asset handling

For each editorial raster asset, preserve at least:

```text
local file path
alt text
source/owner
credit
source page
```

Prefer local optimized WebP/AVIF assets for stable rendering rather than fragile third-party hotlinks, when licensing/reuse permits local storage.

Do not commit font files merely to make screenshots render. System/web-safe typography or runtime test fonts are preferred.

## 11. Evaluation checklist

Before accepting a visual change, ask:

- Can I tell what I get for free in ~3 seconds?
- Does this look unlike a generic AI SaaS template?
- Are photos/screenshots doing real editorial work?
- Is the provider less prominent than the benefit?
- Are temporary and permanent benefits visibly different?
- Does mobile expose the benefit early enough?
- Is any urgency unsupported by evidence?
- Did we accidentally introduce decorative SVG filler?

If several answers are wrong, the change is not ready even if the code is technically correct.
