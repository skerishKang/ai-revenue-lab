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
| 6 | `reserved-06` | Reserved — assignment unresolved | None canonically assigned | Reserved | Not applicable | Not applicable | Requires explicit portfolio decision |
| 7 | `reserved-07` | Reserved — assignment unresolved | None canonically assigned | Reserved | Not applicable | Not applicable | Requires explicit portfolio decision |
| 8 | `reserved-08` | Reserved — assignment unresolved | None canonically assigned | Reserved | Not applicable | Not applicable | Requires explicit portfolio decision |
| 9 | `reserved-09` | Reserved — assignment unresolved | None canonically assigned | Reserved | Not applicable | Not applicable | Requires explicit portfolio decision |
| 10 | `reserved-10` | Reserved — assignment unresolved | None canonically assigned | Reserved | Not applicable | Not applicable | Requires explicit portfolio decision |
| 11 | `reserved-11` | Reserved — assignment unresolved | None canonically assigned | Reserved | Not applicable | Not applicable | Requires explicit portfolio decision |
| 12 | `reserved-12` | Reserved — assignment unresolved | None canonically assigned | Reserved | Not applicable | Not applicable | Requires explicit portfolio decision |
| 13 | `personal-video-archive` | Personal Video Archive / 나의 영상 아카이브 | `apps/personal-video-archive/` | Incubation MVP; Korean-first bilingual redesign in Draft PR #78 | Current MVP is synthetic/local and has no accepted production authentication. Product must own private viewing-record authorization when integrated. | Global portal shell code and visual review accepted in Draft PR #78 at head 989d0056605e091a2fa842e49dc92f29aed68fbb; PR #78 remains unmerged pending latest-main integration and final merge review; actual portal production integration is not completed by the PR #78 merge alone | Issues #60, #62, #72, #76; PR #78 |
| 14 | `korean-ai-platform` | Korean AI Platform / 한국형 AI 실행 플랫폼 | `apps/korean-ai-platform/` | Private governed-execution console MVP in Draft PR #79 | Authentication, CSRF, and persistence are current limitations. Future integration must keep execution permissions and secrets product-local. | Not yet integrated | Issue #80; PR #79 |

## 4. Implemented or researched products awaiting number reconciliation

These products exist in the repository or portfolio record but do not receive an invented Business number in this registry.

| Stable slug | Product | Workspace | Current state | Number status | Required action |
|---|---|---|---|---|---|
| `world-feed` | World Feed / 월드 피드 | `apps/world-feed/` | Synthetic source-to-microbrief MVP and research track | Historic documents conflict: older repository tables assigned numbers inconsistently, while later Business 3 is explicitly Living Fiction and Business 4 is Living Learning. | Open an explicit numbering decision before displaying a Business number in the portal. |

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

The following mappings are treated as verified because current project work or issue evidence explicitly identifies them:

```text
Business 1  Personal Edition
Business 2  Living Travel
Business 3  Living Fiction
Business 4  Living Learning
Business 5  Neighbor Market → DanjiOn successor implementation
Business 13 Personal Video Archive
Business 14 Korean AI Platform
```

Business 1–5 are assigned as verified mappings. B5 now preserves its original Neighbor Market number while actual implementation continues in the external DanjiOn successor. Business 6–12 remain reserved. Business 13–14 remain assigned. World Feed remains unnumbered / number_reconciliation_required.

This is preferable to preserving contradictory historic tables, deleting successful Business lineage, or inventing assignments without evidence.
