# World Feed Thin Benchmark Specification

- Status: Research approved; implementation deferred
- Date: 2026-07-20
- Related issue: #14

## 1. Purpose

This benchmark tests the central World Feed hypothesis before any crawler, feed application, recommendation system, or global infrastructure is built.

> The same verified local facts can be transformed into materially different and useful personal world editions without changing the facts themselves.

The benchmark measures four things:

1. whether free AI can extract source-faithful structured records;
2. whether it can detect duplicate, conflicting, superseded, or withdrawn information;
3. whether it can produce different useful editions for different people;
4. whether the production economics justify a larger information system.

## 2. Benchmark boundary

The benchmark uses a retained, manually assembled corpus. It does not browse or crawl the live web during the default test.

Initial scope:

- three countries: Vietnam, Ghana, and Japan;
- two low-risk content families per country;
- six to ten source records per country;
- Korean and English output;
- three synthetic user profiles;
- one daily-edition format;
- free-model-first generation;
- human review and deterministic validation.

Country selection is intended to expose linguistic and geographic diversity, not to rank or compare the countries.

## 3. Low-risk content families

### A. Places and cultural experiences

Examples:

- parks, trails, beaches, heritage spaces, museums, markets, and public cultural facilities;
- official openings, renovations, seasonal programs, or new visitor experiences;
- public tourism and cultural programs.

### B. Official events and entertainment

Examples:

- festivals, exhibitions, performances, film festivals, album releases, official broadcast schedules, and public sports schedules or results;
- only information published by organizers, venues, labels, broadcasters, leagues, or public institutions.

## 4. Excluded content

The first benchmark excludes:

- politics and elections;
- crime, allegations, and court disputes;
- war, disaster, death, and emergency reporting;
- medical, health, legal, and financial guidance;
- celebrity private life and anonymous rumors;
- content concerning minors beyond clearly official public-event facts;
- transfer, injury, relationship, or cancellation rumors;
- anonymous social posts and unverified community claims;
- copyrighted full-article republication;
- copied images without explicit reuse rights.

## 5. Source corpus

The benchmark corpus contains source records and retained text extracts sufficient to reproduce the test without live network access.

Allowed source tiers:

### Tier A — primary official

- government and local-government sites;
- tourism authorities;
- cultural institutions, universities, museums, and venues;
- official event and festival sites;
- company, label, broadcaster, league, and team newsrooms;
- official public data and RSS records.

### Tier B — verified official social record

Used when an organization publishes a relevant update only through a verified official account. The retained record must include the account identity, post date, content, and original link.

### Tier C — reputable secondary discovery

Used only to locate a primary record. It does not independently authorize publication when a primary source should reasonably exist.

Anonymous social accounts, fan pages, aggregators without provenance, and copied articles are excluded.

## 6. Source record schema

Every retained source record contains:

- `source_record_id`;
- country and locality;
- original language;
- source tier;
- publisher name and organization type;
- canonical URL or retained reference;
- publication timestamp;
- access timestamp;
- title and relevant text extract;
- named entities;
- event or validity dates when present;
- category;
- media-rights state;
- relationship to other source records;
- checksum or other duplicate aid;
- synthetic-data flag;
- reviewer notes.

Credentials, private social data, paywalled full text, and unnecessary personal information are prohibited.

## 7. Canonical fact and event records

The AI converts source records into structured fact and event objects.

Required event fields:

- `event_id`;
- localized and original titles;
- country, locality, and venue where supported;
- category;
- start and end dates where supported;
- organizer or publisher;
- current status;
- claim list;
- supporting source-record identifiers;
- conflicting source-record identifiers;
- last-confirmed timestamp;
- update history;
- language and translation metadata;
- publication eligibility;
- uncertainty notes.

Each claim records:

- claim identifier;
- normalized proposition;
- value and units when applicable;
- supporting segment identifiers;
- direct statement or interpretation status;
- first-seen and last-confirmed times;
- conflict state.

## 8. Verification states

### Single-source confirmed statement

One authorized primary source clearly states the fact. The edition must describe it as an official announcement, not as independently established reality.

### Multi-source confirmed

Two or more organizationally independent primary sources support the same fact.

Multiple pages or accounts controlled by one organization do not count as independent sources.

### Conflicting

Sources disagree on date, place, status, name, price, or another material fact. Automatic publication is blocked or the conflict is explicitly displayed in a research output.

### Superseded

A newer official record replaces an older value. The event retains history but the current edition uses the newer confirmed value.

### Withdrawn or cancelled

An authorized source explicitly withdraws, closes, postpones, or cancels the prior information. The event is updated rather than duplicated.

### Unresolved

The available material is insufficient or ambiguous. The record remains unpublished or clearly marked as unresolved in benchmark analysis.

## 9. Deduplication rules

Two source records may describe one event when they share a strong combination of:

- organizer;
- locality or venue;
- event name or translated equivalent;
- overlapping dates;
- named participants or program identity;
- canonical link relationships.

The system must not merge merely because two events share generic words such as festival, concert, market, or exhibition.

Benchmark cases must include:

- exact duplicate repost;
- translated duplicate;
- organizer update to the same event;
- two different events with similar titles;
- cancellation or date-change record;
- one source incorrectly associated with the wrong locality.

## 10. Synthetic user profiles

### Profile A — Quiet regional traveler

Preferences:

