# B01 — Personal Edition Visual Direction

Status: `V5_IMAGE_LED_DIRECTION_FROZEN`

Current owner judgment:

```text
V4_OWNER_VISUAL_REJECTED=true
V5_REDESIGN_REQUIRED=true
OWNER_UI_APPROVED=false
```

This document supersedes the B01 V4 visual implementation direction while preserving the product/state/backend contracts.

---

## 1. Product job

Personal Edition turns scattered private records into a human-reviewed private publication the participant wants to read, keep, revisit, and influence over time.

```text
FRAGMENT → EDIT → BIND → READ → RECUT
```

The core result is an **authored private Edition**, not a dashboard card, notes database, scrapbook, AI chat, or generic article.

---

## 2. V4 rejection lesson — binding implementation constraint

The V4 implementation was technically valid but visually rejected by the owner.

Why:

1. Main focal visuals were SVG tableaux that illustrated archive/paper metaphors instead of providing convincing material/image authority.
2. Deep forest green spread across too many large surfaces and flattened the palette into a green/ivory theme.
3. Asset presence was incorrectly treated as evidence of reference fidelity; **asset quality and perceptual effect** are the actual acceptance criteria.
4. Entry received more art-direction emphasis than Edition Read, even though Read is the product payoff.
5. The result still felt like a designed explanation of an archive rather than a private publication worth keeping.

Therefore:

```text
MAIN_FOCAL_ART_AS_SVG = FORBIDDEN
ASSET_EXISTS = NOT_A_VISUAL_PASS
EDITION_READ_MUST_BE_STRONGEST_SURFACE = REQUIRED
```

SVG may be used only for minor UI marks, icons, rules, proof lines, or geometry. It must not be the Hero, Human Review, Library/Edition focal visual, or the primary Read visual break.

---

## 3. V5 visual thesis — Image-led Private Archive Editorial

Target response:

> “My scattered private records become a beautiful, authored publication that feels real enough to keep.”

Target qualities:

```text
intimate
tactile
authored
contemporary editorial
quietly luxurious
image-led
collectible
human-reviewed
```

The product should feel closer to a carefully photographed independent publication / editorial campaign than to a vector concept illustration or SaaS prototype.

---

## 4. V5 palette — restore the stronger earlier color tension

Use the earlier B01 palette as the starting tonal system:

```text
ink / near-black      #171915  — structural frame and typography
warm paper            #f2eee4  — primary field
bright paper          #fbf8f1  — reading surfaces
paper depth           #ded6c7  — secondary material
editorial coral       #b7462d  — proof / intervention / authored accent
soft coral            #e9b9a4  — secondary editorial mark
muted olive           #53644a  — limited supporting material
slate / muted blue    ~#40597a — limited visual counterpoint
```

Deep forest green is **not** a default canvas. It may appear only in a limited archive object/folder/material role when it materially improves the composition.

Required palette behavior:

- warm paper + deep ink carry most of the experience;
- coral provides authored editorial tension;
- olive/slate appear sparingly;
- do not allow any single green family to dominate multiple routes;
- avoid beige-on-beige monotony.

---

## 5. Image policy — mandatory for V5

### 5.1 Main focal art

The following surfaces require **raster photographic/image-led material** (`WebP`/`PNG` or equivalent local raster asset):

- Entry / first viewport;
- Human Review;
- Private Library / Edition collection;
- Edition Read opening and/or major visual break.

The imagery must be stored locally in the product build. Do not depend on runtime third-party CDN requests.

### 5.2 Raster text rule

Issue #454 explicitly forbids readable text baked into raster imagery.

Therefore source photography containing printed text must be cropped, defocused, masked, or blurred enough that the raster acts as **material/image**, while all meaningful titles, source text, annotations, issue numbers, proof decisions, and controls remain real HTML.

### 5.3 Stock-photo rule

Do not use recognizable stock-photo people as the product identity.

Hands or partial human presence may appear only when they directly communicate **human editorial review**, and must remain secondary to the proof/source material.

### 5.4 Narrative rule

A photograph is not accepted merely because it contains books, paper, or stationery.

Every image must serve one of these product meanings:

```text
raw material
human editorial intervention
collectible Edition
reading / opening / keeping
```

Decorative stationery mood photography unrelated to state is a MISS.

---

## 6. Reference translation

### Private Archive / independent publication

**Adopt**
- tactile paper and printed-object relationships;
- image-led still life with real light/shadow;
- controlled marginalia and proof intervention;
- collectible issue identity.

**Reject**
- antique nostalgia;
- scrapbook collage;
- fake vector paper scenes;
- stationery mood boards.

**Surfaces**
- Entry, Review, Library, Edition Read.

### The Gentlewoman

**Adopt**
- singular issue identity;
- confident cover hierarchy;
- previous issues as a collection.

**Reject**
- celebrity/fashion-magazine dependency.

