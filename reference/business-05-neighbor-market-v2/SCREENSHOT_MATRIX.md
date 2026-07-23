# Screenshot Matrix — Business 5 Reference Review

## Purpose

The local worker renders screenshots only after syncing the exact approved reference branch. The worker does not redesign, restyle or replace images while producing evidence.

## Required environment

- reference branch: `design/business-05-neighbor-market-v2-89`
- reference path: `reference/business-05-neighbor-market-v2/`
- local server: `python -m http.server 4173 --bind 127.0.0.1`
- URL: `http://127.0.0.1:4173/index.html`
- Chromium or Chrome
- browser zoom: 100%
- device scale factor: 1 unless the automation tool requires otherwise
- wait until web fonts and visible images have settled

## Mandatory screenshots

### Desktop — 1440 × 1100

1. `home-desktop-1440x1100.png`
   - apartment selector
   - hero image and generic-image disclosure
   - search and category selector
   - all eight category entries
   - first benefit row
   - first shop list row

2. `explore-desktop-1440x1100.png`
   - category/search results
   - filters
   - at least four shop cards
   - no horizontal clipping

3. `detail-desktop-1440x1100.png`
   - gallery
   - trust state
   - availability
   - representative services
   - resident benefit action sidebar

4. `benefits-desktop-1440x1100.png`
   - three-column benefit layout
   - eligibility and conditions visible

5. `register-desktop-1440x1100.png`
   - step navigation
   - select/input/textarea finish
   - preview disclosure

### Tablet — 768 × 1024

6. `home-tablet-768x1024.png`
   - four-column category behavior
   - two-column or adjusted result layout
   - no desktop navigation collision

7. `detail-tablet-768x1024.png`
   - single-column content
   - benefit/actions remain readable

### Mobile — 390 × 844

8. `home-mobile-390x844.png`
   - location
   - hero
   - search
   - category grid
   - first benefit
   - bottom navigation

9. `explore-mobile-390x844.png`
   - vertical shop list
   - photo and text alignment
   - filters scroll horizontally without page overflow

10. `detail-mobile-390x844.png`
    - gallery
    - title and verification
    - representative service
    - sticky bottom action bar

11. `benefits-mobile-390x844.png`
    - readable eligibility and expiry
    - no content hidden behind bottom navigation

12. `register-mobile-390x844.png`
    - labels and controls
    - custom select finish
    - no input overflow

13. `my-mobile-390x844.png`
    - empty/synthetic account state
    - clear preview disclosure

14. `qa-mobile-390x844.png`
    - QA routes remain separate from the product home

## State screenshots

15. `search-empty-mobile-390x844.png`
    - enter a query that matches no synthetic shop
    - empty state displayed

16. `favorite-state-mobile-390x844.png`
    - favorite icon toggled
    - no claim that data was persisted

17. `preview-action-toast-mobile-390x844.png`
    - tap order, contact or registration action
    - toast explicitly states that nothing was sent or saved

## Visual review checklist

For every screenshot verify:

- no horizontal page overflow;
- no broken image icon;
- Korean text is not clipped;
- focus and selected states are legible;
- no ordinary button or select appears with the browser default finish;
- no unexplained English-first heading dominates the page;
- no fake rating/review data appears;
- no resident name, building/unit number or private contact data appears;
- generic apartment imagery is not described as the actual apartment;
- bottom navigation and sticky actions do not cover content;
- product home is not a QA index;
- mobile card information can be understood in one scan.

## Worker report

The worker reports:

- exact local and remote SHA;
- browser version;
- screenshot command/tool;
- viewport dimensions;
- console errors;
- failed image requests;
- page-level `scrollWidth` versus `clientWidth` for 390, 768 and 1440;
- screenshot file paths and dimensions;
- no source changes made while rendering.

Do not commit screenshots or modify the reference branch unless separately instructed.
