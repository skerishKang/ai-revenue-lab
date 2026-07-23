# Business 5 v2 Design Specification

## 1. Product sentence

> 방림명지로드힐 주민이 단지 안팎의 이웃가게와 생활 서비스를 사진, 가격, 이용 가능 상태, 주민 혜택을 기준으로 빠르게 찾는 모바일 생활 마켓.

A reviewer should understand this within the first viewport without reading an explanatory essay.

## 2. Reference strategy

The product does not clone Baemin, Yogiyo or Karrot branding. It transfers established Korean marketplace interaction patterns:

### From delivery marketplaces

- location/apartment context before discovery;
- search as the dominant first action;
- category icons immediately below search;
- photographic cards with representative item/service and price;
- current availability before detail navigation;
- dense mobile information hierarchy;
- sticky action area on detail screens.

### From local-business profiles

- resident/local trust labels;
- shop news and time-sensitive updates;
- coupons/benefits separated from base information;
- favorites and repeat relationship;
- phone/chat/order/reservation actions based on business type.

### Explicitly rejected

- copied logos, colors, character mascots or proprietary illustrations;
- a full-screen map as the primary UI;
- fake ratings and fake review counts;
- red discount walls or high-pressure countdowns;
- generic SaaS dashboards;
- AI chatbot or robot imagery;
- large editorial manifesto sections;
- every section placed in an oversized rounded rectangle;
- gradient-heavy AI demo styling.

## 3. Reference apartment

### Public prototype context

- Apartment: 방림명지로드힐
- Address: 광주광역시 남구 대남대로85번길 3
- Households: 192
- Buildings: 2
- Use approval: 2015-10-30

### Privacy rule

Do not display:

- representative-chair or resident names;
- building/unit numbers;
- resident roster status;
- personal phone numbers;
- verification documents;
- management-office internal records;
- private meeting or dispute information.

The chair identity may exist later as a product-local operator account but is not public profile content.

## 4. Core information architecture

### Global shell

A compact AI Revenue Lab strip remains visually separate from the product.

### Product header

- product mark and name;
- Home;
- Category;
- Resident benefits;
- Owner registration;
- search, login placeholder and owner CTA.

### Mobile bottom tabs

- 홈
- 카테고리
- 혜택
- 찜
- 마이

### Required product routes/states

- `#home`
- `#explore`
- `#detail`
- `#benefits`
- `#register`
- `#my`
- `#qa`
- search empty state

## 5. Home composition

Order is fixed:

1. apartment selector;
2. apartment/context visual;
3. dominant search;
4. 8 practical categories;
5. resident-benefit banners;
6. available-now shops;
7. new shops.

The large apartment visual anchors place identity but must not consume most of the mobile viewport. Search and categories must remain visible quickly.

## 6. Category vocabulary

- 음식·반찬
- 카페·디저트
- 집수리·청소
- 교육·과외
- 뷰티·건강
- 반려생활
- 전문서비스
- 취미·클래스

Categories represent resident intent rather than formal business registration codes.

## 7. Shop-card contract

Every card must expose enough information to decide whether to open it:

- photographic image;
- shop/service name;
- resident-operated or verified-information label;
- current availability;
- category;
- action mode;
- concrete one-line description;
- representative item/service and price or consultation basis;
- resident benefit;
- optional small operational tags;
- favorite control.

### Valid action modes

- 주문
- 예약
- 포장
- 픽업
- 견적 문의
- 상담
- 촬영 예약
- 수업 예약

Do not force all businesses into a delivery/order metaphor.

## 8. Trust semantics

These are independent states and must not be merged into one vague badge.

### 입주민 운영 확인

The configured resident-operation verification process was accepted at a point in time. It does not reveal the resident's unit and is not a service-quality guarantee.

### 정보 검토 완료

Basic public business information passed an operator review. It does not mean legal certification.

### 단지 혜택

A benefit specifically claims eligibility for the reference apartment. Eligibility, expiry and exclusions must be visible in production.

## 9. Visual system

### Typography

Reference font: Pretendard.

- Display headings: 700–850 weight, tight Korean letter spacing.
- Product title: 17px desktop / 15px mobile.
- Card title: 17px desktop / 16px mobile.
- Body: 12–15px.
- Metadata: 10–12px.
- Avoid ultra-bold body text and excessive uppercase labels.

### Color

| Token | Value | Role |
|---|---:|---|
| Brand | `#FF6547` | primary actions and selected state |
| Brand strong | `#EF5134` | hover and important benefit text |
| Ink | `#171A19` | primary text |
| Muted | `#686E6B` | metadata |
| Canvas | `#F7F7F5` | desktop background |
| Surface | `#FFFFFF` | content surface |
| Line | `#E7E8E6` | quiet separation |
| Trust green | `#23634F` | verification and open state |
| Trust green soft | `#E7F3EE` | trust badge background |
| Benefit yellow | `#FFEF B8` | benefit explanation |

Note: remove the space in the implementation value: `#FFEFB8`.

### Geometry

- input/button radius: 11–12px;
- content-card radius: 17–20px desktop;
- mobile list cards: no outer radius; use separators;
- category tile radius: 17–20px;
- pills only for filters, compact states and trust labels;
- ordinary cards use near-zero shadow; shadow appears on hover or elevated search.

### Select/input finish

- browser default arrow removed;
- explicit inline chevron;
- 48–52px control height;
- quiet gray field background for search;
- visible brand focus ring;
- no thick dark border;
- placeholder contrast sufficient but subordinate.

## 10. Responsive behavior

### Desktop

- maximum content width: 1160px;
- two-column shop cards;
- apartment hero height around 252px;
- shop detail: main content plus 360px side action panel;
- three-column benefits.

### Tablet

- four category columns;
- detail becomes one column;
- side content may become two columns;
- benefits become two columns.

### Mobile 390×844 reference

- global strip: 28px;
- product header: 56px;
- apartment hero uses full viewport width and about 174px height;
- search is one large field plus search button;
- four category columns;
- benefits use horizontal snap scrolling;
- shop cards become photograph-left/content-right list rows;
- mobile bottom tabs fixed;
- detail route replaces tabs with favorite/phone/order action bar;
- no horizontal page overflow.

## 11. Photo policy

The reference uses temporary Unsplash images to judge layout, density, cropping and color balance.

- apartment hero is clearly marked as a reference image;
- no temporary image is proof of a real business;
- production requires downloaded, reviewed and permission-cleared assets;
- a real 방림명지로드힐 exterior image should be user-supplied or cleared before publication;
- do not scrape Apartment i, KB, Naver, Hogangnono or listing photos into production assets;
- no identifiable resident faces.

## 12. Content honesty

All current businesses are synthetic examples. The UI must retain a visible preview disclosure.

Do not imply:

- actual shop participation;
- actual prices or discounts;
- official management-office endorsement;
- current opening hours;
- quality guarantees;
- real order or contact availability.

## 13. Local implementation quality gate

The future repository implementation is not accepted merely because the HTML exists.

It must show:

- exact screenshot comparison at 1440×1100, 768×1024 and 390×844;
- no layout overflow;
- no missing remote/image fallback during reference port;
- exact product naming and apartment context;
- exact category and shop fixture set;
- no redesign by the implementation model;
- explicit inert actions;
- all navigation and search states functioning without backend persistence.
