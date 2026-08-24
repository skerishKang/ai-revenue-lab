# B60 Editorial Operations

Status: **CANONICAL OPERATING PLAYBOOK**  
Effective: **2026-08-25**  
Tracks: #704

This playbook defines what to do when the owner brings one or more X/web links into any future session.

## 1. Default interpretation of an incoming link

When the owner says things such as:

- “이거 추가해”
- “오늘 발견한 것들”
- “이 링크들 봐봐”
- “이것도 사이트에 넣자”

interpret the links as **editorial opportunity intake** by default.

Do **not** automatically reinterpret them as:

- provider-catalog expansion
- crawler/automation work
- backend architecture work
- API execution integration

unless the owner explicitly asks for those things.

## 2. Minimum intake workflow

For each incoming item:

1. Open/read the supplied source.
2. Extract the core user benefit.
3. Identify provider, product/model, access type, and CTA destination.
4. Check whether the claim is time-sensitive.
5. Verify material claims against an official/primary source when practical.
6. Separate verified facts from source-only/pending claims.
7. Decide editorial importance and placement.
8. Select an appropriate image/visual asset.
9. Record source/provenance.
10. Add/update the B60 data and presentation without weakening existing truth gates.
11. Render/review desktop and mobile when the visual surface changes materially.

## 3. Canonical intake fields

An opportunity should ideally resolve to the following fields. Missing optional fields do not block intake; missing truth-critical fields may keep it pending.

```text
id
headline
benefitLabel
summary
provider
productOrModel
opportunityType
categories[]
access[]
priceOrCredit
limit
startAt
expiresAt
expiryVerification
eligibility
ctaUrl
sourceUrl
sourceLabel
sourceAuthority
observedAt
verifiedAt
verification
pendingClaim
image
imageAlt
imageSource
imageCredit
imageSourcePage
editorialPriority
```

## 4. Opportunity types

Use the smallest meaningful set; do not over-model.

```text
LIMITED_FREE
FREE_CREDIT
ALWAYS_FREE
FREE_MODEL
FREE_TIER
TRIAL
GPU_CREDIT
PREVIEW_BETA
OTHER_FREE_OPPORTUNITY
```

The displayed Korean copy can be more natural than the internal enum.

## 5. Editorial placement decision

### Lead / main feature

Use when an item is unusually useful, timely, broad, or attractive. It should be understandable even to a visitor who does not know the provider.

Examples of signals:

- meaningful free credit
- unusually high limit
- valuable model temporarily free
- short expiry requiring attention
- broad developer relevance
- major new launch

### Today board / secondary feature

Use for strong opportunities that do not deserve the full lead.

### Standard live item

Use for useful but narrower or lower-value current opportunities.

### Always-free section

Use for durable free access, not temporary promotions.

### Checking / pending

Use when the lead is interesting but a key material fact is not verified.

## 6. Urgency rules

Never manufacture urgency.

`종료 임박` is allowed only when:

```text
expiresAt != null
AND expiryVerification is authoritative/verified
```

If a social post claims an end date but the date cannot be verified, show it as pending/checking rather than a countdown.

## 7. Source hierarchy

Prefer evidence in this order:

1. official product/pricing/docs page
2. official company/model blog or release note
3. official X/social account announcement
4. official GitHub repository/release
5. credible partner announcement
6. community/social discovery post

A lower-tier source can trigger discovery. It should not silently overwrite stronger contradictory evidence.

## 8. Manual curation workflow is acceptable

The owner does not need a CMS at this stage.

A normal operating loop is:

```text
Owner finds link
→ sends link in chat
→ assistant verifies/extracts
→ assistant decides editorial placement
→ assistant selects visual
→ assistant updates repo/data/UI
→ browser QA
```

Do not build a large admin panel or automated ingestion system merely because the workflow is manual.

Build tooling only when the repeated manual burden becomes material.

## 9. Batch intake

When the owner supplies multiple links, process them as one editorial batch.

For each item, classify:

```text
PUBLISH_NOW
PUBLISH_ALWAYS_FREE
PENDING_VERIFICATION
DUPLICATE_OR_EXISTING
NOT_RELEVANT
EXPIRED
```

Then decide the overall page rhythm. Do not force all items into identical cards.

## 10. Duplicate and update behavior

Before creating a new record:

- check stable ids/current signals;
- check whether the same benefit already exists under another source;
- distinguish a new opportunity from a change to an existing one.

Use the existing review/NEW_SIGNAL machinery where appropriate. Do not create duplicate provider records just because a new post mentions the same service.

## 11. Publication safety

Manual curation does not mean unreviewed publication.

Preserve these constraints:

- official evidence for material facts where available;
- explicit pending state for uncertain claims;
- no fabricated dates/limits;
- provenance for images and claims;
- no autonomous publication authority introduced by convenience tooling.

## 12. Definition of done for an editorial intake

An item is done when the user-facing page makes these obvious:

- **무엇을 공짜로 얻는가**
- **언제/얼마나 쓸 수 있는가**
- **상시인지 한시인지**
- **어디서 실제로 쓰는가**
- **무엇이 공식 확인되었는가**

A technically correct DB row that fails to communicate those points is not sufficient completion.
