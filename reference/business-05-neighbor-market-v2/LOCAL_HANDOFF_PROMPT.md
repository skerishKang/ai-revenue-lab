# LOCAL WORKER HANDOFF — DO NOT USE UNTIL REFERENCE APPROVAL

You are an implementation worker, not a product designer.

Your job is to port an already approved reference into the repository. You have no authority to reinterpret the product, change the visual direction or add features.

## Repository

- Repository: `skerishKang/ai-revenue-lab`
- Issue: `#89`
- Product: Business 5 · `우리단지 이웃가게`
- English name: `Neighbor Market`
- Stable slug: `neighbor-market`
- Future implementation scope: `apps/neighbor-market/**`

## Authoritative reference

The CTO will provide an approved reference commit SHA on:

`design/business-05-neighbor-market-v2-89`

Read and reproduce exactly:

- `reference/business-05-neighbor-market-v2/index.html`
- `reference/business-05-neighbor-market-v2/README.md`
- `reference/business-05-neighbor-market-v2/DESIGN_SPEC.md`
- `reference/business-05-neighbor-market-v2/IMAGE_SOURCES.md`

Do not begin until the CTO explicitly states that the reference commit is approved.

## No-autonomy rule

Do not:

- rename the product;
- change the reference apartment;
- add the representative-chair name or any resident name;
- alter the category vocabulary;
- replace the layout with a dashboard;
- select another color system;
- use Baemin, Yogiyo, Karrot or Apartment i logos, characters, icons or copied layouts;
- remove photographic shop imagery;
- add a map as the main screen;
- invent ratings, review counts or transactions;
- add AI chat, recommendation explanations or robot imagery;
- add backend, authentication, database, messaging, payment, ordering or real submission;
- add remote analytics;
- add tracking cookies or localStorage;
- modify files outside the accepted scope;
- update the Business Registry in the implementation branch;
- create or merge a PR unless separately instructed.

When something in the reference is technically impossible, stop and report the exact conflict. Do not substitute a different design.

## Required repository shape

Create an isolated static workspace:

```text
apps/neighbor-market/
  README.md
  docs/
    PRODUCT_DECISION.md
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

You may split the approved single-file reference into local CSS and JavaScript, but the rendered result and interactions must remain visually and behaviorally equivalent.

## Product facts that must remain exact

- `방림명지로드힐`
- `광주광역시 남구 대남대로85번길 3`
- `192세대`
- `2개 동`
- `2015-10-30 사용승인`

Do not add the management-office phone number, resident names or unit details.

## Required routes/states

The static preview may use real paths or hashes, but every approved state must exist:

- home
- category/shop discovery
- shop detail
- resident benefits
- owner registration
- favorites/my page
- QA state index
- search empty state

## Required interactions

- text search across synthetic shop fixtures;
- category filter;
- availability/resident/benefit filters;
- hash or path navigation;
- favorite state for visual demonstration only;
- explicit toast or notice for every order, contact, login and submission action;
- no action sends or persists data.

## Visual contract

Match the reference at:

- 1440×1100
- 768×1024
- 390×844

Required:

- Pretendard or the approved self-hosted equivalent;
- exact brand color and token hierarchy;
- polished custom inputs/select boxes;
- apartment visual, search and categories in the first mobile flow;
- two-column desktop and list-style mobile shop cards;
- real photographic imagery;
- separate trust and benefit semantics;
- fixed mobile bottom navigation;
- detail mobile sticky actions;
- no horizontal page overflow;
- no generic placeholder SVG shop images.

## Image rule

During the first port, use the exact URLs and crops from the approved reference so screenshot comparison is meaningful.

Do not scrape or download third-party apartment-listing images.

After visual acceptance, a separate asset-hardening task may:

- download approved stock images;
- replace the generic apartment image with a user-supplied/cleared real photo;
- pin and self-host the font;
- add license files.

Do not perform that hardening unless separately instructed.

## Synthetic fixtures

Use the exact shop set from the reference JavaScript:

- 오늘의 반찬상
- 모퉁이 커피
- 맑은집 홈케어
- 차분한 수학
- 온결 헤어룸
- 포근펫 케어
- 단정 세무회계
- 작은정원 플라워
- 집앞 사진관
- 바른숨 움직임

Do not present these as real participating businesses.

## Tests

Add deterministic tests that prove:

- required files and screens exist;
- exact product and apartment strings exist;
- representative-chair/resident names are absent;
- exactly the approved category and shop fixture sets are present;
- internal navigation targets resolve;
- search/filter code exists and uses only local fixtures;
- no `fetch`, XMLHttpRequest, WebSocket, EventSource or form submission;
- no localStorage, sessionStorage or cookies;
- every preview action has an inert disclosure path;
- no copied commercial logos or brand names appear in rendered UI;
- viewport CSS includes the 920px and 640px responsive boundaries or an equivalent approved implementation;
- mobile navigation and detail sticky actions exist;
- no files outside `apps/neighbor-market/**` changed.

## Git rules

- Start from the exact base SHA provided by the CTO.
- Use a new dedicated worktree.
- Do not touch any dirty existing checkout.
- No rebase, amend or force push.
- Keep the implementation PR Draft.
- Do not close Issue #89.
- Do not merge.

## Completion report

Report:

- exact base, branch and head SHA;
- file list and diff stats;
- confirmation of zero out-of-scope files;
- tests with commands, counts and exit codes;
- zero-network and inert-action evidence;
- desktop/tablet/mobile screenshots;
- pixel/structure comparison against the approved reference;
- every deviation, however small;
- clean worktree status.

Stop after the report.
