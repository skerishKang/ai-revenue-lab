# Business 5 · 우리단지 이웃가게 v2 Reference

Issue: #89  
Branch: `design/business-05-neighbor-market-v2-89`  
Reference path: `reference/business-05-neighbor-market-v2/**`

## Status

This is a controlled **reference design**, not an implementation branch and not a production service.

The purpose is to freeze product direction, content hierarchy, visual quality and interaction behavior before a local coding model is allowed to create `apps/neighbor-market/**`.

Do not merge this reference branch into `main` until the visual direction is explicitly approved.

## Product

- Business number proposal: **5**
- Korean product name: **우리단지 이웃가게**
- English name: **Neighbor Market**
- Stable slug: `neighbor-market`
- Reference apartment: **방림명지로드힐**
- Public road address: **광주광역시 남구 대남대로85번길 3**
- Proposed future workspace: `apps/neighbor-market/**`

The public apartment facts used in the prototype are limited to name, address, 192 households, 2 buildings and 2015-10-30 use approval. No resident name, building/unit number, roster or identity evidence is included.

## What changed from v1

The first reference was rejected because it looked like a regional editorial landing page and used placeholder-style graphics.

v2 is rebuilt as a mobile-first Korean consumer marketplace reference:

- apartment selector and location context at the top;
- large search field;
- direct category entry;
- photographic business cards;
- representative menu/service and price before detail navigation;
- live availability language such as `오늘 주문 가능`, `오늘 상담 가능` and `오늘 예약 1자리`;
- resident benefit banners;
- business-specific actions such as order, reservation, quote and consultation;
- mobile bottom navigation;
- shop-detail sticky mobile actions;
- dedicated favorites/my page and QA states.

## Open the prototype

Open `index.html` in a modern browser.

The prototype is a single self-contained interaction document except for temporary remote font and image references. Navigation uses URL hashes:

- `#home`
- `#explore`
- `#detail`
- `#benefits`
- `#register`
- `#my`
- `#qa`

## Safety and honesty

- All shop names, prices, benefits, opening states and service descriptions are synthetic.
- No order, contact, login or registration data is transmitted.
- Temporary Unsplash images are visual placeholders for reference review.
- The apartment hero image is not a photograph of 방림명지로드힐; it is explicitly marked as a reference image.
- Before production, the apartment photo must be replaced with a user-supplied or permission-cleared real photo.
- The current representative-chair name is intentionally not displayed.

## Files

- `index.html` — clickable product reference
- `DESIGN_SPEC.md` — product, visual and interaction decisions
- `IMAGE_SOURCES.md` — temporary image and font source ledger
- `LOCAL_HANDOFF_PROMPT.md` — strict future local-worker prompt

## Review sequence

1. Review the prototype visually on desktop and mobile.
2. Revise only the reference branch until approved.
3. Create a separate documentation change for Business 5 registry assignment.
4. Create a separate implementation branch under `apps/neighbor-market/**`.
5. Give the local worker the strict handoff prompt and reference commit SHA.
6. Keep the implementation PR Draft until screenshot comparison passes.
