# B02 — Living Travel Visual Direction

Status: `DIRECTION_FROZEN_FOR_PREIMPLEMENTATION_PROGRAM`

New-standard verdict:

```text
REDESIGN
```

Reason:

```text
reference / requirement fidelity failure
+ perceptual collision with B06/B07 dark signal family
+ current live surface does not visibly deliver the required place imagery
```

Preserve the useful workflow and state contracts. Redesign the product-facing art/material layer.

```text
OWNER_UI_APPROVED=false
```

remains unchanged.

---

## 1. Authority and fresh evidence

Creation baseline:

```text
origin/main = a631122888d30c5a8a62f4b27e192967da331898
```

Canonical live surface audited:

```text
https://ai-revenue-living-travel.pages.dev/
```

Relevant authority:

```text
Issue #457 — owner-rejected UI; cinematic travel art-direction reset
PR #460 — V2 PLACE → ROUTE → DAY → ADAPT implementation
```

Fresh Batch A Chromium evidence:

```text
run      = 31421541852
artifact = 9075565375
sha256   = cacecf7ab056a7c3478f3cd078bf8edb080780a3e8ab7afbb960fd6bee58f0e2
viewports = 1440×1100, 390×844
```

Observed:

- HTTP 200;
- overflow 0;
- console/page errors 0;
- visible broken images 0;
- visible `<img>` count on audited root/Guide: **0**;
- root first impression is a dark teal/black field, giant condensed place title and CSS route/orbit lines;
- desktop root H1 `144px / 118.08px`; mobile `78px / 63.96px`;
- current root visually collides with the dark signal/diagram family used by B06 and B07.

Technical health does not resolve the visual fidelity failure.

---

## 2. Product job

Living Travel interprets one traveler's preferences into a personally composed journey, carries that interpretation through human editorial review, publishes a travel Edition, then visibly adapts the next Edition from feedback.

It is not primarily:

- a map utility;
- a booking/search engine;
- a generic itinerary table;
- a destination magazine for everyone;
- a dark route dashboard.

The emotional result should be:

> This is not a list of places. This is **my trip**, interpreted and composed for me.

---

## 3. Core transformation — preserve

```text
PLACE → ROUTE → DAY → ADAPT
```

This remains a strong product grammar and should be preserved.

- `PLACE` — destination, neighborhood texture, weather/light and local character are immediately felt;
- `ROUTE` — preferences become a spatial sequence;
- `DAY` — route becomes an authored daily travel rhythm;
- `ADAPT` — feedback visibly changes pace, density, local depth and dwell time.

The redesign should strengthen this grammar, not replace it.

---

## 4. Visual world — Cinematic Personal Journey

Reserve B02's territory as:

```text
place-first
cinematic but useful
sunlight / weather / street texture
route and time layered over real atmosphere
movement through neighborhoods
personal travel edition
```

The primary visual material should be **place**, not abstract route geometry.

Route diagrams, coordinates and time are supporting layers around actual destination atmosphere.

---

## 5. Core object

The core object is the **personal journey / travel Edition**.

A route line alone is not the product.

The Edition should combine:

- destination imagery;
- place-name hierarchy;
- route signature;
- dates / time of day;
- neighborhood sequence;
- practical utility;
- `why this fits you` editorial rationale;
- visible adaptation between Editions.

---

## 6. Reference / requirement Translation Sheet

### A. Cinematic destination imagery

**OBSERVE**

Issue #457 explicitly requires destination imagery, place atmosphere, weather/light and spatial storytelling.

**ADOPT**

- one dominant real-feeling place moment per key chapter;
- light/weather/time-of-day as travel material;
- intentional crop and image/type pacing.

**REJECT**

- random stock-photo slideshow;
- generic travel hero template;
- image as decorative rectangle beside unrelated copy.

**TRANSLATE**

The image must identify where the traveler is and what that particular route/day feels like.

**SURFACE**

- Entry;
- Traveler Home/current Edition;
- Edition Read/day chapter openers;
- History covers/signatures.

**VERIFY**

Actual screenshots must show destination/place imagery as a major focal element. A CSS-only route drawing does not satisfy this criterion.

---

### B. Route / time / location layer

**OBSERVE**

Current V2 correctly made route and coordinates visible.

**ADOPT**

- route trace;
- neighborhood sequence;
- coordinates/location labels where useful;
- time-of-day cues;
- transfer/dwell signals.

**REJECT**

- abstract orbit geometry that could belong to any signal/control product;
- map clutter;
- route line as the entire art direction.

**TRANSLATE**

Overlay concise route/time information on place imagery and Edition structure so spatial utility and travel feeling reinforce each other.

**SURFACE**

- Entry;
- Generation;
- Edition Read;
- Adaptation.

**VERIFY**

Route information must remain legible while the first impression unmistakably reads as travel rather than a control room.

---

### C. Premium travel editorial / film-like pacing

**OBSERVE**

Issue #457 asks for immersive full-bleed moments balanced by precise editorial utility.

**ADOPT**

- large place reveal;
- chapter pacing;
- image-to-detail transitions;
- concise editorial explanation.

**REJECT**

- plain blog article;
- generic magazine imitation;
- B01 archival paper identity.