- small cities and local neighborhoods;
- nature, morning culture, markets, and food context;
- dislikes crowds and globally famous attractions;
- wants practical but calm explanations;
- Korean output.

### Profile B — Emerging music and film follower

Preferences:

- local film festivals, regional cinema, new music releases, and official artist activity;
- values original names and context;
- wants more detail and fewer tourism items;
- English output.

### Profile C — Family cultural explorer

Preferences:

- public cultural programs, museums, parks, performances, and clearly family-suitable official events;
- requires uncertainty and age-suitability claims to remain conservative;
- prefers short Korean explanations and explicit dates.

Profiles contain no sensitive traits and do not represent real people.

## 11. Personal edition output

Every profile receives an edition from the same canonical event pool.

Required fields:

1. edition title and date;
2. short editorial opening;
3. three to seven selected items;
4. explanation of why each item matters to this profile;
5. original place, person, work, or event names where useful;
6. source and last-confirmed indicators;
7. conflict or uncertainty note when applicable;
8. one discovery item adjacent to, but not identical with, known preferences;
9. one feedback question for the next edition.

The edition must distinguish:

- shared factual layer;
- profile-specific selection;
- profile-specific explanation;
- AI interpretation.

Facts may not change across profiles. Selection, order, depth, tone, and meaning may change.

## 12. Material-personalization test

A blind reviewer receives two or three profile editions without profile labels.

The benchmark passes this component when the reviewer can correctly match at least 80% of editions to their intended profiles based on substantive differences rather than superficial wording.

Substantive differences include:

- different selected events;
- different prioritization;
- different contextual explanation;
- different practical detail;
- different discovery item;
- different depth and terminology.

Changing only the greeting, adjectives, or sentence length is a failure.

## 13. Model tasks

### Task 1 — source extraction

Convert retained source segments into structured claims without adding facts.

### Task 2 — event resolution

Group duplicates, preserve updates, identify conflicts, and create canonical event records.

### Task 3 — translation

Produce Korean or English structured translations while retaining original names and ambiguity.

### Task 4 — publication eligibility

Apply low-risk scope and source-state rules.

### Task 5 — personal selection and editing

Create profile-specific editions from eligible canonical records.

### Task 6 — adversarial review

Detect unsupported additions, incorrect merges, stale values, and profile-based factual distortion.

Each task is evaluated independently. One model/provider may be approved for extraction but rejected for event resolution or final editing.

## 14. Required fixtures

The corpus must include at least:

- one clear official event per country;
- one place or program update per country;
- one duplicate record;
- one translated duplicate;
- one date correction;
- one cancellation or withdrawal;
- one conflicting source pair;
- one similar-title nonduplicate pair;
- one record outside allowed categories;
- one record with insufficient evidence;
- one record with a name transliteration challenge.

Synthetic fixtures must be unmistakably marked. Real retained records require a source reference and limited necessary extracts.

## 15. Deterministic validation

Before an output can be accepted:

- all cited source-record identifiers must exist;
- all event identifiers must resolve;
- dates and places must match canonical records;
- a profile edition cannot introduce new named entities or amounts absent from eligible records;
- excluded categories cannot appear;
- withdrawn events cannot be described as upcoming;
- conflicts cannot be silently resolved by model preference;
- generated HTML or scripts are prohibited;
- source text cannot be reproduced beyond necessary short factual use.

## 16. Quality metrics

Measure per task and provider/model:

- schema compliance;
- unsupported-claim rate;
- claim omission rate;
- date and locality accuracy;
- duplicate precision and recall;
- conflict detection rate;
- supersession accuracy;
- translation faithfulness;
- publication-scope compliance;
- blind profile-match rate;
- human correction minutes per accepted item;
- provider failure and timeout rate.

Any invented material date, place, cancellation status, or person association is critical.

## 17. Production and economic metrics

Record:

- free calls by provider and model;
- paid calls and reason;
- source records processed;
- canonical events created;
- eligible items produced;
- editions generated;
- human minutes;
- cash infrastructure cost;
- estimated cost per accepted event and edition;
- search-impression or click potential where measurable;
- subscription, alert, affiliate, promoted-listing, or B2B intent from test users.

## 18. First economic hypotheses

The benchmark does not need revenue, but it must prepare measurable offers.

Candidate signals:

- a user follows a country, city, artist, work, or category and requests continued editions;
- a user pays for a weekly personal world edition or faster official alert;
- a user clicks an official ticket, accommodation, tour, or commerce link;
- a small organization expresses interest in a localized white-label feed;
- a regional promoter pays for a clearly labeled verified listing.

The first implementation decision should choose only one primary economic signal.

## 19. Approval thresholds

A provider/model combination may be approved for a task when:

- structured-output success is at least 95%;
- unsupported material claims are zero in the acceptance set;
- date and locality accuracy are at least 98%;
- conflict and withdrawal cases are never silently published;
- blind profile matching is at least 80%;
- average human correction is economically acceptable and recorded;
- free inference performs at least 90% of benchmark calls.

Thresholds may be revised only through an evidence-backed decision.

## 20. Implementation gate

No live collector or public feed should be built until:

- this corpus is complete;
- at least one free model/provider passes a limited role;
- canonical record and update-state rules are validated;
- three personal editions pass blind matching;
- one economic signal is selected;
- expected human correction time is acceptable.

The first authorized implementation, when approved, should process a retained corpus before any live-source automation.
