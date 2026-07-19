# Living Travel Product Contract

- Status: Design approved for research; implementation deferred
- Date: 2026-07-20
- Related issue: #13

## 1. Product definition

Living Travel is a recurring personal travel publication. It does not return a one-time itinerary or generic chatbot answer. A reader receives a polished edition, reacts to it, and receives a materially adapted next edition at a deliberate time.

```text
travel interest and constraints
→ curated source packet
→ personal travel edition
→ reader reaction
→ updated preference state
→ materially adapted next-morning edition
```

The product tests whether AI can make one-to-one travel publishing economically viable.

## 2. First experiment

The first experiment is a **seven-morning destination season** for one real destination.

Initial candidate destination: Da Nang, Vietnam.

The destination may be replaced before implementation when source accessibility or pilot-user demand favors another place. The product contract does not depend on Da Nang-specific facts.

### Target first reader

An adult independent traveler who:

- is considering or preparing for one destination;
- dislikes generic top-ten lists;
- can articulate changing interests after reading;
- values neighborhood atmosphere, food, culture, or quiet exploration;
- is willing to read one compact edition each morning.

### Initial travel stage

Pre-trip inspiration and preference discovery.

The first pilot does not provide emergency navigation, immigration advice, safety guarantees, live transport status, or time-critical booking instructions.

## 3. Exact input

The first edition accepts:

- destination;
- approximate travel month or season;
- trip duration range;
- solo, couple, family, or group context;
- budget tendency;
- mobility or pace preference;
- initial interests;
- explicit exclusions;
- preferred edition tone and length;
- optional user-supplied memories or reasons for interest.

After each edition, the reader may provide:

- continue in this direction;
- make it more practical;
- make it more atmospheric;
- show more food, culture, nature, neighborhoods, or events;
- reduce famous attractions;
- reduce crowds, cost, walking, nightlife, or complexity;
- go deeper on one section;
- free-form instruction.

The system must not infer medical conditions, disabilities, financial capacity, family relationships, or risk tolerance beyond what the reader explicitly supplies.

## 4. Source packet

Every edition is grounded in an approved source packet rather than unrestricted model memory.

A source record contains:

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

Initial source priorities:

1. local or national tourism authorities;
2. local government and cultural institutions;
3. official attraction, market, venue, event, and transport sources;
4. verified official business pages for operating information;
5. reputable secondary sources used only when primary confirmation is unavailable and the limitation is shown.

User-generated ratings and anonymous recommendations are not treated as verified factual sources. They may later be analyzed as subjective signals with explicit labeling.

## 5. Output contract

Each edition is a polished mobile-readable publication containing:

1. edition title;
2. destination, date, and edition number;
3. a short opening that connects to the reader's stated interest;
4. two to four editorial sections;
5. source-backed place, activity, food, event, or cultural material;
6. a practical note only when its validity date is clear;
7. a continuity note describing how prior feedback changed this edition;
8. source and freshness indicators;
9. one question or choice for the next edition.

Target length:

- approximately 700 to 1,300 Korean words; or
- equivalent English length.

The output must not be a list of links, a raw itinerary table, a copied article, or a chat transcript.

## 6. Adaptation rule

A next edition is materially adapted only when at least one of the following changes:

- selected places or topics;
- geographic focus within the destination;
- practical versus narrative emphasis;
- route or sequence;
- depth of one subject;
- crowd, budget, pace, or companionship constraints;
- time-of-day focus;
- excluded category;
- editorial tone or length.

Changing adjectives or merely acknowledging feedback does not qualify.

The edition stores an `applied_feedback` record with:

- feedback identifier;
- requested change;
- actual editorial action;
- affected sections;
- evidence that the change is visible;
- unfulfilled request and reason when applicable.

## 7. Three-edition design demonstration

The following is a structural prototype. Place names and operational details are placeholders until grounded source records are supplied.

### Edition 1 — Broad destination discovery

Theme: a balanced introduction to the destination beyond a generic checklist.

Sections:

- morning atmosphere and one representative local area;
- one cultural or natural experience;
- one food context;
- a choice between deeper neighborhood life, food, nature, or evening culture.

Reader reaction:

> Famous attractions are less interesting. I want neighborhood restaurants and ordinary morning life.

