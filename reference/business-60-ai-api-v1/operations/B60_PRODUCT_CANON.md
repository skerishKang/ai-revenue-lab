# B60 Product Canon

Status: **CANONICAL**  
Effective: **2026-08-25**  
Tracks: #704, #707  
Related UI direction: #702 / PR #703

This document defines the product direction that future sessions must preserve unless the owner explicitly changes it.

## 1. Product sentence

> B60 helps people quickly discover **what AI they can use for free right now**, what remains **continuously free**, and how to verify the actual conditions.

B60 is not primarily a provider directory. Provider names are supporting metadata; the user-visible benefit is primary.

## 2. Priority order

### Priority 1 — Timely opportunities

Examples:

- launch-week free access
- limited-time free model access
- temporary high/unlimited usage
- preview/beta free access
- GPU / inference promotions
- coding-agent/model promotions
- newly announced free routes

This is the strongest reason for repeat visits.

### Priority 2 — Durable free benefits

Examples:

- permanent free API tiers
- recurring monthly/daily allocations
- free model routers
- free developer playground access
- signup credits and other account-opening benefits

This is the durable reference layer that remains useful even when no major promotion is active. Signup credits may be plentiful, but volume alone must not push them into the hottest editorial positions.

### Priority 3 — Provider/API execution

Actual multi-provider execution, routing, API-key handling, metering, billing, or provider abstraction is **not the current B60 homepage mission**. It belongs to a separate provider/API product or execution layer.

Do not let Priority 3 pull B60 back into a generic provider catalog.

## 3. Core user question

The homepage should answer, within seconds:

> **“지금 내가 공짜로 쓸 수 있는 AI가 뭐지?”**

Secondary questions:

- 얼마를/얼마나 무료로 쓸 수 있는가?
- 언제까지인가?
- 계속 무료인가?
- 신규 가입자만 받을 수 있는가?
- 계정이나 결제 설정이 필요한가?
- API / Coding / Image / Video / GPU / Voice 중 무엇인가?
- 공식적으로 확인된 조건인가?
- 실제로 어디에서 사용하면 되는가?

## 4. Information hierarchy

User-facing hierarchy:

1. **혜택** — free amount, credit, period, usable scope
2. **urgency/status** — 지금 무료 / 종료 임박 / 상시 무료 / 확인 중
3. **what it is** — model/service/product
4. **provider** — company/platform
5. **conditions** — limits, signup/card/region/account requirements
6. **verification/source** — official page, announcement, source date
7. **action** — use/claim/read official source

Do not reverse this into `Provider → product → plan → tiny benefit` on the main discovery surface.

## 5. Canonical opportunity mechanics

The **mechanic** describes how the free benefit works. It is not an editorial ranking.

```text
TEMP_FREE_ACCESS = an existing/special model, API or service becomes $0/free for a limited period
SIGNUP_CREDIT    = one-time credit granted because a user creates/qualifies a new account
RECURRING_FREE   = daily/monthly allocation or credit that replenishes
ALWAYS_FREE      = ongoing free tier, free model, free router or other persistent no-charge access
```

Rules:

- A temporary free opening of an otherwise paid/special model is fundamentally different from a signup coupon.
- `SIGNUP_CREDIT` belongs in a separate signup-benefit surface by default. It may enter HOT only when unusually valuable or newsworthy.
- `RECURRING_FREE` and `ALWAYS_FREE` form the durable reference layer.
- Subtypes/categories such as API, Coding, Image, Video, GPU, Voice, Trial, Preview, Model, Credit may be separate tags; do not explode the mechanic enum to encode every category.

### Eligibility is a separate axis

Do not encode eligibility inside the mechanic.

```text
ANY_USER         = generally usable without being a new customer
NEW_USER_ONLY    = benefit is explicitly restricted to new users/accounts
ACCOUNT_REQUIRED = an account/login or service enrollment is required
UNKNOWN          = eligibility has not been verified sufficiently
```

Additional conditions such as payment-card requirement, paid subscription, region, workspace restriction, or balance setup should be explicit condition fields/copy rather than hidden inside `eligibility`.

## 6. Editorial role is independent from mechanic

`HOTTEST` and `JUST_DROPPED` are editorial roles, not offer types.

```text
HOTTEST      = the strongest current attention/value lead
JUST_DROPPED = the newest meaningful opportunity worth surfacing
STANDARD     = useful current item
REFERENCE    = durable reference item
```

Therefore:

- **hottest does not have to be newest**;
- a `TEMP_FREE_ACCESS` item may be HOTTEST today and STANDARD later;
- a newly announced item may be JUST_DROPPED even when another older opportunity remains HOTTEST;
- signup-credit volume must not automatically displace stronger temporary free-access news.

## 7. Canonical public sections

- **지금 가장 핫함**: strongest current editorial lead
- **방금 뜬 무료**: newly announced meaningful opportunities
- **지금 무료**: other active timely opportunities
- **종료 임박**: only when the expiry is authoritative and within the configured urgency window
- **가입 혜택**: signup credits/new-user-only benefits, visually separated from temporary free openings
- **상시 무료**: ongoing/replenishing free tiers/models/credits
- **최근 확인**: freshness and verification history
- **확인 중**: useful claims that have not yet met publication/expiry certainty

Category filters such as API, Coding, Image, Video, GPU, Voice are secondary navigation, not the core product identity.

## 8. Manual curation is first-class

The owner may discover items manually on X, blogs, communities, launch posts, GitHub, newsletters, or official pages and send only one or more links.

That is a normal production workflow, not a temporary workaround.

Automation may be added later if volume requires it, but automation is **not** a prerequisite for product value and must not become the development priority by default.

## 9. Truth boundary

- Social posts can be discovery leads.
- An **official brand/model social announcement** is authoritative evidence for what that brand explicitly announces and should be recorded separately from official web/docs evidence.
- Official/primary web/docs should still be used to verify stable product/model/access facts when available.
- A community/social-only claim can be recorded as pending rather than silently upgraded to fact.
- `종료 임박` / countdown requires a verified authoritative expiry date and must respect the urgency window; a future date alone is not enough.
- Do not invent exact limits, dates, credit values, signup conditions, or model availability.
- Keep provenance and observed/verified dates.

Canonical verification examples:

```text
VERIFIED_OFFICIAL_WEB
VERIFIED_OFFICIAL_SOCIAL
PENDING_VERIFICATION
```

## 10. Relationship to existing technical layers

Existing detail, compare, watchlist, source, snapshot, review/promotion, and NEW_SIGNAL mechanisms remain useful supporting infrastructure.

Their role is to make the editorial surface trustworthy; they are not the primary visual identity.

A newly discovered opportunity may enter the existing human-reviewed NEW_SIGNAL path when appropriate. `NEW_SIGNAL` means “a new publishable opportunity/record,” not “we must expand the provider catalog.”

## 11. Non-goals for current B60

Unless explicitly requested, do not prioritize:

- mass provider-directory expansion for its own sake
- API proxy/provider execution
- API-key vaults
- billing
- auth/account systems
- complex automatic crawlers
- autonomous publishing
- large backend rebuilds

## 12. Change control

This file is the product-direction source of truth.

If a future request conflicts with it:

1. do not silently reinterpret the canon;
2. identify the conflict;
3. if the owner explicitly changes direction, update this file in the same workstream;
4. preserve the previous rationale in Git history rather than relying on chat memory.
