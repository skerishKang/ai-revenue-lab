# B01 — Personal Edition Visual Direction

Status: `DIRECTION_DRAFT_FROZEN_FOR_PREIMPLEMENTATION_AUDIT`

Implementation verdict under the new program:

```text
REDESIGN
```

Reason:

```text
reference fidelity failure
+ insufficient perceptual differentiation
+ usage clarity gap
```

No product implementation is authorized by this document alone.

```text
OWNER_UI_APPROVED=false
```

remains unchanged.

---

## 1. Authority / current evidence snapshot

Current repository main when this document was created:

```text
a631122888d30c5a8a62f4b27e192967da331898
```

Canonical live product:

```text
https://ai-revenue-personal-edition.pages.dev/
```

Relevant lineage:

```text
PR #111 — image-led clickable concept work
Issue #454 — owner rejected V2; art-direction reset required
PR #456 — V3 ASSEMBLY → BIND → READ → RECUT
PR #511 — later B01 typography polish
```

The current V3 contains useful functional/state structure but is not considered visually complete under the new standard.

---

## 2. Product job

Personal Edition turns scattered private personal records into a human-reviewed private publication the participant wants to keep and return to.

The product is not primarily:

- a writing SaaS;
- a notes database;
- a generic personal dashboard;
- a newsletter tool;
- an AI chat interface;
- a scrapbook generator.

The user value is the **transformation from raw private fragments into an authored, collectible personal Edition**.

---

## 3. Core transformation

Use this as the visible product grammar:

```text
FRAGMENT → EDIT → BIND → READ → RECUT
```

Interpretation:

- `FRAGMENT` — a private memory, conversation, note or sentence enters the system;
- `EDIT` — context and relationships are shaped, then human-reviewed;
- `BIND` — the reviewed material becomes a singular private Edition object;
- `READ` — the Edition opens into a designed long-form reading experience;
- `RECUT` — participant editorial feedback visibly changes the next Edition's treatment/focus.

Do not reduce this to a generic progress stepper.

---

## 4. Product feeling

Target qualities:

```text
intimate
archival
quietly luxurious
contemporary editorial
tactile
collectible
human-reviewed
```

These qualities must be expressed through concrete material and composition, not only copywriting.

The product should feel private and valuable, not nostalgic or precious for its own sake.

---

## 5. Visual world — Private Archive Editorial

The design territory is a contemporary private archive / independent publication studio.

### Primary material vocabulary

Use selectively and meaningfully:

- warm ivory / warm white paper;
- deep charcoal/ink;
- deep forest green archival envelope/folder material;
- translucent tracing paper / vellum-like layers;
- restrained oxblood red editorial thread, proof mark or binding accent;
- muted gray and restrained terracotta only where useful;
- pencil/proof marks;
- date stamps / archival indexing;
- clipped source fragments;
- thin binding lines/thread;
- shallow tactile paper depth and soft natural-light shadow;
- museum-catalog / independent-publication precision;
- high-quality stationery tactility without vintage cosplay.

### Explicitly avoid

- beige-on-beige monotony;
- distressed/dirty/torn paper effects;
- sepia nostalgia;
- generic scrapbook collage;
- decorative stationery photos unrelated to product state;
- flat CSS rectangles pretending to be sufficient focal artwork;
- glassmorphism;
- neon/cyberpunk;
- stock-photo people;
- cartoonish 3D;
- generic SaaS cards and dashboard grids.

---

## 6. Color territory

Indicative, not final token lock:

```text
warm ivory / white     — principal reading material
charcoal / near-black  — ink and framing
forest green           — archival/private object identity
restrained oxblood     — editorial/binding intervention
muted gray             — metadata/provenance
terracotta             — optional secondary material accent
```

The final palette must remain more materially varied than a single beige paper field.

Do not copy B06's cyan/orange signal palette.

---

## 7. Core object

The dominant object is the **Edition** — not a card, not a dashboard tile.

The Edition should appear as a designed object with:

- issue/edition identity;
- cover hierarchy;
- tactile material;
- deliberate proportions;
- visible relationship to source fragments;
- opening/reading behavior;
- collectible continuity across previous issues.

The Edition must look desirable enough that the participant understands why this product is worth keeping.

---

## 8. Reference Translation Sheet

