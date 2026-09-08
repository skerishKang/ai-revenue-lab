# B05 / DanjiOn Boundary Lock

Status: **AUTHORITATIVE GOVERNANCE BOUNDARY**

## Decision

`B05 — Neighbor Market / 우리단지 이웃가게` is retained only as a portfolio lineage identifier inside AI Revenue Lab.

The product lineage has already expanded into the independent product **DanjiOn / 단지온**.

Authoritative external product repository:

- `skerishKang/02-danji-on`

Portfolio display:

- `B05` may remain visible only as lineage/history metadata.
- Preferred status: `확장 → 단지온`.
- Internal UI / UX / backend phase gates are not applicable to B05.

## Hard No-Touch Rule

Do **not** create, redesign, refine, implement, deploy, or revive a separate B05 product surface inside `ai-revenue-lab`.

This includes:

- no new B05 standalone HTML;
- no B05 visual recovery or visual-authority pass;
- no B05 marketplace redesign;
- no B05 app/runtime implementation;
- no B05 backend/Auth/DB/storage work;
- no B05 Cloudflare/Pages deployment;
- no copying DanjiOn source back into an internal B05 app;
- no treating a B05 design experiment as the current product canonical.

If a task appears to ask for product work on B05, **STOP and route the work to DanjiOn** unless the user explicitly asks only for historical/portfolio metadata maintenance.

## DanjiOn Product Boundary

DanjiOn is an independent product and must be presented without portfolio numbering.

Public/product branding must use:

- `단지온`
- `DanjiOn`

Do not expose `B05`, `05`, `Business 05`, or similar portfolio numbering in the DanjiOn product UI, title, public URL, metadata, or deployment identity.

## Visual Authority

Do not use the 2026-08-16 `B05_Resident_Marketplace_Identity_Refinement` experiment as DanjiOn canonical. It is reference-only and is not a replacement for DanjiOn.

The stronger DanjiOn design lineage is the existing DanjiOn source and product work, including the source-locked field-demo direction built around:

`발견 → 검색 → 상세 → 주민혜택 → 내 일 알리기 → 홍보물 → 운영확인/승인 → 다시 발견`

The known canonical visual source used by the V2 work is the Drive HTML:

- `01_단지온_8월현장시연_통합시제품_v1_이미지리프레시.html`
- Drive file ID: `18Tl6-J5q9_7ZXx0Rb9FZS--QifQ09aZB`
- Recorded SHA256: `70d925fffdb24f752cce489fccd97bda2b5856edafe982be4a7e6abc54546f85`

Before any future DanjiOn implementation or deployment mutation, re-read the current `skerishKang/02-danji-on` remote state and current approved visual/product baseline. Do not assume an old SHA is still current.

## Deployment Separation

Existing DanjiOn comparison/preview deployments are protected evidence surfaces and must not be overwritten merely to create a cleaner public address.

Known comparison aliases include:

- `v1.padiem-danjion-web-preview.pages.dev`
- `v2.padiem-danjion-web-preview.pages.dev`
- `gateway.padiem-danjion-web-preview.pages.dev`

A clean DanjiOn public/demo address must be created as a **separate deployment identity/project**, not by repurposing B05 and not by overwriting those comparison aliases.

## Historical Evidence

Issue #440 records the portfolio decision that B05 is an expanded DanjiOn lineage and excludes B05 from internal development.

Historical B05 files/evidence may remain for audit/history, but they are not product authority.

## Approval Semantics

This boundary does not imply owner visual approval of any DanjiOn implementation.

`OWNER_UI_APPROVED=false` remains authoritative unless the owner explicitly approves a specific exact surface/revision.
