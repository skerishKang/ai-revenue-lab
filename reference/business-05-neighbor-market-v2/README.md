# Business 5 · 우리단지 이웃가게 Resident-First Reference

Issue: #89  
Branch: `design/business-05-neighbor-market-v2-89`  
Reference path: `reference/business-05-neighbor-market-v2/**`

## Status

This is a controlled reference design, not an implementation branch and not a production service.

The reference freezes product purpose, resident-priority rules, visual hierarchy and interaction behavior before a local coding model may create `apps/neighbor-market/**`.

Keep the reference PR Draft until visual review is complete.

## Product purpose

Business 5 is not primarily a nearby-shop directory.

> 우리 아파트 주민이 하는 일을 먼저 발견하고, 서로 이용하며 돕는 생활경제 서비스.

The fixed default order is:

```text
1. 방림명지로드힐 주민 운영
2. 이웃 단지 주민 운영
3. 우리 동네 가게
```

Tier 1 must be the first and strongest business section. Distance, discount size, sponsorship or payment must not move a lower tier above a higher tier.

The authoritative rule is `COMMUNITY_PRIORITY_MODEL.md`.

## Product identity

- Business number proposal: **5**
- Korean product name: **우리단지 이웃가게**
- English name: **Neighbor Market**
- Stable slug: `neighbor-market`
- Reference apartment: **방림명지로드힐**
- Public road address: **광주광역시 남구 대남대로85번길 3**
- Proposed future workspace: `apps/neighbor-market/**`

The public apartment facts in the reference are limited to name, address, 192 households, 2 buildings and 2015-10-30 use approval. No resident name, unit number, roster or verification evidence is displayed.

## Current primary prototype

Use **`index-v3.html`**.

The older `index.html` remains only as a comparison artifact and is not the current target.

The current prototype includes:

- resident-mutual-aid lead copy;
- explicit 1→2→3 relationship priority;
- search and eight practical categories;
- separate Tier 1, Tier 2 and Tier 3 home sections;
- resident-priority grouped search results;
- photographic business/service cards;
- representative price, availability, action and benefit;
- separate verification and benefit semantics;
- relationship-first owner registration;
- storefront, visiting, freelance, online and tutoring work types;
- mobile bottom navigation and detail sticky actions;
- benefits, my and QA states.

## Open the prototype locally

### Safe worktree launcher

Run `LOCAL_PREVIEW.ps1` from the reference directory. It:

- fetches the exact remote branch;
- leaves the existing checkout untouched;
- creates or refreshes a detached dedicated worktree;
- refuses to reset or clean a dirty target;
- starts a local static server;
- opens `index-v3.html`.

```powershell
powershell -ExecutionPolicy Bypass -File .\LOCAL_PREVIEW.ps1
```

Default local URL:

```text
http://127.0.0.1:4173/index-v3.html
```

Manual server:

```bash
python -m http.server 4173 --bind 127.0.0.1
```

## Routes

- `#home`
- `#explore`
- `#detail`
- `#benefits`
- `#register`
- `#my`
- `#qa`

## Safety and honesty

- All business names, relationship tiers, prices, benefits and availability states are synthetic.
- No order, contact, login or registration data is transmitted.
- Unsplash imagery and remote Pretendard CSS are temporary reference assets.
- No actual apartment photograph is claimed.
- A real 방림명지로드힐 photograph must be user-supplied or permission-cleared before publication.
- The representative-chair and all resident names are intentionally absent.
- `주민 운영 확인` does not mean a quality guarantee or management-office endorsement.

## Files

- `index-v3.html` — primary resident-first clickable reference
- `index.html` — superseded comparison artifact
- `COMMUNITY_PRIORITY_MODEL.md` — authoritative three-tier product and ranking rule
- `DESIGN_SPEC.md` — resident-first design and interaction contract
- `UI_REFINEMENT_V3.md` — consumer-marketplace finish rules
- `IMAGE_SOURCES.md` — temporary image and font ledger
- `LOCAL_HANDOFF_PROMPT.md` — strict future implementation prompt
- `LOCAL_PREVIEW.ps1` — safe local launcher
- `SCREENSHOT_MATRIX.md` — required evidence matrix

## Review sequence

1. Sync the exact reference branch into a clean dedicated worktree.
2. Open `index-v3.html` through the local server.
3. Capture all screenshots in `SCREENSHOT_MATRIX.md` without source changes.
4. Verify Tier 1 → Tier 2 → Tier 3 ordering on home and search.
5. Revise only the reference branch until explicitly approved.
6. Create a separate portfolio-number documentation change.
7. Create a separate implementation branch under `apps/neighbor-market/**`.
8. Give the implementation worker the approved SHA and strict handoff prompt.
9. Keep the implementation PR Draft until screenshot comparison passes.
