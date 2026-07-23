# UI Refinement V3 — Consumer Marketplace Finish

## Status

This document tightens the visual finish of the Business 5 reference before any local implementation begins.

The product structure in `index.html` remains valid. The next design pass must make the interface feel like a maintained Korean consumer marketplace rather than a generated landing page.

## Reference principles

Use familiar interaction patterns from leading Korean consumer apps without copying logos, proprietary illustrations, wording, or exact layouts.

- delivery-app clarity: location, search, category, availability, price and primary action;
- local-business trust: owner profile, news, benefit, contact and correction path;
- apartment context: one verified residential community, resident-only benefit and privacy-safe verification.

## Mandatory visual changes

### 1. Reduce generated-looking geometry

Current cards use too many unrelated radii and floating shadows.

Use this fixed radius system:

- image: `12px`;
- search field and large action: `12px`;
- standard card: `14px`;
- small control: `8px`;
- status chip: `6px`;
- circular controls only for icon-only buttons and avatars.

Do not use pill geometry for ordinary navigation, buttons, select fields or trust labels.

Use only two shadow levels:

```css
--shadow-rest: 0 1px 2px rgba(0,0,0,.04);
--shadow-float: 0 8px 24px rgba(0,0,0,.08);
```

Most list cards should have no shadow. Prefer dividers and image hierarchy.

### 2. Typography

Use Pretendard when available and system Korean sans-serif as fallback.

```css
font-family: Pretendard, -apple-system, BlinkMacSystemFont,
  "Apple SD Gothic Neo", "Noto Sans KR", "Malgun Gothic", sans-serif;
```

Required scale:

| Role | Desktop | Mobile | Weight | Letter spacing |
|---|---:|---:|---:|---:|
| Apartment location | 20 | 18 | 750 | -0.025em |
| Page title | 32 | 26 | 750 | -0.035em |
| Section title | 22 | 20 | 750 | -0.025em |
| Shop title | 17 | 16 | 700 | -0.015em |
| Body | 14 | 14 | 400–500 | -0.005em |
| Metadata | 12 | 12 | 400–600 | 0 |
| Badge | 11 | 11 | 650 | 0 |

Avoid weights above 800 except the compact brand mark. Avoid excessive negative tracking.

### 3. Header and search

Mobile header order:

1. apartment selector;
2. notification and account icons;
3. sticky search field below the header after the user scrolls past the hero.

The search field must look like a real input, not a large decorative card:

- height `48px` mobile / `52px` desktop;
- neutral `#f4f5f4` fill;
- one subtle focus ring;
- icon left, clear button right when text exists;
- no drop shadow;
- category selector separated from the query input on desktop only.

Custom select finish:

- native semantic `<select>` retained;
- `appearance:none`;
- one down-chevron;
- no double border;
- focus ring identical to search;
- text vertically centered;
- minimum width sufficient for Korean labels.

### 4. Category navigation

Eight categories remain.

Do not use generic emoji or colored AI icons. Use one coherent line-icon family, identical stroke width and optical size.

- icon container `56×56px` mobile, `68×68px` desktop;
- light neutral background;
- selected category uses a restrained brand tint, not a saturated tile;
- category names remain one line;
- exactly four columns on mobile.

### 5. Benefit presentation

Benefits must not resemble generic SaaS gradient banners.

Use real service imagery with a readable solid or translucent label area.

Every benefit card exposes:

- provider name;
- exact benefit;
- eligibility;
- expiry or `상시`;
- one action.

No ambiguous `최대`, `특가`, countdown or urgency language.

### 6. Shop list cards

Mobile is a vertically separated list, not a grid of floating cards.

Required order:

1. real photo;
2. shop name and favorite;
3. category and verification state;
4. representative product/service;
5. price or consultation mode;
6. current availability;
7. resident benefit.

Desktop may use two columns, but each item retains the same information order.

Required states:

- `영업 중`;
- `오늘 예약 가능`;
- `오늘 상담 가능`;
- `주문 마감`;
- `정보 확인 필요`.

Green is reserved for actual availability. Coral is reserved for resident benefits and primary commerce actions. Verification badges use neutral or dark-green text on a low-contrast background.

### 7. Detail page

The detail page prioritizes a decision, not an essay.

Above the fold:

- photo gallery;
- shop name;
- verification state;
- current availability;
- service mode;
- benefit;
- fixed mobile action bar.

Below the fold:

- representative products/services with prices;
- use instructions;
- business introduction;
- recent news;
- correction/report path.

The mobile action bar adapts by business type:

- food: `전화`, `문의`, `주문하기`;
- repair: `전화`, `문의`, `견적받기`;
- class: `전화`, `상담`, `예약하기`;
- professional: `전화`, `상담`, `상담신청`.

Static reference actions must show that no message, order or data was sent.

### 8. Image rules

Temporary MVP stock photographs are acceptable, but images must look like business content rather than decorative stock art.

- no text embedded in images;
- no obvious AI artifacts;
- no smiling corporate stock teams;
- no identifiable apartment residents;
- no apartment photo claimed as 방림명지로드힐 unless user-supplied or permission-cleared;
- each image uses a documented source;
- consistent crop ratios by component;
- lazy loading below the first viewport;
- fixed aspect ratio prevents layout shift.

Before production implementation, temporary remote images must be downloaded, optimized and checked into the product workspace with an attribution ledger where required.

### 9. Apartment identity

Public display name: `방림명지로드힐`.

Public context may show:

- 광주광역시 남구;
- 192세대;
- 2개 동;
- apartment-level benefit coverage.

Do not display:

- chairperson name in the resident-facing MVP;
- building/unit numbers;
- resident roster information;
- private management-office contact details;
- a claim that the management office officially endorses the service unless formally approved.

### 10. Desktop and mobile density

The product is mobile-first, but desktop must not become an oversized mobile mockup.

Desktop:

- content width `1120–1180px`;
- two-column shop results;
- three-column benefit cards;
- detail content plus action sidebar;
- maximum line length for descriptive text `68ch`.

Mobile:

- side padding `16px`;
- bottom navigation height `64–72px` including safe area;
- no horizontal page overflow;
- list separators aligned with text, not full-bleed through photographs;
- sticky action bars do not cover content.

## Rejected patterns

- oversized hero marketing copy;
- dozens of rounded white cards on gray canvas;
- every label rendered as a pill;
- heavy drop shadows;
- glossy gradients;
- glassmorphism;
- fake ratings or fake review counts;
- generic AI illustration;
- map-first experience;
- dashboard side navigation;
- English-first headings;
- unexplained icons;
- default browser select appearance;
- inconsistent icon stroke and size.

## V3 acceptance gate

The reference cannot be handed to the local implementation worker until all are true:

- [ ] typography follows the fixed scale;
- [ ] ordinary controls use the fixed radius system;
- [ ] search and select controls have production-grade focus and spacing;
- [ ] cards use real imagery and consistent crops;
- [ ] mobile shop list reads in one scan without decorative clutter;
- [ ] all business types have an appropriate action label;
- [ ] apartment reference image is clearly generic or user-supplied;
- [ ] no private resident or chairperson information is exposed;
- [ ] screenshots at 390, 768 and 1440 have been reviewed;
- [ ] no local worker has introduced visual discretion.
