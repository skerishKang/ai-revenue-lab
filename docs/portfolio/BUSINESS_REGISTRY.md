# AI Revenue Lab Business Registry

- Status: Canonical after merge of Issue #83
- Owner: AI Revenue Lab portfolio governance
- Numbering rule: only evidenced number-to-product mappings are verified

## 1. Purpose

This registry is the authoritative portfolio catalog for Business numbering, product workspaces, lifecycle status, identity mode, authorization ownership, and deployment integration.

It prevents four recurring errors:

1. assigning the same Business number to different products;
2. treating a repository workspace as proof of a final Business number;
3. treating shared Firebase authentication as shared product authorization;
4. presenting a preview or synthetic MVP as an active production service.

For a numbered Business that has expanded into an external successor product, this registry preserves the number while `docs/portfolio/BUSINESS_EXPANSION_LINEAGE.md` records the successor and implementation-location boundary.

## 2. Registry fields

Every verified Business entry must eventually record:

- Business number;
- stable slug;
- Korean and English display names;
- repository workspace;
- lifecycle state;
- primary audience and product promise;
- authentication mode;
- authorization owner;
- runtime and database class;
- portal integration state;
- canonical issues or decision documents;
- public or staging hostname when approved;
- known limitations;
- successor or external implementation state when applicable.

Secrets, database URLs, Firebase service-account material, API keys, private hostnames, and user data are prohibited.

## 3. Canonical numbered Businesses

| No. | Stable slug | Product | Workspace | Current lifecycle | Identity and authorization | Portal integration | Evidence |
|---:|---|---|---|---|---|---|---|
| 1 | `personal-edition` | Personal Edition / 퍼스널 에디션 | `apps/personal-edition/` | Active implementation; production foundation open | Shared Firebase identity is planned/being integrated; Personal Edition owns participant/admin authorization. Existing invitation-token and admin-secret controls remain authoritative until migrated. | First integration target | Issues #51, #54, #57; product README |
| 2 | `living-travel` | Living Travel / 리빙 트래블 | `apps/living-travel/` | Implemented private MVP; production foundation and pre-staging security contracts merged | Shared Firebase identity; Living Travel owns traveler/operator mapping and data access. | Not yet integrated; no portal implementation in Issue #74 | Issues #32, #43, #69, #74, #86 |
| 3 | `living-fiction` | Living Fiction / 리빙 픽션 | `apps/living-fiction/` | Implemented private reader/editorial MVP; production infrastructure open | Product-local invite, reader, and editorial authorization; shared identity integration not yet accepted as a completed portal flow. | Not yet integrated | Issues #34, #55, #75, #77 |
| 4 | `living-learning` | Living Learning / 리빙 러닝 | `apps/living-learning/` | Isolated adaptive-learning MVP and static adaptive UI preview | Current product-local/synthetic access contract; portfolio identity integration not yet implemented. | Not yet integrated | Issue #37 and current Business 4 project direction |
| 5 | `neighbor-market` | Neighbor Market / 우리단지 이웃가게 | **External successor: DanjiOn / 단지온 — `skerishKang/02-danji-on`; `NO_INTERNAL_IMPLEMENTATION`** | `private_preview`; B5 number preserved as `EXPANDED_SUCCESSOR` lineage | DanjiOn external source owns resident verification, listing eligibility, operator/moderator/admin roles, Auth and product records. AI Revenue Lab does not create a parallel authorization implementation. | List/link only inside AI Revenue Lab; actual product work stays in DanjiOn | Owner decision 2026-08-09; `BUSINESS_EXPANSION_LINEAGE.md`; prior Issues #89 and #99 |
| 6 | `world-feed` | World Feed / 월드 피드 — current commercial positioning: Personal World Discovery / 나만의 세계 발견 편집자 | `apps/world-feed/` with current review implementation in `reference/business-06-world-feed-v1/` | `private_preview`; commercial thesis narrowed for concierge validation | Current repository work is synthetic/frontend evidence only; no accepted live account or recommendation-service authorization is implied by numbering. | Not integrated | Issues #98, #155, #165, #562, #616, #617; numbered execution #396/#465 |
| 7 | `personal-meaning-map` | Personal Meaning Map / 개인 의미 지도 | `reference/business-07-personal-meaning-map-v1/` | `private_preview`; reviewable UI/UX evidence | Synthetic/reference-only state; no product authentication, private-data import, persistence, or backend authorization is implied by numbering. | Not integrated | Issue #166; later numbered UI/UX execution under #396/#465; #617 reconciliation |
| 8 | `family-newspaper` | Family Newspaper / 우리 가족 신문 | `reference/business-08-family-newspaper-v1/` | `private_preview`; reviewable UI/UX evidence | Synthetic/reference-only state; no family-data import, account, sharing, persistence, or backend authorization is implied by numbering. | Not integrated | Issue #168; later numbered UI/UX execution under #396/#465; #617 reconciliation |
| 9 | `personalized-childrens-story` | Personalized Children’s Story / 우리 아이 이야기 | `reference/business-09-personalized-childrens-story-v1/` | `private_preview`; reviewable UI/UX evidence | Synthetic/reference-only state; no child-data import, account, generation service, persistence, or backend authorization is implied by numbering. | Not integrated | Issue #170; later numbered UI/UX execution under #396/#465; #617 reconciliation |
| 10 | `fan-magazine` | Fan Magazine / 나만의 팬 매거진 | `reference/business-10-fan-magazine-v1/` | `private_preview`; reviewable UI/UX evidence | Synthetic/reference-only state; no live ingestion, public-figure data pipeline, account, persistence, or backend authorization is implied by numbering. | Not integrated | Issue #171; later numbered UI/UX execution under #396/#465; #617 reconciliation |
| 11 | `language-learning-magazine` | Language Learning Magazine / 나의 언어학습 매거진 | `reference/business-11-language-learning-magazine-v1/` | `private_preview`; reviewable UI/UX evidence | Synthetic/reference-only state; no learner-data import, evaluation service, account, persistence, or backend authorization is implied by numbering. | Not integrated | Issue #172; later numbered UI/UX execution under #396/#465; #617 reconciliation |
| 12 | `creator-mini-media` | Creator Mini-Media / 크리에이터 미니미디어 | `reference/business-12-creator-mini-media-v1/` | `private_preview`; reviewable UI/UX evidence | Synthetic/reference-only state; no creator account connection, publishing, persistence, analytics, or backend authorization is implied by numbering. | Not integrated | Issue #173; later numbered UI/UX execution under #396/#465; #617 reconciliation |
| 13 | `personal-video-archive` | Personal Video Archive / 나의 영상 아카이브 | `apps/personal-video-archive/` | `private_preview`; current main contains the Private Cinema Ledger V2 static review experience and deterministic preview/production-review builders; no live user persistence or provider runtime is implied | Current published/review surfaces are synthetic/static and have no accepted live end-user authentication or persistence. Any future private viewing-record runtime remains product-local authorization. | Padiem Lab aggregate `/b13/` generated-preview route merged in PR #801 and is recorded live under Issue #778. The legacy standalone `ai-revenue-personal-video-archive` Pages project remains operationally separate; Issue #225 narrowed its Git-connected watch scope to `apps/personal-video-archive/**` and is under final closure verification. | Issues #60, #62, #72, #76, #118, #225; PRs #78, #483, #546, #801 |
| 14 | `korean-ai-platform` | Korean AI Platform / 한국형 AI 실행 플랫폼 | `apps/korean-ai-platform/` | Private governed-execution console MVP in Draft PR #79 | Authentication, CSRF, and persistence are current limitations. Future integration must keep execution permissions and secrets product-local. | Not yet integrated | Issue #80; PR #79 |

