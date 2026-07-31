# Business 5 Community Priority Model

## 1. Product purpose

Business 5 is not primarily a nearby-shop directory.

Its purpose is to help apartment residents discover and support the economic activity of people who share or neighbor their residential community.

> 우리 아파트 주민이 하는 일을 먼저 발견하고, 서로 이용하며 돕는 생활경제 서비스.

The marketplace interaction may resemble familiar Korean commerce products, but the ranking purpose is different. Convenience supports community mutual aid; distance and advertising do not define the product.

## 2. Fixed three-tier priority

Every public business or service profile belongs to one of three relationship tiers.

### Tier 1 — 우리 단지 주민 운영

The business or service is operated by a verified resident of the user's current apartment complex.

Reference label:

- `방림명지로드힐 주민 운영`
- supporting phrase: `우리 단지 이웃`

Product treatment:

- first section on the home screen;
- strongest trust treatment;
- first ranking group in search and category results;
- eligible for the free resident basic listing policy;
- may include store-based, home-based, visiting, freelance, online and professional services;
- building and unit numbers remain private.

### Tier 2 — 이웃 단지 주민 운영

The business or service is operated by a verified resident of another nearby apartment complex.

Reference label:

- `이웃 단지 주민 운영`
- supporting phrase: `방림동 이웃 사업`

Product treatment:

- second section on the home screen;
- second ranking group in search and category results;
- visually distinct from both Tier 1 and general local businesses;
- apartment name may be displayed only when the operator consents and the product policy permits it;
- exact building and unit numbers remain private.

### Tier 3 — 우리 동네 가게

The business is a nearby general business without accepted resident-operation verification.

Reference label:

- `우리 동네 가게`
- optional supporting label: `입주민 혜택 제공`

Product treatment:

- third section on the home screen;
- third ranking group in search and category results;
- may participate by offering a clear resident benefit or filling an unmet local need;
- must never outrank Tier 1 or Tier 2 through payment alone.

## 3. Ranking contract

The default order is fixed:

```text
Tier 1: current-apartment resident businesses
→ Tier 2: nearby-apartment resident businesses
→ Tier 3: general neighborhood businesses
```

Within each tier, secondary ordering may use:

1. query and category relevance;
2. currently available or accepting reservations;
3. information freshness;
4. clear resident benefit;
5. distance or service area;
6. editorial rotation to prevent permanent lock-in.

Payment, sponsorship or advertising may not move a lower tier above a higher tier.

## 4. Search behavior

A search for `에어컨 청소` must present results in this order when matching profiles exist:

1. a 방림명지로드힐 resident-operated service;
2. a nearby-apartment resident-operated service;
3. a general neighborhood service.

The interface may offer a user-controlled alternative sort, but the default and recommended sort remain community priority.

`가까운 순` is a secondary optional sort and must not be the dominant default.

## 5. Home information architecture

The first three business sections are fixed:

1. `우리 아파트 주민의 가게와 서비스`
2. `이웃 아파트 주민의 가게와 서비스`
3. `우리 동네 가게`

Tier 1 must be the most prominent section. It cannot be reduced to a small filter or badge inside a mixed list.

The home screen should explain the purpose in one short line, not an editorial manifesto:

> 우리 이웃이 하는 일을 먼저 찾고, 함께 이용해요.

## 6. Profile scope

A listing does not require a physical storefront.

Valid examples include:

- restaurant, side-dish shop and cafe;
- cleaning, repair and air-conditioner service;
- tutoring, lessons and education;
- beauty, exercise and wellness service;
- tax, labor, legal-information and document support;
- design, development, online sales and freelance work;
- farm products, crafts and group purchasing;
- photography, pet care and visiting services.

The product term `가게와 서비스` should be used where `가게` alone would exclude residents without storefronts.

## 7. Verification semantics

Resident-operation verification proves only that the accepted product procedure linked the operator to the applicable residential community at a point in time.

It does not prove:

- service quality;
- legal compliance beyond the checked information;
- management-office endorsement;
- continued residence forever;
- customer satisfaction.

Private evidence and public profile data must remain separated.

Publicly forbidden:

- building and unit number;
- resident roster record;
- ID or management-fee documents;
- private phone number unless explicitly published for business use;
- reviewer identity and internal notes.

## 8. Monetization guardrail

The initial policy hypothesis is:

- Tier 1 basic listing: free;
- Tier 2: limited free or apartment-network partnership;
- Tier 3: participation tied to resident benefit or product need;
- optional paid tools may cover coupon management, analytics or profile operations;
- verification badges are never sold;
- sponsored placement is clearly marked and remains inside its relationship tier.

## 9. UI acceptance conditions

A reviewer must understand from the first screen that:

- the service prioritizes residents helping residents;
- 방림명지로드힐 resident businesses come first;
- nearby-apartment resident businesses come second;
- general nearby businesses come third;
- the interface is not merely another local advertising directory.

Any implementation that mixes all businesses into one visually equal list fails this product contract.
