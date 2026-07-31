# LOCAL WORKER HANDOFF — DO NOT USE UNTIL REFERENCE APPROVAL

You are an implementation worker, not a product designer.

Your task is to reproduce an approved Business 5 reference exactly. You have no authority to reinterpret the product, reorder relationship tiers, change the visual direction or add features.

## Repository

- Repository: `skerishKang/ai-revenue-lab`
- Issue: `#89`
- Product: Business 5 · `우리단지 이웃가게`
- English name: `Neighbor Market`
- Stable slug: `neighbor-market`
- Future implementation scope: `apps/neighbor-market/**`

## Authoritative reference

The CTO will provide an approved commit SHA on:

`design/business-05-neighbor-market-v2-89`

Read and reproduce exactly:

- `reference/business-05-neighbor-market-v2/index-v3.html`
- `reference/business-05-neighbor-market-v2/COMMUNITY_PRIORITY_MODEL.md`
- `reference/business-05-neighbor-market-v2/DESIGN_SPEC.md`
- `reference/business-05-neighbor-market-v2/UI_REFINEMENT_V3.md`
- `reference/business-05-neighbor-market-v2/IMAGE_SOURCES.md`
- `reference/business-05-neighbor-market-v2/SCREENSHOT_MATRIX.md`

Do not begin until the CTO explicitly approves a reference commit.

## Non-negotiable product purpose

This is not primarily a nearby-shop directory.

The product exists to help residents discover and support the economic activity of people in their apartment community.

Fixed default order:

```text
1. 방림명지로드힐 주민 운영
2. 이웃 단지 주민 운영
3. 우리 동네 가게
```

This priority must control:

- home sections;
- default search results;
- category results;
- visual badge strength;
- copy hierarchy;
- registration classification.

Do not mix all profiles into one equal list. Do not use distance, discount size, sponsorship or payment to move Tier 2 or Tier 3 above Tier 1.

## Exact terminology

Use:

- `우리 아파트 주민의 가게와 서비스`
- `이웃 아파트 주민의 가게와 서비스`
- `우리 동네 가게`
- `방림명지로드힐 주민 운영`
- `이웃 단지 주민 운영`
- `우리 동네 가게`

Use `가게와 서비스` where `가게` alone would exclude freelancers, tutors, consultants, online sellers or visiting services.

## No-autonomy rule

Do not:

- rename the product;
- change the reference apartment;
- add the representative-chair name or any resident name;
- expose building or unit numbers;
- alter the three relationship tiers;
- change their order;
- merge the three tiers into a generic local-business badge;
- make `가까운 순` the default;
- alter category vocabulary;
- replace the layout with a dashboard;
- select another color system;
- copy Baemin, Yogiyo, Karrot or Apartment i branding;
- remove photographic imagery;
- add a full-screen map;
- invent ratings, review counts or transactions;
- add AI chat, recommendation explanations or robot imagery;
- add backend, authentication, database, messaging, payment, ordering or real submission;
- add remote analytics, tracking cookies or localStorage;
- modify files outside `apps/neighbor-market/**`;
- update the Business Registry in the implementation branch;
- create, ready, merge or close a PR unless separately instructed.

When a reference detail is technically impossible, stop and report the exact conflict. Do not substitute another design.

## Required repository shape

```text
apps/neighbor-market/
  README.md
  docs/
    PRODUCT_DECISION.md
    COMMUNITY_PRIORITY_MODEL.md
    DESIGN_SPEC.md
    IMAGE_SOURCES.md
    PRIVACY_BOUNDARY.md
  pages-preview/
    index.html
    assets/
      styles.css
      app.js
  tests/
    test_static_reference.py
```

You may split the approved single-file reference into CSS and JavaScript, but rendering, content hierarchy and interactions must remain equivalent.

## Required product facts

- `방림명지로드힐`
- `광주광역시 남구 대남대로85번길 3`
- `192세대`
- `2개 동`
- `2015-10-30 사용승인`

