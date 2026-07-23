# Business 5 · 우리단지 이웃가게 Resident-First Reference

Issue: #89  
Static demo issue: #106  
Reference branch: `design/business-05-neighbor-market-v2-89`  
Static demo branch: `feat/business-05-static-demo-106`  
Reference path: `reference/business-05-neighbor-market-v2/**`

## Status

This directory contains a controlled reference design and a Phase 0 static clickable demo. Neither is a production service or a persisted MVP.

The reference freezes product purpose, resident-priority rules, visual hierarchy and interaction behavior before a local coding model may create `apps/neighbor-market/**`.

The Phase 0 demo lets a viewer click through resident, listing-owner and operator scenarios using synthetic in-memory state only. It has no authentication, resident verification, database, real messaging, payment, approval authority or production backend.

Keep both PRs Draft until their separate review gates pass.

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

## Current primary reference prototype

Use **`index-v3.html`** for the approved visual and hierarchy reference.

The older `index.html` remains only as a comparison artifact and is not the current target.

The reference prototype includes:

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

## Phase 0 static clickable demo

Entry file:

```text
demo/index.html
```

The demo is based on approved reference commit:

```text
89add370b78e5f7567a2acb44e53a45f07680372
```

It adds clickable synthetic flows for:

- resident discovery, search, detail, favorites and request simulation;
- listing-owner registration, preview, submission and status;
- operator queue, review detail, approve, request-changes and reject simulations.

All state is browser-memory-only and resets on refresh. Every write-like action must state that nothing was really sent, stored, verified, approved, paid or delivered.

Demo documents:

- `demo/DEMO_CONTRACT.md`
- `demo/DEMO_GUIDE.md`
- `demo/DEMO_QA.md`

## Open locally

### Reference launcher

Run `LOCAL_PREVIEW.ps1` from the reference directory. It opens `index-v3.html` from a protected detached worktree.

```powershell
powershell -ExecutionPolicy Bypass -File .\LOCAL_PREVIEW.ps1
```

Default reference URL:

```text
http://127.0.0.1:4173/index-v3.html
```

### Static demo

From the `demo/` directory:

```bash
python -m http.server 4175 --bind 127.0.0.1
```

Open:

```text
http://127.0.0.1:4175/index.html
```

The demo can also be opened directly as a local file. No backend, package install, build command, database or API key is required.

## Reference routes

- `#home`
- `#explore`
- `#detail`
- `#benefits`
- `#register`
- `#my`
- `#qa`

The Phase 0 demo uses in-page navigation rather than requiring manual hash editing.

## Safety and honesty

- All business names, relationship tiers, prices, benefits, requests and review states are synthetic.
- No order, contact, login or registration data is transmitted.
- Unsplash imagery and remote Pretendard CSS are temporary reference assets.
- No actual apartment photograph is claimed.
- A real 방림명지로드힐 photograph must be user-supplied or permission-cleared before publication.
- The representative-chair and all resident names are intentionally absent.
- `주민 운영 확인` does not mean a quality guarantee or management-office endorsement.
- Demo operator mode is a simulation, not authentication or authority.

## Files

- `index-v3.html` — primary resident-first clickable reference
- `index.html` — superseded comparison artifact
- `demo/index.html` — Phase 0 static clickable demo entry
- `demo/styles.css` — demo-only responsive presentation
- `demo/app.js` — demo-only in-memory interactions and role flows
- `demo/DEMO_CONTRACT.md` — supported scope and false assumptions to avoid
- `demo/DEMO_GUIDE.md` — run instructions and demonstration script
- `demo/DEMO_QA.md` — route, interaction and screenshot matrix
- `COMMUNITY_PRIORITY_MODEL.md` — authoritative three-tier product and ranking rule
- `DESIGN_SPEC.md` — resident-first design and interaction contract
- `UI_REFINEMENT_V3.md` — consumer-marketplace finish rules
- `IMAGE_SOURCES.md` — temporary image and font ledger
- `LOCAL_HANDOFF_PROMPT.md` — strict future implementation prompt
- `LOCAL_PREVIEW.ps1` — safe local launcher
- `SCREENSHOT_MATRIX.md` — required reference evidence matrix

## Review sequence

1. Keep the approved reference commit fixed as the visual baseline.
2. Run the Phase 0 demo from a clean worktree.
3. Verify every primary action responds and every simulated write states that nothing was sent or saved.
4. Capture resident, owner and operator screenshots at 390×844, 768×1024 and 1440×1100.
5. Keep all Phase 0 changes under `reference/business-05-neighbor-market-v2/**`.
6. Do not create `apps/neighbor-market/**` through the static-demo issue.
7. Complete the separate portfolio-number documentation change.
8. Use Issue #100 only when a persisted and authorized private MVP is approved.
9. Keep the demo PR Draft until exact-head review and screenshot QA pass.