### Edition 2 — Neighborhood food and morning life

Material changes:

- famous attractions removed;
- geographic focus narrowed to residential or market areas;
- food is explained through morning routines rather than restaurant rankings;
- practical notes focus on opening periods and solo ordering where sourced.

Reader reaction:

> I travel alone. I prefer quiet places and do not want crowded markets or complicated ordering.

### Edition 3 — Quiet solo-friendly morning route

Material changes:

- crowded or high-friction locations excluded;
- route favors short transitions and calmer periods;
- each stop includes a solo-entry or ordering note only when sourced;
- one alternative is supplied for weather or crowd changes;
- the continuity note explicitly states which prior suggestions were removed.

The three editions must remain recognizably part of one continuing publication while offering substantively different content.

## 8. Freshness and verification policy

Travel information decays at different speeds.

### Slow-changing

- geography;
- cultural context;
- historical background;
- general neighborhood character.

These records may have longer review intervals.

### Medium-changing

- regular operating hours;
- ticket structure;
- recurring programs;
- transport routes;
- seasonal access.

These require dated sources and rechecking before a pilot edition.

### Fast-changing

- temporary events;
- closures;
- weather-dependent activities;
- live transport disruption;
- current prices;
- reservation availability.

The first pilot either excludes these or displays a prominent last-confirmed timestamp and directs the reader to the official source.

The service must say what was confirmed, when it was confirmed, and what remains uncertain. It must not claim that a future activity will certainly occur.

## 9. Delivery model

- reader input and feedback may be submitted at any time;
- the next edition is normally delivered the following morning;
- generation may occur within minutes, but deliberate delivery creates continuity and expectation;
- manual generation and delivery are acceptable during the pilot;
- urgent in-trip requests are outside the first experiment.

## 10. Revenue hypothesis

> A traveler will pay for a destination publication that becomes visibly more relevant each morning, even though generic AI itinerary tools are available for free.

Initial offer:

- one sample edition free;
- seven-morning destination season: KRW 5,900;
- manual payment acceptable;
- optional official booking or commerce links may be measured, but affiliate revenue is not required for first validation.

The user is paying for recurrence, editorial packaging, memory, adaptation, and source freshness—not access to an AI model.

## 11. Success metrics

Critical:

- at least one external user pays;
- at least two users complete three or more editions;
- each continuing user gives feedback at least twice;
- an independent reviewer can identify the requested adaptation without seeing the feedback text;
- at least 80% of editions require no substantial human rewrite;
- at least 90% of generation calls use free inference.

Supporting:

- five sample users from ten or more qualified invitations;
- two paid conversions;
- average human correction below seven minutes per edition;
- at least one official-link or booking-intent action;
- at least one request to continue or switch to another destination.

## 12. Failure conditions

- readers prefer one immediate itinerary over recurring editions;
- adaptations are perceived as superficial;
- source collection and correction time make one-to-one production uneconomic;
- operational facts become stale too quickly;
- no payment follows 20 qualified invitations and sample exposure;
- the service repeatedly recommends places that violate explicit constraints;
- users do not return after the first edition.

Failure must be classified as demand, packaging, freshness, source, personalization, pricing, or distribution failure.

## 13. Safety and privacy boundaries

The first experiment excludes:

- medical or accessibility guarantees;
- legal, visa, immigration, or customs advice;
- emergency and personal-safety guarantees;
- travel to active conflict or severe-disaster areas;
- personalized risk judgments based on sensitive identity inference;
- unverified private residences or intrusive local-life recommendations;
- hidden sponsorship;
- collection of precise live location unless a later product decision explicitly authorizes it.

The reader may delete supplied preferences, feedback, and editions.

## 14. Relationship to Personal Edition

Living Travel may reuse these concepts:

- edition sequence;
- structured feedback;
- continuity note;
- applied-feedback evidence;
- deliberate delivery;
- experiment accounting.

It must not share implementation code merely because the concepts are similar. Shared extraction is considered only after both products have working tested implementations.

## 15. Implementation gate

Implementation remains deferred until:

- Personal Edition proves or disproves that readers value feedback-responsive recurring editions;
- a destination source packet is assembled;
- freshness and source-display requirements are accepted;
- the three-edition prototype is reviewed;
- the pilot user and economic signal are confirmed.