### 3A. Proposed-number portfolio entries

The following entries are intentionally **not canonical**. They are recorded so the portfolio can review an evidenced product identity without pretending that a conversation or local prototype already completed canonical-number promotion.

| Proposed No. | Stable slug | Product | Proposed workspace | Current lifecycle | Boundary | Evidence |
|---:|---|---|---|---|---|---|
| 60 | `ai-api` | AI API / AI API 탐색 허브 | `apps/ai-api/` — not created by registration alone | `concept`; UI exploration in progress; backend frozen | Discovery/deal intelligence owns current API/provider/model offers, source verification, expiry/eligibility and cinematic discovery. Business 14 remains the execution/routing platform. | Issue #650; `BUSINESS_60_AI_API_PROPOSAL.md` |

## 4. Reconciled numbering history for B6–B12

Before Issue #617, the canonical registry still showed B6–B12 as reserved even though later portfolio execution repeatedly used stable B6–B12 product labels. The historical Phase 1 issues intentionally described those numbers as proposed/noncanonical because they were not authorized to rewrite the registry.

Issue #617 completed the duplicate/conflict review and found no competing product claiming the same B6–B12 slots. The canonical assignments above therefore preserve the existing stable slugs and workspaces rather than creating new products, duplicate folders, or silent renumbering.

Important history and boundaries:

