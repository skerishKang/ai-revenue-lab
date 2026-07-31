# Business 5 Product Decision — 우리단지 이웃가게

## 1. Decision

- Business number proposal: **5**
- Korean name: **우리단지 이웃가게**
- English name: **Neighbor Market**
- Stable slug: `neighbor-market`
- Reference apartment: `방림명지로드힐`
- Proposed future workspace: `apps/neighbor-market/**`
- Initial lifecycle: `concept` → approved static reference 후 `incubation`

## 2. Core problem

아파트 주민 중 자영업자, 프리랜서, 과외 교사, 전문직, 온라인 판매자와 방문 서비스 제공자가 많아도 같은 단지 주민이 그 사실을 알기 어렵다.

현재 수단의 한계:

- 엘리베이터 전단은 검색과 갱신이 어렵다.
- 단체 채팅방 홍보는 반복 노출과 갈등을 만든다.
- 지도·배달 플랫폼은 주민 관계를 알 수 없다.
- 관리사무소 게시판은 가게가 없는 프리랜서와 서비스 제공자를 포괄하기 어렵다.
- 광고비를 많이 낸 일반 업체가 실제 이웃보다 더 잘 보일 수 있다.

## 3. Product promise

> 우리 아파트 주민이 하는 일을 먼저 발견하고, 서로 이용하며 돕는 생활경제 서비스.

The product borrows familiar commerce discovery patterns for usability, but its ranking principle is community relationship rather than distance or advertising.

## 4. Fixed priority

```text
1. 방림명지로드힐 주민 운영
2. 이웃 단지 주민 운영
3. 우리 동네 가게
```

This order applies to home sections, search, category results and profile emphasis.

No paid placement may move Tier 2 or Tier 3 above Tier 1.

See `COMMUNITY_PRIORITY_MODEL.md` for the full contract.

## 5. Target users

### Residents looking for help

- need food, repair, tutoring, beauty, pet care or professional support;
- prefer to support a neighbor when the service is suitable;
- need clear information without exposure of private residence details.

### Resident operators

- storefront business owners;
- home or visiting service providers;
- tutors and class operators;
- accountants, designers, developers and other freelancers;
- online sellers;
- farm-product, craft and group-purchase operators.

### Nearby-apartment resident operators

- fill service categories not available inside the current apartment;
- remain below current-apartment residents in default ranking.

### General local businesses

- may participate when they fill an unmet need or provide a clear resident benefit;
- are not represented as resident-operated.

## 6. Core loops

### Resident discovery

필요한 일 검색
→ 우리 단지 주민 결과 먼저 확인
→ 이웃 단지 주민 결과 확인
→ 일반 동네 가게 확인
→ 관계·가격·가능 시간·혜택 비교
→ 외부 문의 또는 예약

### Operator registration

주민 관계 선택
→ 공개 프로필 작성
→ 비공개 확인자료 별도 제출
→ 운영자 검토
→ 관계 등급에 맞는 영역에 게시
→ 정보와 혜택 갱신

## 7. MVP boundary

The first MVP is a clickable static reference.

Included:

- 방림명지로드힐 context;
- resident-mutual-aid lead copy;
- search and categories;
- separate Tier 1, Tier 2 and Tier 3 sections;
- grouped resident-priority search;
- profile detail;
- relationship-first registration preview;
- resident benefits;
- mobile navigation;
- synthetic photography and fixtures;
- privacy and verification disclosures.

Excluded:

- real login or resident verification;
- database persistence;
- real business participation;
- ordering, messaging, phone connection or payments;
- ratings and reviews;
- map and live distance calculation;
- advertising marketplace;
- AI recommendations;
- management-office endorsement.

## 8. Trust boundary

Resident-operation verification means only that an accepted product procedure linked the operator to the applicable residential community at a point in time.

It does not guarantee service quality or reveal:

- building or unit number;
- resident roster records;
- identity or management-fee documents;
- private contact details;
- reviewer identity and internal notes.

## 9. Monetization hypotheses

Consider only after product validation:

- Tier 1 basic listing free;
- optional profile-operation, coupon or analytics tools;
- Tier 2 limited free or apartment-network partnership;
- Tier 3 participation linked to resident benefit or unmet need;
- clearly marked sponsorship inside the same relationship tier.

Never sell verification badges or cross-tier ranking.

## 10. Success criteria for the reference

A reviewer should immediately understand:

- this is about residents supporting residents;
- 방림명지로드힐 resident work comes first;
- nearby-apartment resident work comes second;
- general local businesses come third;
- storefronts and personal services are both supported;
- private residence information is not exposed.