### A. Private Archive Editorial / museum catalogue / independent publication language

**OBSERVE**

- tactile paper relationships;
- archival folders/envelopes;
- translucent overlays;
- controlled annotations;
- physical hierarchy without decorative clutter.

**ADOPT**

- forest archival object;
- vellum/tracing layer;
- proof/editorial marks;
- quiet material depth;
- catalogue-like precision.

**REJECT**

- antique nostalgia;
- distressed scrapbook effects;
- excessive decorative ephemera.

**TRANSLATE**

- private source material physically/visually enters an editorial archive and becomes an Edition.

**SURFACE**

- Entry;
- Human Review;
- Edition Cover/Open;
- Library.

**VERIFY**

- screenshots must visibly contain the translated material system; it must not exist only in hidden assets or prose.

---

### B. The Gentlewoman — issue identity / collectible publication

**OBSERVE**

- strong issue identity;
- confident cover hierarchy;
- archive as a sequence of collectible publications.

**ADOPT**

- singular issue identity;
- disciplined cover typography;
- previous Editions as a collection.

**REJECT**

- fashion-magazine identity;
- portrait/celebrity dependency.

**TRANSLATE**

- participant's private Editions become a personal library with distinct issue presence.

**SURFACE**

- Private Library;
- Edition Cover;
- archive/history.

**VERIFY**

- latest Edition is visually dominant and previous Editions read as a collectible series, not CRUD cards.

---

### C. MUBI Notebook — image/type editorial rhythm

**OBSERVE**

- image and type create pacing;
- confident editorial crops;
- visual moments punctuate reading rather than decorate it.

**ADOPT**

- macro-to-detail rhythm;
- decisive visual breakpoints;
- text/image/material pacing.

**REJECT**

- film-specific identity;
- blog/article-template imitation.

**TRANSLATE**

- source fragments, proof traces and Edition material create reading rhythm inside a private personal publication.

**SURFACE**

- Edition Read;
- opening spread;
- section transitions.

**VERIFY**

- Edition Read must not collapse into a plain centered article column.

---

### D. Are.na — fragments accumulating into meaning

**OBSERVE**

- separate fragments acquire meaning through relation and accumulation.

**ADOPT**

- visible fragment identity;
- accumulation/association;
- source pieces remain legible as originating material.

**REJECT**

- neutral research-board interface;
- generic block grid.

**TRANSLATE**

- private notes/conversation fragments become editorial material and then a singular Edition.

**SURFACE**

- Entry;
- source capture transition;
- Human Review.

**VERIFY**

- the source-to-edition relationship must be visible, not only described by `Gather/Shape` labels.

---

## 9. Key surface direction

### 9.1 Entry / first viewport

Goal: show the transformation before the user reads an explanation.

Composition direction:

- one clear, short Korean thesis;
- one primary CTA: `첫 기록 맡기기`;
- one secondary learning entry such as `30초 사용법`;
- a dominant tactile visual occupying roughly half or more of the meaningful composition;
- archival envelope/folder + translucent fragment layers + emerging Edition relationship;
- motion may gather/reveal/bind, but only if it communicates product meaning.

Remove from first viewport:

- generic four-column process explanation;
- excessive product prose;
- QA/debug labels;
- weak decorative objects.

The first 5 seconds should say:

> my scattered private records become one authored private Edition.

---

### 9.2 30-second use path

Must answer:

```text
1. 기록 남기기
2. 편집/사람 검토 보기
3. 완성된 Edition 읽기
4. 편집 메모로 다음 호 바꾸기
```

Prefer actual screen previews or visual state transitions over four generic explanation cards.

The Guide should show what the participant does, not only what the editorial system does.

---

### 9.3 Writing / source capture

The textarea remains the hero interaction.

Required:

- comfortable writing measure;
- clear action state;
- privacy/consent visible but secondary;
- prompts behave like restrained editorial cues/marginalia;
- source provenance feels real without clutter;
- tactile material may frame the writing environment, but must not compete with typing.

Do not add an unrelated large photograph below the form.

---

### 9.4 Human Review

This should become one of B01's strongest differentiating surfaces.

Show a legible relationship between:

```text
original fragment
editorial shaping / proof trace
human-reviewed decision
emerging Edition structure
```