- B6 preserves `world-feed` as the stable product identity. `Personal World Discovery` is the current narrowed commercial positioning, not a second Business or a replacement slug.
- B6 preserves `apps/world-feed/` as the existing technical/research workspace and `reference/business-06-world-feed-v1/` as the current numbered review implementation.
- B7–B12 preserve their existing `reference/business-XX-...-v1/` workspaces as the current implementation authority. Canonical numbering does not require creating duplicate `apps/` placeholders.
- Historical Issues #166, #168, #170, #171, #172 and #173 remain truthful evidence that their numbers were proposed at the time those issues were authored.
- Canonical assignment does not imply owner UI approval, backend authorization, live data, authentication, persistence, billing, or Production readiness.
- B6 product and validation boundaries in #98 and #616 remain separate from the numbering decision.
- External/successor boundaries governed by #393 and merged lineage policy remain unchanged.

## 5. Candidate concepts without a canonical workspace or number

Ideas discussed outside a merged registry entry are portfolio candidates, not numbered Businesses.

They may be recorded in a future candidate backlog with:

- problem statement;
- target user;
- evidence source;
- proposed workspace;
- overlap analysis;
- proposed Business number;
- accept/reject decision.

A conversation, ranking, contest proposal, prototype outside the repository, or product recommendation does not assign a canonical Business number.

## 6. Lifecycle vocabulary

Use only these lifecycle values in future portal metadata:

- `concept`
- `research`
- `incubation`
- `private_preview`
- `pilot`
- `active`
- `paused`
- `archived`
- `reserved`
- `number_reconciliation_required`

Lifecycle describes product maturity, not user authorization or expansion lineage. Expansion state such as `EXPANDED_SUCCESSOR` is separate metadata defined in `BUSINESS_EXPANSION_LINEAGE.md`.

## 7. Portal access vocabulary

A future portal implementation uses a separate user-specific access state:

- `available`
- `request_access`
- `pending`
- `invite_required`
- `not_authorized`
- `coming_soon`
- `maintenance`
- `suspended`

See `docs/operations/DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md` for the canonical Production deployment and rollback policy. Cloudflare deployment Preview is not required as a deployment gate.

Lifecycle `private_preview` (Section 6) is a product maturity phase, distinct from Cloudflare deployment Preview.

A Business may be `private_preview` while one user is `available` and another is `invite_required`.

## 8. Identity and deployment registry rules

### Shared identity

The portfolio identity provider is Firebase project `ai-revenue-lab-identity`.

This is public architecture metadata, not a credential. No service-account JSON, API secret, private key, or unrestricted configuration artifact is stored here.

### Product authorization

Every Business remains the authority for its own memberships, roles, and records. When a Business has an external successor, that successor source owns the live product authorization; AI Revenue Lab does not recreate it in parallel.

### Deployment

When a Business gains an approved deployment, record only safe metadata:

- hosting/runtime class, such as Cloudflare Pages or Modal;
- non-secret project name when required for operations;
- approved public or staging URL;
- environment status;
- last verified deployment evidence.

Do not infer production status from a branch preview or a successful static build.

## 9. Number assignment procedure

A new or reconciled Business number requires:

1. a GitHub Issue that names the proposed number and product;
2. a duplicate and conflict search across this registry, issues, and workspaces;
3. confirmation that the number is not verified elsewhere;
4. workspace and product-boundary definition;
5. registry update in a reviewed PR;
6. root and apps README update when the portfolio summary changes.

Do not renumber an implemented Business silently. A renumbering must document aliases, affected issues, routes, deployment names, evidence records, and migration consequences.

A Business that expands to an external successor keeps its original number. Expansion is not renumbering and the vacated number must not be reused.

## 10. Current reconciliation findings

The following mappings are verified through the registry procedure and preserved as canonical portfolio identities:

```text
Business 1  Personal Edition
Business 2  Living Travel
Business 3  Living Fiction
Business 4  Living Learning
Business 5  Neighbor Market → DanjiOn successor implementation
Business 6  World Feed / Personal World Discovery
Business 7  Personal Meaning Map
Business 8  Family Newspaper
Business 9  Personalized Children’s Story
Business 10 Fan Magazine
Business 11 Language Learning Magazine
Business 12 Creator Mini-Media
Business 13 Personal Video Archive
Business 14 Korean AI Platform
```

Proposed-number entries are reviewed separately and do not join the canonical list merely by appearing in Portfolio Console metadata. B60 `ai-api` is currently proposed under Issue #650.

B6–B12 were reconciled under Issue #617 after their earlier proposed/operational use had outpaced the older reserved registry. This assignment preserves the historical evidence and existing workspaces; it does not retroactively convert old proposed-number records into claims that the numbers were canonical at the time.