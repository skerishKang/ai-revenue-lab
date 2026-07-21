# Living Travel Product Contract

- Status: **Approved for Phase 1 implementation**
- Date: 2026-07-20
- Related issue: #32
- Base SHA: 2afaa049614337c8d61a9ec7b34dd02c89f4ee78

## 1. Product definition

Living Travel is a recurring personal travel publication. A reader receives a polished edition, reacts to it, and receives a materially adapted next edition at a deliberate time.

```
travel interest and constraints
→ curated source packet
→ personal travel edition
→ reader reaction
→ updated preference state
→ materially adapted next-morning edition
```

The product tests whether AI can make one-to-one travel publishing economically viable.

## 2. First experiment

The first experiment is a **Busan 2-night domestic solo trip**.

### Target reader

A Korean solo traveler planning a two-night domestic trip who:

- is considering or preparing for a short destination trip;
- dislikes generic top-ten lists;
- can articulate changing interests after reading;
- values neighborhood atmosphere, food, culture, or quiet exploration;
- is willing to read one compact edition.

### Initial travel stage

Pre-trip or early-trip inspiration and planning.

The first pilot does not provide emergency navigation, immigration advice, safety guarantees, live transport status, or time-critical booking instructions.

## 3. Exact input

The first edition accepts:

- destination;
- trip duration;
- solo context;
- budget tendency;
- mobility or pace preference;
- initial interests;
- explicit exclusions;
- preferred edition tone and length.

After each edition, the reader may provide:

- continue in this direction;
- make it more practical;
- more local food;
- quieter places;
- slower pace;
- less walking;
- lower budget;
- more practical detail;
- free-form instruction.

## 4. Source packet

Every edition is grounded in an approved source packet rather than unrestricted model memory.

### Source record

- source identifier;
- source URL or retained reference;
- publisher and source type;
- original language;
- publication or update date;
- access date;
- destination and locality;
- category;
- extracted factual claims;
- operating dates or validity period when applicable;
- single-source, multi-source, conflicting, superseded, or withdrawn state;
- confidence and review notes.

## 5. Output contract

Each edition is a polished publication containing:

1. publication and edition title;
2. destination and trip frame;
3. editorial opening;
4. two night/day route sections;
5. food or neighborhood recommendations;
6. quieter or lower-effort alternatives;
7. practical notes;
8. source/provenance references;
9. information class and freshness/verification metadata for each operational item;
10. applied feedback on later editions;
11. next-edition feedback prompt.

## 6. Current-information policy

Every generated travel item must be classified as one of:

1. **inspiration** — subjective or thematic material that does not claim current operations;
2. **stable_reference** — a broadly stable place or geography statement with provenance;
3. **time_sensitive** — opening hours, price, booking, transit, weather, event, closure, or other changing operational advice.

For **time_sensitive** items:

- `as_of_date` required;
- source/provenance reference required;
- confidence or verification state required;
- `verify_before_use=true` unless an approved current source is present.

Synthetic fixtures must not pretend to be current.

## 7. Adaptation rule

A next edition is materially adapted only when at least one of the following changes:

- selected places or topics;
- geographic focus within the destination;
- practical versus narrative emphasis;
- route or sequence;
- depth of one subject;
- crowd, budget, pace, or companionship constraints;
- excluded category;
- editorial tone or length.

Changing adjectives or merely acknowledging feedback does not qualify.

The edition stores an `applied_feedback` record with:

- feedback identifier;
- requested change;
- actual editorial action;
- affected sections;
- evidence that the change is visible.

## 8. Revenue hypothesis

> A traveler will pay for a destination publication that becomes visibly more relevant, even though generic AI itinerary tools are available for free.

Initial offer:

- one free sample edition;
- three adapted editions: KRW 4,900;
- payment integration is out of scope; only the contract and privacy-safe evidence structure are required.

The user is paying for recurrence, editorial packaging, memory, adaptation, and source freshness — not access to an AI model.

## 9. Success metrics

Critical:

- at least one external user pays;
- at least two users complete three editions;
- each continuing user gives feedback at least twice;
- an independent reviewer can identify the requested adaptation without seeing the feedback text.

## 10. Failure conditions

- readers prefer one immediate itinerary over recurring editions;
- adaptations are perceived as superficial;
- source collection and correction time make one-to-one production uneconomic;
- operational facts become stale too quickly;
- users do not return after the first edition.

## 11. Safety and privacy boundaries

The first experiment excludes:

- medical or accessibility guarantees;
- legal, visa, immigration, or customs advice;
- emergency and personal-safety guarantees;
- collection of precise live location.

The reader may delete supplied preferences, feedback, and editions.

## 12. Relationship to Personal Edition

Living Travel is a conceptual sibling of Personal Edition. It must not share implementation code merely because the concepts are similar. Shared extraction is considered only after both products have working tested implementations.

Structural patterns may be studied, but all code is independently designed and maintained within `apps/living-travel/`.

## 13. Non-goals (Phase 1)

- booking, maps, navigation, weather, payment, affiliate integration;
- email, OAuth, or public sharing;
- UI beyond health/smoke boundary;
- live web research or provider call;
- shared package extraction.
