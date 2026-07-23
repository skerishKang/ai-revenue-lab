# Business 5 v3 Design Specification

## 1. Product sentence

> 방림명지로드힐 주민이 하는 가게와 서비스를 가장 먼저 발견하고, 이웃 단지 주민과 일반 동네 가게를 차례로 연결해 서로의 생활경제를 돕는 모바일 커뮤니티 마켓.

A reviewer must understand the following in the first viewport:

1. this is for 방림명지로드힐;
2. current-apartment resident businesses come first;
3. nearby-apartment resident businesses come second;
4. general neighborhood businesses come third.

The product is not accepted when it looks like a generic nearby-shop directory.

## 2. Authoritative priority model

`COMMUNITY_PRIORITY_MODEL.md` is authoritative for relationship tiers, ranking, verification and monetization guardrails.

Fixed order:

```text
우리 단지 주민 운영
→ 이웃 단지 주민 운영
→ 우리 동네 가게
```

This order controls:

- home sections;
- default search ranking;
- category results;
- badge strength;
- copy hierarchy;
- registration classification;
- sponsored-placement limits.

Distance, discount size or payment may not override the relationship tier.

## 3. Reference strategy

The product does not clone Baemin, Yogiyo or Karrot branding. It borrows established Korean marketplace interaction patterns while applying a different community objective.

### Marketplace patterns retained

- apartment context before discovery;
- dominant search;
- direct category entry;
- photographic cards;
- representative service and price;
- current availability;
- dense mobile hierarchy;
- sticky detail actions;
- category, favorites and profile routes.

### Community-specific patterns added

- three explicit resident-relationship tiers;
- Tier 1 as the largest home section;
- separate color and language for each tier;
- `가게와 서비스` terminology for residents without storefronts;
- resident-first default search order;
- disclosure that resident verification is not a quality guarantee;
- no paid cross-tier ranking.

### Explicitly rejected

- copied logos, proprietary colors or mascots;
- mixed equal treatment of all local shops;
- distance-first default sorting;
- paid placement above resident businesses;
- fake ratings or review counts;
- full-screen map as the primary UI;
- generic SaaS dashboard;
- AI chatbot or robot styling;
- oversized manifesto sections;
- every section inside a floating rounded box;
- excessive pills, shadows, gradients or ultra-bold text.

## 4. Reference apartment and privacy

### Public prototype context

- Apartment: 방림명지로드힐
- Address: 광주광역시 남구 대남대로85번길 3
- Households: 192
- Buildings: 2
- Use approval: 2015-10-30

### Public UI exclusions

Do not display:

- representative-chair or resident names;
- building or unit numbers;
- resident roster status;
- identity documents;
- private phone numbers;
- management-office internal records;
- private meeting or dispute information.

The current representative-chair identity may later exist as a product-local operator account, but it is not public marketplace content.

## 5. Core information architecture

### Global shell

A compact AI Revenue Lab strip remains separate from the product.

### Product header

- product mark and name;
- 홈;
- 가게와 서비스;
- 주민 혜택;
- 가게 등록;
- favorites/profile placeholders.

### Mobile bottom tabs

- 홈
- 찾기
- 혜택
- 찜
- 마이

### Required routes and states

- `#home`
- `#explore`
- `#detail`
- `#benefits`
- `#register`
- `#my`
- `#qa`
- search empty state
- Tier 1 section
- Tier 2 section
- Tier 3 section

## 6. Home composition

The order is fixed:

1. current apartment selector;
2. one-line community purpose;
3. search;
4. practical categories;
5. **우리 아파트 주민의 가게와 서비스**;
6. **이웃 아파트 주민의 가게와 서비스**;
7. **우리 동네 가게**;
8. resident-benefit strip;
9. owner registration invitation.

The apartment photograph is contextual support, not the primary product message. The first screen should foreground people helping people, not real-estate information.

Required lead copy:

> 우리 이웃이 하는 일을 먼저 찾고, 함께 이용해요.

Supporting copy may mention:

- 방림명지로드힐 주민 운영 profiles are shown first;
- exact residence details are not disclosed;
- nearby apartments and general local businesses follow in separate groups.

## 7. Relationship-tier presentation

### Tier 1 — current apartment

Label:

- `방림명지로드힐 주민 운영`
- optional secondary: `우리 단지 이웃`

Visual treatment:

- strongest coral/green trust treatment;
- section header includes the apartment name;
- first placement;
- card may include a narrow left accent or strong top badge;
- no star rating.

### Tier 2 — nearby apartment

Label:

- `이웃 단지 주민 운영`
- optional secondary: `방림동 이웃 사업`

Visual treatment:

- blue/teal secondary trust treatment;
- second placement;
- apartment name shown only when permitted;
- clearly distinguishable from Tier 1.

### Tier 3 — general neighborhood

Label:

- `우리 동네 가게`
- optional: `입주민 혜택 제공`

Visual treatment:

- neutral gray base;
- third placement;
- benefit may be highlighted, but not as resident verification.

## 8. Search and filtering

Default result order is community priority.

