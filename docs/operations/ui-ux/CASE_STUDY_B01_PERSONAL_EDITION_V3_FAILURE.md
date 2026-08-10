# Case Study — B01 Personal Edition V3

Role in the new visual program: **failure/learning case study**.

This is not a statement that no work was done. V3 materially changed templates, layout and styling.

The failure is narrower and more important:

> substantial implementation change did not produce enough **perceptual change, reference fidelity, or unique product identity** in the owner's live review.

This case study does not modify owner approval state.

```text
OWNER_UI_APPROVED=false
```

---

## 1. Relevant lineage

Earlier image-led concept work:

```text
PR #111
```

That work explicitly referenced:

- Substack — publication/cover hierarchy;
- MUBI Notebook — image/type editorial rhythm;
- The Gentlewoman — issue identity and collectible archive;
- Are.na — fragment assembly.

Later owner rejection of B01 V2:

```text
Issue #454
B1_UI_V2_OWNER_REJECTED=true
V3_ART_DIRECTION_RESET_REQUIRED=true
```

V3 redesign:

```text
PR #456
head 8aa51765fcfbcf6c9871c6e19ea1f491368914d6
merge commit dc129b0a2768ec8aaae0d7517e182311d7b80422
```

V3 thesis:

```text
ASSEMBLY → BIND → READ → RECUT
```

Later B01 typography polish was included in PR #511.

The current repository main at creation of this case study is:

```text
a631122888d30c5a8a62f4b27e192967da331898
```

---

## 2. What V3 genuinely improved

V3 was not a tiny CSS patch.

It correctly attempted to:

- remove the rejected V2 split beige/photo hero;
- replace generic visible progress steppers with a coherent Gather/Shape/Review/Bind grammar;
- make the writing textarea the primary interaction;
- turn the participant dashboard into a Private Library;
- give the published Edition a stronger cover/opening treatment;
- turn feedback into an editorial `RECUT` concept;
- keep participant routes in one visual system;
- hide owner-facing QA/debug chrome from the canonical root.

These are real structural improvements.

The lesson is therefore **not** “large redesigns are pointless.”

The lesson is that a redesign can be structurally coherent and still miss the promised art direction.

---

## 3. Why the owner could reasonably ask “what changed?”

The V3 first viewport is still composed primarily from:

```text
large editorial display title
+ dark field
+ paper-colored CSS rectangles
+ text fragments
+ flat edition/book-like object
+ editorial process copy
```

This is different from V2 source code, but the perceptual vocabulary remains close to the same broad family:

```text
editorial typography
paper metaphor
publication object
large empty composition
```

Therefore the owner sees evolution inside one familiar aesthetic category rather than a decisive new product world.

Large implementation change is not enough if the visual material remains conceptually similar.

---

## 4. Reference fidelity failure

The most important B01 lesson is that reference work became too abstract during later redesign.

Concrete private-archive/editorial qualities that had been discussed or implied included things such as:

- deep forest archival material;
- translucent tracing/vellum-like layers;
- restrained oxblood/red editorial thread or marks;
- proofing/annotation traces;
- tactile depth;
- collectible independent-publication behavior;
- image/type rhythm that makes the Edition feel physically desirable.

But V3 increasingly translated the direction into generic nouns/adjectives:

```text
premium
cinematic
editorial
collectible
assembly
binding
```

The implementation then deliberately avoided visible decorative raster photography and relied heavily on CSS/HTML objects.

That is not inherently wrong, but it removed much of the concrete material evidence that could have made the references legible.

A reference is not successfully used when only its abstract concept survives.

---

## 5. Hidden asset symptom

A particularly useful diagnostic pattern is that some richer visual assets can exist in repository history or compatibility markup without contributing to the visible product.

For example, current participant dashboard compatibility markup references assets such as:

```text
private-library-hero.webp
editorial-process-layers.webp
edition-cover-shift.webp
```

inside a non-rendered legacy contract template, while the visible Library/Edition experience is primarily HTML/CSS composition.

This shows why code/asset inventory is not visual QA.

The reviewer must ask:

> What is actually visible in the screenshot?

not:

> What visual assets exist somewhere in source?

---

## 6. Missing usage clarity

B01 also exposes a difference between **process explanation** and **user onboarding**.

A row such as:

```text
Gather → Shape → Review → Bind
```

explains how an edition is produced.

It does not fully answer:

```text
What do I click?
What do I enter?
What happens next?
Where do I see the completed result?
How does my feedback change the next edition?
```

B01 therefore needs a real `START → ACTION → RESULT` path, potentially a compact `30초 사용법` entry or equivalent integrated onboarding.

---

## 7. Why B06 felt more changed

B06's later reset changed the product-facing **material system**:

```text
reference-board/SVG feeling
→ active signal environment
```

and rebuilt hierarchy around:

```text
lead story
signal rail
discovery mosaic
WHY
preference change
return context
```

B01 V3 changed layout and semantics but did not create an equally decisive material distinction from its earlier editorial/paper family.

Therefore:

> B06 is evidence that perceptual change comes from changing the relationship between product behavior and visible material/hierarchy — not merely from rewriting templates.

---

## 8. New-standard verdict

Under the new Visual Direction Standard, current B01 is classified:

```text
REDESIGN
reason = reference fidelity + perceptual differentiation failure
```

This does **not** mean functional contracts should be discarded.

Preserve the useful product structure:

```text
source capture
human review
private library
published edition
feedback/adaptation
archive
```

Rebuild the product-facing art layer so the user's supplied archive/publication references are visibly translated into real screens.

---

## 9. What B01 V4 must prove before completion

A future redesign should be rejected as insufficient if the owner can again reasonably ask “what changed?” after seeing only the live screens.

The new version must visibly prove:

1. a distinct Private Archive Editorial world;
2. a focal material/visual system stronger than generic CSS paper rectangles;
3. a collectible Edition that looks worth keeping;
4. a visible source → edit/review → bind transformation;
5. reference qualities that can be pointed to in screenshots;
6. a clear first action;
7. a clear 30-second usage path;
8. strong but controlled Korean typography;
9. Mobile composition that preserves the product feeling;
10. differentiation from B19 Memory Book and B20 Memory Novel.

---

## 10. Program-level lesson

Never again accept the following chain as proof of visual success:

```text
large diff
+ new design vocabulary in PR description
+ screenshot automation PASS
= successful redesign
```

The required chain is:

```text
frozen visual thesis
+ explicit reference translation
+ real implementation
+ direct screenshot inspection
+ MATCH against the promised thesis
= visually conforming implementation
```