**Surfaces**
- Library, cover/opening, history.

### MUBI Notebook

**Adopt**
- decisive image/type rhythm;
- strong editorial crops;
- macro-to-detail pacing;
- visual moments that punctuate reading.

**Reject**
- film-specific identity;
- generic blog/article template.

**Surfaces**
- Edition Read is the primary translation surface.

### Are.na

**Adopt**
- fragments remain distinct before accumulating into meaning;
- source relationship remains visible.

**Reject**
- neutral research-board grid.

**Surfaces**
- Entry, source capture, Human Review.

---

## 7. Surface contracts

### 7.1 Entry / first viewport

Required:

- image-led focal composition has at least equal visual authority to the headline;
- short Korean thesis;
- one primary CTA: `첫 기록 맡기기`;
- secondary `30초 사용법`;
- actual image material communicates fragment → Edition transformation;
- no generic process-card strip as the first explanation;
- on 390px, the headline must not push the focal image entirely below the meaningful first viewport.

Failure conditions:

- focal art still looks like vector/SVG illustration;
- green canvas dominates;
- image behaves as a decorative rectangle unrelated to transformation.

### 7.2 Guide / 30초 사용법

Show four real user steps:

```text
1. 기록 남기기
2. 사람 검토 확인
3. 완성된 Edition 읽기
4. 편집 메모로 다음 호 바꾸기
```

Use actual product-screen/image-preview rhythm. Do not return to generic `how it works` cards or icon explainers.

### 7.3 Writing

Textarea remains the hero interaction.

- calm warm-paper writing field;
- prompts as restrained marginalia;
- privacy/consent visible but secondary;
- image decoration must not compete with typing.

### 7.4 Human Review

This is a proof surface, not a loading/status illustration.

The user should understand:

```text
original fragment
→ editorial intervention
→ human-reviewed decision
→ emerging Edition structure
```

Use raster editorial/proof material as supporting evidence, while actual source/proof labels remain HTML.

### 7.5 Private Library

- latest Edition is the dominant collectible object;
- previous issues read as a coherent but non-identical series;
- image/cover material has real depth;
- avoid CRUD cards and dashboard grids.

### 7.6 Edition Read — highest visual priority

**Edition Read must be the strongest surface in B01 V5.**

Required:

- authentic opening/cover moment;
- image/type editorial pacing;
- at least one major raster visual break inside the reading journey;
- pull quote / source/proof fragment / section shifts where appropriate;
- readable long-form Korean body rhythm;
- HTML text remains authoritative and selectable;
- Mobile is independently composed, not just stacked Desktop.

A plain article column after an attractive cover is a MISS.

### 7.7 Feedback / RECUT

The user must visibly understand:

```text
current treatment
→ my editorial note
→ next treatment
```

Use HTML before/after treatment differences. Do not bake explanation into imagery.

### 7.8 History

Past Editions should feel accumulated and collectible, with controlled cover/image variation rather than a CRUD list.

---

## 8. Typography

- Korean display line-height `<1.0` is not allowed by default;
- do not use giant type merely to signal premium quality;
- image and type share the visual burden;
- body reading comfort outranks display drama;
- manual line breaks must be compositionally intentional;
- Latin microcopy remains metadata, not brand dominance.

---

## 9. Motion

Allowed:

- image mask/opening reveal;
- source fragment arrival;
- proof mark appearance;
- cover/opening transition;
- restrained recut comparison transition.

Avoid:

- decorative orbit/radar motion;
- endless floating;
- parallax with no state meaning;
- motion that delays reading or writing.

Full reduced-motion equivalence required.

---

## 10. V5 conformance gate

Technical QA is necessary but insufficient.

A reviewer must directly inspect Desktop `1440×1100` and Mobile `390×844` screenshots and score:

```text
IMAGE AUTHORITY
REFERENCE FIDELITY
PALETTE QUALITY
FIRST VIEWPORT
ASSET QUALITY
EDITION READ PAYOFF
HUMAN REVIEW CLARITY
LIBRARY COLLECTIBILITY
KOREAN TYPOGRAPHY
MOBILE COMPOSITION
CROSS-STATE COHERENCE
DIFFERENTIATION FROM B06 / B19 / B20
```

Each item is `MATCH / PARTIAL / MISS`.

### Automatic rejection conditions

V5 is not merge-ready if any of the following are true:

- Hero/Review/Library/Read focal art is still SVG-led;
- a main raster asset contains readable baked-in UI/product text;
- green dominates the overall product palette again;
- Entry looks stronger/more authored than Edition Read;
- Read collapses into a plain article after the opening;
- Mobile headline pushes the focal image out of the meaningful first experience;
- asset quality looks like placeholder/prototype art;
- the screen looks materially similar to B06, B19, or B20.

`OWNER_UI_APPROVED=false` remains unchanged after technical merge/deploy until the owner explicitly accepts the actual live V5.