Required filters:

- 전체
- 우리 단지 주민
- 이웃 단지 주민
- 동네 가게
- 지금 가능
- 혜택 있음

Optional secondary sort:

- 추천순
- 정보 최신순
- 가까운 순

`가까운 순` must not be the initial selection.

Search matching occurs before tier ordering; matched profiles are then grouped or sorted by relationship tier.

## 9. Category vocabulary

- 음식·반찬
- 카페·디저트
- 집수리·청소
- 교육·과외
- 뷰티·건강
- 반려생활
- 전문서비스
- 취미·클래스

These categories cover both storefront businesses and individual services.

## 10. Shop-card contract

Every card must expose:

- photographic image;
- name;
- relationship-tier label;
- category;
- concrete one-line description;
- representative item/service and price or consultation basis;
- current availability;
- resident benefit when applicable;
- business-specific action mode;
- favorite control.

Valid actions include:

- 주문
- 예약
- 포장
- 픽업
- 견적 문의
- 상담
- 촬영 예약
- 수업 예약

Do not force every business into food delivery.

## 11. Detail-page contract

The detail page must answer, in order:

1. who operates this profile in community terms;
2. what service is offered;
3. how and when it can be used;
4. representative price or consultation basis;
5. resident benefit;
6. verification meaning and limitations;
7. contact/order/reservation action.

Required disclosure for a Tier 1 profile:

> 방림명지로드힐 주민 운영 확인은 거주 동·호수를 공개하지 않으며 서비스 품질을 보증하지 않습니다.

## 12. Registration contract

The first registration decision is relationship type, not business category.

Required choices:

1. 방림명지로드힐 주민이 직접 운영
2. 주변 아파트 주민이 운영
3. 일반 인근 가게이며 입주민 혜택 제공

The form must also accept non-storefront work:

- freelance service;
- online shop;
- visiting service;
- class or tutoring;
- professional consultation;
- farm product or craft sale.

Private verification material is submitted separately from public profile content in the future service.

## 13. Visual system

### Typography

Reference font: Pretendard.

- page title: 26–30px;
- section title: 20–22px;
- card title: 16–17px;
- body: 12–14px;
- metadata: 10–12px;
- body weights generally 400–650;
- avoid excessive 800+ weights and aggressive negative tracking.

### Color

| Token | Value | Role |
|---|---:|---|
| Brand coral | `#FF5B3D` | primary actions |
| Ink | `#191C1B` | primary text |
| Muted | `#6A706D` | metadata |
| Canvas | `#F7F8F6` | desktop background |
| Surface | `#FFFFFF` | content |
| Line | `#E8E9E7` | separation |
| Tier 1 green | `#176347` | current-apartment trust |
| Tier 1 soft | `#E9F4EF` | current-apartment badge |
| Tier 2 blue | `#315F91` | nearby-apartment trust |
| Tier 2 soft | `#EDF4FF` | nearby-apartment badge |
| Tier 3 gray | `#626966` | general local label |
| Benefit yellow | `#FFF4C7` | benefit explanation |

### Geometry

- controls: 8–10px radius;
- desktop content cards: 12–14px radius;
- mobile list cards: no outer radius, separators only;
- category tiles: 12–14px radius;
- pills only for compact filters and trust labels;
- shadows near zero except elevated search or hover.

## 14. Responsive behavior

### Desktop

- max width 1160px;
- two-column cards inside each tier;
- relationship sections remain visibly separated;
- detail uses main content and side action panel.

### Tablet

- four category columns;
- detail becomes one column;
- tier sections retain headings and explanatory copy.

### Mobile 390×844

- 56px product header;
- search near top;
- four category columns;
- Tier 1 appears before any general promotion;
- shop cards use image-left list rows;
- horizontal benefit strip allowed;
- fixed bottom tabs;
- detail route uses fixed action bar;
- no horizontal page overflow.

## 15. Photo policy

Temporary Unsplash images may be used only for reference layout review.

- apartment image must say it is not the actual complex photograph;
- temporary images are not evidence of real participating businesses;
- production assets must be downloaded, reviewed and permission-cleared;
- a real 방림명지로드힐 photograph should be user-supplied or separately cleared;
- do not scrape Apartment i, Naver, KB, Hogangnono or listing images;
- do not show identifiable resident faces without permission.

## 16. Content honesty

All current businesses, apartment relationships, prices, benefits and availability states are synthetic examples.

Do not imply:

- actual participation;
- actual resident verification;
- official management-office endorsement;
- actual prices or discounts;
- real-time opening status;
- quality guarantees;
- real order or contact availability.

## 17. Acceptance gate

The design fails when:

- Tier 1 is only a small badge inside a mixed list;
- all local businesses appear equal;
- the first section is a general discount banner;
- distance is the default ranking principle;
- a paid general business can outrank a resident profile;
- `가게` wording excludes services or freelancers;
- private residence details are exposed.

The future implementation must provide screenshots at 1440×1100, 768×1024 and 390×844, with no overflow, missing images, console errors or source changes during capture.