Do not add management-office phone numbers, resident names or unit details.

## Required routes and states

- home;
- grouped search/discovery;
- shop/service detail;
- resident benefits;
- owner registration;
- favorites/my page;
- QA state index;
- search empty state;
- Tier 1, Tier 2 and Tier 3 sections.

## Required interactions

- text search across synthetic fixtures;
- category filter;
- relationship filters: current apartment, nearby apartment, local business;
- availability and benefit filters;
- default grouped ranking current → neighbor → local;
- hash or path navigation;
- temporary favorite state;
- explicit inert toast for order, contact, login and submission actions;
- no action sends or persists data.

## Registration contract

The first form decision must be one of:

1. 방림명지로드힐 주민이 직접 운영
2. 주변 아파트 주민이 운영
3. 일반 인근 가게이며 입주민 혜택 제공

The form must support storefront and non-storefront work:

- physical shop;
- visiting service;
- freelance/professional service;
- online sales;
- tutoring/class;
- farm product or craft sale.

## Visual contract

Match the reference at:

- 1440×1100
- 768×1024
- 390×844

Required:

- Pretendard or approved self-hosted equivalent;
- exact token hierarchy;
- polished inputs and selects;
- community purpose, search and category flow near the top;
- Tier 1 as the first and strongest business section;
- visible Tier 2 and Tier 3 separation;
- two-column desktop and list-style mobile cards;
- photographic imagery;
- distinct relationship and benefit semantics;
- fixed mobile bottom navigation;
- detail mobile sticky actions;
- no horizontal overflow;
- no generic placeholder SVG business images.

## Image rule

For the first port, use the exact reference URLs and crops so screenshot comparison remains meaningful.

Do not scrape or download apartment-listing images.

After visual acceptance, a separate asset-hardening task may:

- download approved stock images;
- replace the generic apartment image with a user-supplied or cleared real photo;
- self-host the font;
- add license files.

Do not perform asset hardening unless separately instructed.

## Synthetic fixtures

Use the exact fixture set and relation values from `index-v3.html`:

### Tier 1 — 방림명지로드힐 주민 운영

- 오늘의 반찬상
- 맑은집 홈케어
- 차분한 수학
- 단정 세무회계

### Tier 2 — 이웃 단지 주민 운영

- 골목 베이크룸
- 온결 헤어룸
- 포근펫 케어

### Tier 3 — 우리 동네 가게

- 작은정원 플라워
- 동네 사진관

Do not present these as real businesses or real resident relationships.

## Tests

Add deterministic tests proving:

- required files and routes exist;
- exact product/apartment strings exist;
- all three relationship tier labels exist;
- home order is Tier 1 → Tier 2 → Tier 3;
- search grouping uses the same order;
- Tier 1 is not merely a filter inside a mixed equal list;
- `가까운 순` is not the default;
- exact category and fixture sets exist;
- representative-chair/resident names and unit details are absent;
- navigation targets resolve;
- search/filter code uses only checked-in synthetic fixtures;
- no `fetch`, XMLHttpRequest, WebSocket, EventSource or form submission;
- no localStorage, sessionStorage or cookies;
- every preview action has an inert disclosure path;
- no copied commercial logos or brand names appear in rendered UI;
- responsive boundaries and mobile navigation exist;
- no files outside `apps/neighbor-market/**` changed.

## Git rules

- Start from the exact base SHA provided by the CTO.
- Use a dedicated clean worktree.
- Do not touch any dirty existing checkout.
- No rebase, amend or force push.
- Keep the implementation PR Draft.
- Do not close Issue #89.
- Do not merge.

## Completion report

Report:

- exact base, branch and head SHA;
- file list and diff stats;
- zero out-of-scope changes;
- tests with commands, counts and exit codes;
- zero-network and inert-action evidence;
- desktop/tablet/mobile screenshots;
- current → neighbor → local order evidence;
- every deviation from the approved reference;
- clean worktree status.

Stop after the report.
