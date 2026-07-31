# UI Refinement V3 — Resident-First Consumer Marketplace Finish

## Status

This document fixes the visual finish for the current `index-v3.html` reference.

The interface should feel like a maintained Korean consumer marketplace, but the product purpose is resident mutual aid rather than generic nearby-commerce discovery.

`COMMUNITY_PRIORITY_MODEL.md` controls ranking and relationship semantics. `DESIGN_SPEC.md` controls information architecture. This file controls finish quality.

## 1. First-screen comprehension

Within the first mobile viewport, the user must understand:

- the current community is 방림명지로드힐;
- the service helps residents support resident-run work;
- current-apartment profiles come first;
- nearby-apartment profiles come second;
- general local businesses come third.

Required lead copy:

> 우리 이웃이 하는 일을 먼저 찾고, 함께 이용해요.

Do not lead with a generic apartment photograph, discount banner or nearby-shop claim.

## 2. Relationship hierarchy finish

### Tier 1

- label: `방림명지로드힐 주민 운영`;
- strongest trust treatment;
- green trust token;
- first business section;
- optional narrow card accent;
- must not look like a paid advertisement.

### Tier 2

- label: `이웃 단지 주민 운영`;
- blue trust token;
- second business section;
- clearly different from Tier 1.

### Tier 3

- label: `우리 동네 가게`;
- neutral gray token;
- third business section;
- no resident-operation implication.

Relationship labels are not interchangeable with discount labels.

## 3. Geometry

Use a fixed radius system:

- image: `10–12px`;
- search and large action: `10px`;
- standard desktop card: `12–14px`;
- small control: `8px`;
- status label: `6px`;
- circular shape only for icon-only controls and avatars.

Do not use pills for ordinary navigation, select fields or relationship labels.

Most list cards use no shadow. Use separators and photography before elevation.

```css
--shadow-rest: 0 1px 2px rgba(0,0,0,.04);
--shadow-float: 0 8px 24px rgba(0,0,0,.08);
```

## 4. Typography

Use Pretendard with Korean system sans-serif fallback.

| Role | Desktop | Mobile | Weight |
|---|---:|---:|---:|
| Location | 20 | 18 | 700–750 |
| Lead title | 30 | 25 | 700–750 |
| Page title | 30 | 26 | 700–750 |
| Section title | 22 | 20 | 700–750 |
| Card title | 17 | 16 | 650–700 |
| Body | 13–14 | 12–14 | 400–550 |
| Metadata | 10–12 | 10–12 | 400–600 |
| Relationship label | 9–10 | 8–10 | 650–700 |

Avoid ultra-bold paragraph text and excessive negative tracking.

## 5. Header and search

- product header: 68px desktop / 56px mobile;
- search is visually dominant but not a floating marketing card;
- desktop query field, category select and search button remain one coherent unit;
- mobile hides the category select and keeps one query field plus button;
- native semantic select retained with custom arrow;
- focus ring uses the brand token;
- no thick dark borders or multiple shadows.

The default search copy may mention a range of resident work:

`반찬, 에어컨 청소, 수학, 세무 검색`

## 6. Priority explanation

A compact priority explanation may appear beside or below the lead copy:

1. 우리 아파트 주민
2. 이웃 아파트 주민
3. 우리 동네 가게

It should look like product guidance, not a policy document. On mobile it stacks in a quiet white information block.

## 7. Category navigation

Eight categories remain:

- 음식·반찬
- 카페·디저트
- 집수리·청소
- 교육·과외
- 뷰티·건강
- 반려생활
- 전문서비스
- 취미·클래스

Use one coherent line-icon family. No emoji, generic AI icons or saturated category colors.

- desktop icon box: about 68px;
- mobile icon box: about 58px;
- four columns on mobile;
- restrained brand tint for selected state.

## 8. Business/service cards

Required information order:

1. photograph;
2. relationship label;
3. name and favorite;
4. category and action mode;
5. concrete one-line description;
6. price or consultation basis;
7. current availability;
8. resident benefit.

Mobile uses a vertical list with image-left/content-right rows. It must not become a grid of floating cards.

Tier color may appear as a narrow left edge on desktop, but the photograph and content remain primary.

No ratings, review counts or fake popularity numbers.

## 9. Grouped discovery

The explore page must preserve visible group headings:

- 우리 아파트 주민의 가게와 서비스;
- 이웃 아파트 주민의 가게와 서비스;
- 우리 동네 가게.

Filters may isolate a tier, but the default view is grouped in that order.

`가까운 순` may exist as a secondary option, never as the selected default.

## 10. Benefits

Benefits are separate from relationship verification.

Every benefit card should show:

- provider name;
- relationship label;
- exact benefit;
- eligibility;
- expiry or `상시` in production;
- current availability or action.

No `최대`, countdown or urgency language without exact conditions.

## 11. Detail page

Above the fold:

- gallery;
- relationship label;
- name;
- category and action mode;
- current availability;
- representative price;
- benefit;
- fixed mobile action bar.

Below the fold:

- representative services;
- introduction;
- relationship-verification disclosure;
- correction or report path in the future service.

Required Tier 1 disclosure:

> 방림명지로드힐 주민 운영 확인은 거주 동·호수를 공개하지 않으며 서비스 품질을 보증하지 않습니다.

## 12. Registration page

The first decision is relationship type:

1. 방림명지로드힐 주민이 직접 운영
2. 주변 아파트 주민이 운영
3. 일반 인근 가게이며 입주민 혜택 제공

Then select work form:

- offline shop;
- visiting service;
- freelance/professional service;
- online sales;
- tutoring/class;
- product or craft sale.

The screen must not imply that only storefront businesses can register.

## 13. Images

Temporary stock images are acceptable for the reference when:

- they depict the actual service category;
- no text is embedded;
- no obvious AI artifact;
- no identifiable residents;
- crop ratios remain consistent;
- sources are recorded in `IMAGE_SOURCES.md`.

Do not claim any generic apartment image is 방림명지로드힐.

Production images must be downloaded, reviewed, optimized and permission-cleared in a separate task.

## 14. Desktop and mobile density

### Desktop

- content width 1120–1180px;
- two-column cards inside each tier;
- detail content plus action sidebar;
- three-column benefits where space permits;
- descriptive line length under about 68ch.

### Mobile

- side padding 16px;
- lead and priority explanation stack;
- four category columns;
- shop list rows use separators;
- fixed bottom navigation;
- detail action bar does not cover content;
- no horizontal page overflow.

## 15. Rejected patterns

- generic local-directory copy;
- mixed equal list of every business;
- Tier 1 reduced to one small filter;
- distance-first sorting;
- paid general business above resident profile;
- oversized apartment hero;
- excessive rounded white cards;
- every label as a pill;
- heavy shadows, glossy gradients or glassmorphism;
- fake ratings and fake reviews;
- map-first experience;
- English-first headings;
- unfinished browser-default selects;
- private resident or chairperson information.

## 16. V3 acceptance gate

The reference cannot be handed to an implementation worker until:

- [ ] first-screen copy communicates residents helping residents;
- [ ] Tier 1 appears before Tier 2 and Tier 3;
- [ ] search results preserve the same group order;
- [ ] all three relationship labels are visually distinct;
- [ ] `가까운 순` is not default;
- [ ] registration starts with relationship type;
- [ ] storefront and non-storefront work are supported;
- [ ] typography and controls follow the fixed system;
- [ ] images load without broken states;
- [ ] no private resident information is exposed;
- [ ] screenshots at 390, 768 and 1440 are reviewed;
- [ ] no local worker has introduced design discretion.
