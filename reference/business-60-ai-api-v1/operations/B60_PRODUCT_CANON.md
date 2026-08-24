# B60 Product Canon

Status: **CANONICAL**  
Effective: **2026-08-25**  
Tracks: #704  
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
- free signup credits
- temporary high/unlimited usage
- preview/beta free access
- GPU / inference promotions
- coding-agent/model promotions
- newly announced free routes

This is the strongest reason for repeat visits.

### Priority 2 — Always-free access

Examples:

- permanent free API tiers
- recurring monthly/daily credits
- free model routers
- free developer playground access
- recurring inference allocations

This is the durable reference layer that remains useful even when no major promotion is active.

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
- API / Coding / Image / Video / GPU / Voice 중 무엇인가?
- 공식적으로 확인된 조건인가?
- 실제로 어디에서 사용하면 되는가?

## 4. Information hierarchy

User-facing hierarchy:

1. **혜택** — free amount, credit, period, usable scope
2. **urgency/status** — 지금 무료 / 종료 임박 / 상시 무료 / 확인 중
3. **what it is** — model/service/product
4. **provider** — company/platform
5. **conditions** — limits, signup/card/region requirements
6. **verification/source** — official page, announcement, source date
7. **action** — use/claim/read official source

Do not reverse this into `Provider → product → plan → tiny benefit` on the main discovery surface.

## 5. Canonical public sections

- **지금 무료**: time-sensitive or currently attractive opportunities
- **종료 임박**: only when the expiry is verified from authoritative evidence
- **상시 무료**: ongoing free tiers/models/recurring credits
- **최근 확인**: freshness and verification history
- **확인 중**: useful claims that have not yet met publication/expiry certainty

Category filters such as API, Coding, Image, Video, GPU, Voice are secondary navigation, not the core product identity.

## 6. Manual curation is first-class

The owner may discover items manually on X, blogs, communities, launch posts, GitHub, newsletters, or official pages and send only one or more links.

That is a normal production workflow, not a temporary workaround.

Automation may be added later if volume requires it, but automation is **not** a prerequisite for product value and must not become the development priority by default.

## 7. Truth boundary

- Social posts can be discovery leads.
- Official/primary sources should be used to verify material claims when available.
- A social-only claim can be recorded as pending rather than silently upgraded to fact.
- `종료 임박` / countdown requires a verified expiry date.
- Do not invent exact limits, dates, credit values, signup conditions, or model availability.
- Keep provenance and observed/verified dates.

## 8. Relationship to existing technical layers

Existing detail, compare, watchlist, source, snapshot, review/promotion, and NEW_SIGNAL mechanisms remain useful supporting infrastructure.

Their role is to make the editorial surface trustworthy; they are not the primary visual identity.

A newly discovered opportunity may enter the existing human-reviewed NEW_SIGNAL path when appropriate. `NEW_SIGNAL` means “a new publishable opportunity/record,” not “we must expand the provider catalog.”

## 9. Non-goals for current B60

Unless explicitly requested, do not prioritize:

- mass provider-directory expansion for its own sake
- API proxy/provider execution
- API-key vaults
- billing
- auth/account systems
- complex automatic crawlers
- autonomous publishing
- large backend rebuilds

## 10. Change control

This file is the product-direction source of truth.

If a future request conflicts with it:

1. do not silently reinterpret the canon;
2. identify the conflict;
3. if the owner explicitly changes direction, update this file in the same workstream;
4. preserve the previous rationale in Git history rather than relying on chat memory.