**TRANSLATE**

The user moves through a trip as chapters of a personal route, alternating atmosphere with practical travel decisions.

**SURFACE**

- Entry;
- Edition Read;
- History.

**VERIFY**

Screenshots should show clear macro-to-detail travel pacing, not one continuous dark diagram field.

---

## 7. Asset plan

The current live no-image direction is not sufficient under Issue #457.

For a future implementation use one rights-safe path:

- locally stored licensed/CC0 place photography with source documentation; or
- intentionally generated local destination visuals that depict plausible place/weather/route atmosphere without readable text baked into imagery.

Requirements:

- no runtime image CDN dependency for the core experience;
- assets must be documented;
- destination visuals must relate to the actual synthetic route/day fixture;
- do not substitute procedural gradients for location imagery;
- do not use stock-photo people as the identity.

---

## 8. Key surface direction

### 8.1 Entry

Required first 5 seconds:

```text
WHERE am I going?
WHAT kind of trip is this?
WHAT should I do first?
```

Composition:

- one dominant destination/place image or cinematic scene;
- concise place-name title;
- subtle route/time layer;
- one primary action;
- persistent but quiet access to `30초 사용법`;
- no giant abstract orbit as the primary focal object.

Avoid the current visual collision of dark field + huge condensed title + orbit lines.

---

### 8.2 Preference capture

The user should feel they are shaping **trip character**, not configuring settings.

Show pace, food, neighborhood depth, nature/culture, exclusions, budget/tone as progressive choices that visibly change the journey preview.

Avoid a generic chip wall.

---

### 8.3 Generation / pending review

Make interpretation visible:

```text
preference signal
→ neighborhood candidates
→ route fragments
→ day structure
→ editorial review
```

Use actual place thumbnails/scenes, route segments and time cues rather than a three-step loader.

---

### 8.4 Traveler Home

Current Edition is the hero journey object.

Required:

- destination + dates;
- route signature;
- dominant visual cover/scene;
- next meaningful action;
- previous Editions/trips as evolving journey collection;
- no CRUD grid.

---

### 8.5 Edition Read — strongest B02 surface

Required materials:

- day chapter opener;
- large destination imagery;
- neighborhood transitions;
- route line/map fragment;
- time-of-day rhythm;
- concise practical info;
- `why this fits you` editorial note;
- food/place alternatives;
- strong distinction between narrative atmosphere and practical utility.

Mobile must remain highly usable and should not simply stack large images and giant headings.

---

### 8.6 Feedback → Adaptation

The change must be immediately visible:

```text
BEFORE
fast / broad / landmark-heavy

→ feedback

AFTER
slower / neighborhood-heavy / longer dwell / deeper local time
```

Show route density, transfer count, chapter pace and imagery emphasis changing.

---

### 8.7 History

Past travel Editions should feel like accumulated journeys using place/date/route/image signatures, not database records.

---

## 9. Typography

Current root uses intentionally condensed Latin display type, but the scale is extreme:

```text
desktop 144 / 118.08
mobile   78 / 63.96
```

For future redesign:

- keep strong place-name typography;
- reduce dependence on ultra-condensed all-caps as the entire first impression;
- Korean display line-height defaults to >= 1.0;
- image/place should carry part of the emotional burden that typography currently carries alone;
- practical info remains compact and readable.

---

## 10. Motion grammar

B02 motion expresses **travel through space/time**:

- route trace advancing between actual places;
- destination title reveal tied to image change;
- day chapter transition;
- photo mask/pan tied to movement;
- preference choices reshaping route preview;
- feedback changing route density/pacing.

Do not reuse B06 radar/orbit/signal-room motion.

Reduced-motion state must remain information-complete.

---

## 11. 390px Mobile

Mobile should prioritize:

1. destination/place identity;
2. primary action;
3. route/day utility;
4. supporting editorial explanation.

Do not let giant title typography consume most of the viewport before place evidence appears.

Use deliberate crop, compact route signature and readable time/neighborhood labels.

---

## 12. Differentiation

### vs B01

B01 = inward/private/tactile/archive/Edition object.

B02 = outward/place/movement/light/route/journey.

No paper-envelope archive aesthetic in B02.

### vs B06

B06 = signal-dense current discovery environment.

B02 = cinematic place-first journey with actual destination atmosphere.

Avoid dark cyan/orange signal-room similarity.

### vs B07

B07 = relational personal meaning field.

B02 = physical movement through real/synthetic geographic places.

---

## 13. Observable acceptance criteria

A future B02 implementation passes visual conformance only if screenshots show:

1. destination/place atmosphere in the first viewport;
2. at least one rights-documented focal destination image/scene used meaningfully;
3. route/time/location as supporting travel material;
4. `PLACE → ROUTE → DAY → ADAPT` visibly coherent across states;
5. current Edition as a personal journey object;
6. Edition Read stronger than a blog/table;
7. feedback visibly changes route density/pacing/local depth;
8. clear 30-second user path;
9. controlled Korean typography;
10. independently authored Mobile composition;
11. no strong first-impression collision with B06/B07;
12. no load-bearing reference requirement hidden only in prose/source code.

Technical GREEN without these visible criteria is insufficient.
