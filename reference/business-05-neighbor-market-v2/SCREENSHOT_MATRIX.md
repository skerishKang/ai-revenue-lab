# Screenshot Matrix — Business 5 Resident-First Reference Review

## Purpose

The local worker renders screenshots only after syncing the exact approved reference branch. The worker does not redesign, restyle, reorder relationship tiers or replace images while producing evidence.

## Required environment

- reference branch: `design/business-05-neighbor-market-v2-89`
- reference path: `reference/business-05-neighbor-market-v2/`
- local server: `python -m http.server 4173 --bind 127.0.0.1`
- URL: `http://127.0.0.1:4173/index-v3.html`
- Chromium or Chrome
- browser zoom: 100%
- device scale factor: 1 unless the automation tool requires otherwise
- wait until the web font and visible images have settled

## Mandatory screenshots

### Desktop — 1440 × 1100

1. `home-desktop-1440x1100.png`
   - 방림명지로드힐 selector;
   - resident-mutual-aid lead copy;
   - explicit 1→2→3 priority explanation;
   - search and all eight categories;
   - Tier 1 section begins before Tier 2 and Tier 3.

2. `home-tier-sequence-desktop-1440x1800.png`
   - full-page capture;
   - `우리 아파트 주민의 가게와 서비스`;
   - `이웃 아파트 주민의 가게와 서비스`;
   - `우리 동네 가게`;
   - exact visual order current → neighbor → local.

3. `explore-desktop-1440x1100.png`
   - relationship filters;
   - grouped search results;
   - Tier 1 group before Tier 2 and Tier 3;
   - `가까운 순` visible only as a secondary, nonselected option.

4. `detail-current-desktop-1440x1100.png`
   - Tier 1 relationship badge;
   - service and price;
   - resident benefit;
   - disclosure that unit information is private and verification is not a quality guarantee.

5. `detail-neighbor-desktop-1440x1100.png`
   - Tier 2 relationship badge clearly differs from Tier 1.

6. `detail-local-desktop-1440x1100.png`
   - Tier 3 local-business label;
   - no resident-operation claim.

7. `benefits-desktop-1440x1100.png`
   - relationship label and benefit are separately visible.

8. `register-desktop-1440x1100.png`
   - relationship choice is the first registration step;
   - current apartment, nearby apartment and general local business choices;
   - storefront and non-storefront work types.

### Tablet — 768 × 1024

9. `home-tablet-768x1024.png`
   - four-column categories;
   - community lead and priority panel stack cleanly;
   - Tier 1 still appears first.

10. `explore-tablet-768x1024.png`
    - relationship groups remain explicit;
    - no navigation collision or horizontal overflow.

11. `detail-tablet-768x1024.png`
    - single-column detail;
    - relationship disclosure and actions remain readable.

### Mobile — 390 × 844

12. `home-mobile-390x844.png`
    - location;
    - resident-mutual-aid lead copy;
    - priority explanation;
    - search;
    - categories;
    - bottom navigation.

13. `home-current-tier-mobile-390x844.png`
    - first business section is Tier 1;
    - `방림명지로드힐 주민 운영` label is readable;
    - no general discount banner precedes Tier 1.

14. `explore-mobile-390x844.png`
    - vertical result list;
    - relationship filters scroll without page overflow;
    - result groups retain current → neighbor → local order.

15. `detail-current-mobile-390x844.png`
    - current-apartment badge;
    - relationship disclosure;
    - sticky bottom actions.

16. `benefits-mobile-390x844.png`
    - relationship and benefit semantics are separate;
    - no content hidden behind navigation.

17. `register-mobile-390x844.png`
    - three relationship choices are readable;
    - form controls do not overflow.

18. `my-mobile-390x844.png`
    - synthetic account state and nonpersistence disclosure.

19. `qa-mobile-390x844.png`
    - QA route remains separate from product home.

## Required state screenshots

20. `search-aircon-grouped-desktop-1440x1100.png`
    - search a term represented in multiple tiers when fixtures permit;
    - prove the result order remains current → neighbor → local.

21. `filter-current-mobile-390x844.png`
    - select `우리 단지 주민`;
    - only Tier 1 profiles remain.

22. `filter-neighbor-mobile-390x844.png`
    - select `이웃 단지 주민`;
    - only Tier 2 profiles remain.

23. `filter-local-mobile-390x844.png`
    - select `동네 가게`;
    - only Tier 3 profiles remain.

24. `search-empty-mobile-390x844.png`
    - enter a query matching no synthetic profile;
    - empty state displayed.

25. `favorite-state-mobile-390x844.png`
    - favorite icon toggled;
    - no persistence claim.

26. `preview-action-toast-mobile-390x844.png`
    - tap an order, contact or registration action;
    - toast explicitly states that nothing was sent or saved.

## Visual review checklist

For every screenshot verify:

- no horizontal page overflow;
- no broken image icon;
- Korean text is not clipped;
- focus and selected states are legible;
- no ordinary button or select uses unfinished browser-default styling;
- no fake rating or review count;
- no resident name, building/unit number or private contact data;
- Tier 1 is not merely a badge inside one mixed equal list;
- Tier 1 appears before Tier 2 and Tier 3;
- Tier 2 and Tier 3 remain visually distinguishable;
- `가까운 순` is not selected by default;
- relationship verification and discount benefit are not merged;
- bottom navigation and sticky actions do not cover content;
- mobile cards remain understandable in one scan.

## Worker report

The worker reports:

- exact local and remote SHA;
- browser version;
- screenshot command or tool;
- viewport dimensions;
- console errors;
- failed image requests;
- page `scrollWidth` versus `clientWidth` at 390, 768 and 1440;
- screenshot paths and dimensions;
- DOM evidence for current → neighbor → local section order;
- confirmation that no source changes were made while rendering.

Do not commit screenshots or modify the reference branch unless separately instructed.
