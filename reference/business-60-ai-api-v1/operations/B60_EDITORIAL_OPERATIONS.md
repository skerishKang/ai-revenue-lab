# B60 Editorial Operations

Status: **CANONICAL OPERATING PLAYBOOK**  
Effective: **2026-08-25**  
Tracks: #704, #707, #726

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
4. Classify the free-benefit mechanic and eligibility separately.
5. Check whether the claim is time-sensitive.
6. Verify material claims against official/primary evidence when practical.
7. Separate verified facts from source-only/pending claims.
8. Decide editorial importance independently from offer mechanic.
9. Select an appropriate image/visual asset.
10. Record source/provenance.
11. Add/update the B60 data and presentation without weakening existing truth gates.
12. Render/review desktop and mobile when the visual surface changes materially.

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
editorialRole
categories[]
access[]
priceOrCredit
limit
startAt
expiresAt
expiryVerification
eligibility
conditions[]
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
```

## 4. Opportunity mechanics

Keep the primary mechanic small and meaningful:

```text
TEMP_FREE_ACCESS
SIGNUP_CREDIT
RECURRING_FREE
ALWAYS_FREE
```

Meaning:

- `TEMP_FREE_ACCESS`: an existing/special model, API or service is temporarily free. This is normally the highest-value discovery class.
- `SIGNUP_CREDIT`: one-time credit tied to creating/qualifying a new account. Keep it visually separate from temporary free access.
- `RECURRING_FREE`: free allocation or credit replenishes daily/monthly/periodically.
- `ALWAYS_FREE`: persistent free tier/model/router/access.

Use category/subtype tags for API, Coding, Image, Video, GPU, Voice, Trial, Preview, Model, Credit, etc. Do not create a new primary mechanic for every category.

### Eligibility

Eligibility is independent from the mechanic:

```text
ANY_USER
NEW_USER_ONLY
ACCOUNT_REQUIRED
UNKNOWN
```

Record card/payment/subscription/region/workspace/balance requirements separately in `conditions[]` and user-facing copy.

## 5. Editorial role and placement

Editorial importance is not the same thing as freshness or mechanic.

```text
HOTTEST
JUST_DROPPED
STANDARD
REFERENCE
```

### HOTTEST / lead

Use when an item is unusually useful, timely, broad, attractive, or receiving exceptional attention. It should be understandable even to a visitor who does not know the provider.

### JUST_DROPPED

Use for the newest meaningful opportunity that deserves a dedicated new-release treatment. It may coexist with a different HOTTEST lead.

### Standard live item

Use for useful active opportunities that do not deserve the lead/new-release treatment.

### Reference

Use for durable free access and signup-benefit reference layers.

### Checking / pending

Use when a lead is interesting but a material fact has not been verified.

A large number of signup-credit offers is not evidence that signup credits should dominate the page. They normally belong to `가입 혜택` unless individually exceptional.

## 6. Urgency rules

Never manufacture urgency.

`종료 임박` requires all of:

```text
expiresAt != null
AND expiryVerification is authoritative/verified
AND expiry is within the configured urgency window (default: 7 days)
```

An offer can have a verified future expiry without being `종료 임박` yet.

If a community/social post claims an end date but the date cannot be corroborated authoritatively, show it as pending/checking rather than a countdown.

## 7. Source authority

Prefer evidence in this order for stable product facts:

1. official product/pricing/docs page
2. official company/model blog or release note
3. official brand/model social account announcement
4. official GitHub repository/release
5. credible partner announcement
6. community/social discovery post

Important distinction:

- `OFFICIAL_WEB` / `VERIFIED_OFFICIAL_WEB`: primary web/docs evidence.
- `OFFICIAL_SOCIAL` / `VERIFIED_OFFICIAL_SOCIAL`: the provider/model owner itself explicitly announced the claim on its official social account.
- community social posts remain discovery leads unless independently verified.

An official social announcement can authoritatively establish a temporary promotion and its announced dates. Stable technical details should still be cross-checked against official docs/product pages when possible.

A lower-tier source must not silently overwrite stronger contradictory evidence.

## 8. Manual curation workflow is acceptable

The owner does not need a large CMS at this stage.

A normal operating loop is:

```text
Owner finds link
→ sends link in chat
→ assistant verifies/extracts
→ assistant classifies mechanic + eligibility
→ assistant decides editorial role
→ assistant selects visual
→ assistant updates repo/data/UI
→ browser QA
```

Do not build a large admin panel or automated ingestion system merely because the workflow is manual.

Build tooling only when the repeated manual burden becomes material.

### Lightweight intake helper

A lightweight **편집 인입 워크벤치** is allowed as an operator convenience after repeated manual intake work. Its role is limited to:

```text
operator-entered facts
→ field normalization
→ truth-gate warnings
→ publication disposition suggestion
→ candidate JSON / repo-compatible snippet
```

The workbench **게시 권한을 갖지 않는다**. It must not hold GitHub credentials, write to the repository, call provider APIs, scrape social sources, or autonomously promote a candidate. Verification still happens outside the helper using the source hierarchy in this playbook, and final repository mutation remains an explicit human/assistant-reviewed step.

The canonical helper location is:

```text
operator/editorial-intake/
```

It is not linked from the public B60 consumer navigation.

## 9. Batch intake

When the owner supplies multiple links, process them as one editorial batch.

For each item, classify publication status:

```text
PUBLISH_NOW
PUBLISH_ALWAYS_FREE
PUBLISH_SIGNUP_BENEFIT
PENDING_VERIFICATION
DUPLICATE_OR_EXISTING
NOT_RELEVANT
EXPIRED
```

Then decide the overall page rhythm. Do not force all items into identical cards and do not assume newest = hottest.

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
- **왜 무료인가** — 한시 개방 / 가입 크레딧 / 반복 무료 / 상시 무료
- **누가 받을 수 있는가**
- **언제/얼마나 쓸 수 있는가**
- **어디서 실제로 쓰는가**
- **무엇이 공식 확인되었는가**

A technically correct DB row that fails to communicate those points is not sufficient completion.
