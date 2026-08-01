# Neighbor Market Phase 0 Demo Contract

## Status

Static clickable demonstration only.

Reference baseline: `89add370b78e5f7567a2acb44e53a45f07680372`

Issue: `#106`

## Purpose

The demo communicates one product idea:

1. current-apartment resident businesses and services first;
2. nearby-apartment resident businesses and services second;
3. general neighborhood businesses third.

It allows a viewer to click through resident, listing-owner, and operator scenarios without a backend.

## Supported flows

### Resident

- browse the resident-first home;
- search and filter synthetic listings;
- open a listing detail;
- favorite or unfavorite a listing;
- simulate order, reservation, quote, or consultation interest;
- inspect in-memory saved and request history.

### Listing owner

- switch to owner demo mode;
- register a storefront or non-storefront service;
- choose relationship type first;
- edit synthetic details;
- preview the listing;
- submit a review simulation;
- inspect draft, review, changes-requested, rejected, and approved states.

### Operator

- switch to operator demo mode;
- inspect a synthetic review queue;
- open a review detail;
- simulate approve, request-changes, or reject decisions;
- observe the corresponding owner state.

## What the demo does not prove

The demo does not implement or prove:

- authentication;
- resident identity or residence verification;
- business ownership verification;
- authorization;
- persistence;
- messaging;
- reservation, ordering, payment, settlement, or delivery;
- service quality;
- management-office endorsement;
- production security or privacy operations;
- real demand or willingness to pay.

## Data and privacy boundary

All identities, businesses, listings, relationships, prices, benefits, requests, and review decisions are synthetic.

Prohibited in the demo and repository:

- real resident names;
- building or unit numbers;
- resident rosters;
- verification files;
- personal phone numbers;
- management records;
- real inquiries;
- credentials, tokens, secrets, or database URLs.

## State model

All state is held in browser memory. Refreshing the page resets role selection, favorites, requests, search and filters, registration progress, owner review status, and operator decisions.

No `localStorage`, cookie, database, remote API, or backend is required.

## Product hierarchy

The demo must preserve the following default ordering in home and discovery views:

```text
방림명지로드힐 주민 운영
→ 이웃 단지 주민 운영
→ 우리 동네 가게
```

Distance, discounts, sponsorship, or payment cannot move a lower tier above a higher tier.

## Truthful demo language

Every simulated write action must tell the viewer that nothing was really sent, saved, verified, approved, paid, or delivered.

Operator mode must be presented as a simulation rather than authentication or authority.