Use proof marks, annotation, vellum overlays, source index or binding cues where they improve understanding.

Do not theme the operator so heavily that scanning/review becomes harder.

---

### 9.5 Private Library

Goal: personal archive, not dashboard.

Required:

- latest Edition is the dominant collectible object;
- previous issues have distinct yet coherent covers/spines;
- next meaningful action is obvious;
- archive/history reads as accumulated personal time;
- no generic card grid as the primary language.

Strong differentiation from B19 is mandatory.

B01 = authored private publication / Edition collection.

B19 = memory binding/provenance book workflow.

---

### 9.6 Edition Read

This is the payoff surface and must be the strongest screen in the product.

Required:

- authentic cover/opening transition;
- controlled long-form Korean reading rhythm;
- section markers;
- pull insight / proof/reference moments when appropriate;
- material shifts that support pacing;
- clear provenance/human-review context without compliance-dashboard weight;
- Mobile reading composition independently designed.

Avoid plain blog/article layout.

---

### 9.7 Feedback / RECUT

The participant should **see** that feedback changes the next Edition.

Required:

- current treatment vs next treatment relationship;
- one or two visible changes in focus, framing or editorial emphasis;
- an authored transition rather than a generic form confirmation;
- clear human control.

---

## 10. Typography

Korean typography is a primary material but must remain controlled.

Rules:

- no default Korean display line-height below `1.0`;
- avoid giant titles merely to signal premium/editorial quality;
- prefer fewer, stronger lines;
- control Hangul line shapes deliberately;
- body reading comfort outranks dramatic display type;
- use Latin microcopy sparingly as metadata, not as the dominant identity.

The design should not depend on a Latin-first serif/condensed fallback to create quality.

---

## 11. Motion grammar

Allowed meaningful motions:

```text
fragment arrival
overlap / reveal
vellum shift
editorial mark appearance
binding alignment
cover/opening reveal
recut comparison transition
```

Motion must answer “what changed in the product state?”

Avoid:

- endless decorative floating;
- generic parallax;
- orbit/radar motion associated with B06;
- motion that delays writing/reading;
- motion that becomes the product's identity instead of supporting it.

Full reduced-motion equivalence required.

---

## 12. Desktop composition

Desktop may use asymmetric editorial composition, but the product action must remain dominant.

Target characteristics:

- strong material scale;
- one clear focal object;
- intentional negative space;
- controlled asymmetry;
- no tiny action controls stranded in large canvases;
- reading width remains comfortable.

---

## 13. 390px Mobile composition

Mobile must be independently authored.

Requirements:

- product identity visible in the first viewport;
- main CTA accessible without excessive scroll;
- focal archive/Edition material crops intentionally;
- large Korean titles compact relative to Desktop;
- sticky chrome must not cover the real task;
- writing field gets priority over decorative material;
- Edition Read feels designed, not merely stacked.

---

## 14. Differentiation requirements

### vs B06 World Feed

B01 must feel:

```text
inward / private / slow / tactile / collected
```

not:

```text
outward / current / signal-dense / exploratory
```

### vs B19 Personal Memory Book

B01 core object is **an authored Edition**.

B19 core object should remain the **memory/provenance binding process**.

### vs B20 Personal Memory Novel

B01 is private publication from broad personal fragments.

B20 is narrative interpretation of memory with source/POV/author boundaries.

Do not let all three become paper + giant serif title products.

---

## 15. Observable acceptance criteria

A future B01 implementation is visually conforming only if direct Desktop/Mobile screenshots show:

1. a clearly new Private Archive Editorial material system;
2. deep forest / ivory / ink / restrained oxblood used with purpose rather than as token-only changes;
3. visible tactile layering or equivalent high-quality focal art;
4. source fragments visibly becoming an Edition;
5. an Edition that appears collectible;
6. a clear first action;
7. a real 30-second use path;
8. Writing dominated by the writing surface;
9. Human Review visually communicates source → edit/proof → decision;
10. Edition Read is stronger than a plain article;
11. RECUT visibly changes the next treatment;
12. Korean typography passes direct visual review;
13. Mobile preserves identity and action clarity;
14. the result does not look like B06, B19 or B20;
15. a reviewer can point to each major reference translation in screenshots.

If several load-bearing items are `MISS`, the redesign is incomplete even if all technical tests pass.
