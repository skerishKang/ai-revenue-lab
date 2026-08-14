# Case Study — B01 V7: Anchor Success, System Failure

- Status: **METHODOLOGY CASE**
- Date: 2026-08-14
- Business: B01 Personal Edition
- Scope: visual/process lesson; not a product approval record

## 1. What happened

Business 01 progressed through several named visual generations. The 2026-08-14 V7 Entry correction finally produced a first page the owner described as more balanced/satisfactory.

However, direct review of the remaining participant pages showed that the product still did not read as one coherent visual system.

The key mismatch was structural:

```text
Entry
= scene + photo fragments + spatial overlap + collectible vertical Edition object

Other routes
= persistent header + very large title + two-column shell + cards/forms/panels
```

The problem was not merely a font choice or a few spacing defects.

## 2. Why the nominal V7 whole-site pass failed

The initial V7 site-wide work largely preserved existing V3/V4/V5/V6 page structures and applied V7 materials, colors, photography and glass treatments on top.

That produced **material skinning over legacy composition** rather than full design-system translation.

The Entry became different only after a dedicated fidelity layer rebuilt its first viewport composition more directly.

## 3. Technical visual-debt signal

The participant base loaded multiple visual generations in sequence, including V3, V4, V5, several V6 layers, V7 layers and later Entry-specific fidelity CSS.

This made visual authority hard to reason about and encouraged further overrides rather than consolidation.

The lesson is:

> a new art-direction name is not a new design system if old layout/type/component authorities still control most routes.

## 4. Typography symptom

The user specifically noticed that non-Entry pages looked strange around typography.

The deeper issue was mixed authority:

- current V7 body/UI stacks;
- older V3 typography-polish rules;
- route-specific inherited title sizes/weights;
- different serif/sans roles across reading and non-reading surfaces;
- preferred font names without one clearly verified current delivery strategy.

Therefore the correct remedy is not simply “pick a nicer font.” It is to establish one explicit current typography system and verify actual rendered fallback behavior across route archetypes.

## 5. Screen-level diagnosis

The audit grouped routes roughly as follows:

### Keep as anchor

- Entry — current direction is the local B01 anchor.

### Archetype recovery first

- Library — collection/object archetype; promising assets/object idea but generic two-column/product-page composition remains.
- Write — interaction archetype; core writing function is visually dominated by an oversized form shell/title relationship.
- Read — long-form archetype; strongest internal candidate but typography and reading hierarchy do not yet feel fully connected to Entry.

### Wait for system proof, then rebuild

- Guide;
- Access;
- Feedback;
- History/Archive;
- Adaptation/Recut;
- other participant states.

These should not each invent their own solution before the archetype system is proven.

## 6. What should have happened earlier

The cheaper sequence would have been:

```text
V7 Entry anchor
→ owner/CTO direction lock
→ Library + Write + Read
→ side-by-side system review
→ only then remaining routes
```

Had this process been used, the cross-state mismatch would have been discovered after four screens rather than after a broad site pass.

## 7. Failure classification

The current B01 problem is primarily:

```text
ARCHETYPE_SYSTEM_FAILURE
LEGACY_SHELL_FAILURE
TYPOGRAPHY_FAILURE
IMPLEMENTATION_CASCADE_FAILURE
```

It is **not currently classified as `CONCEPT_FAILURE`**, because the owner is satisfied with the corrected Entry direction.

Therefore the operating response is:

```text
KEEP ENTRY
→ repair translation/system
→ consolidate source authority
```

not:

```text
invent V8
```

## 8. Owner-approval boundary

The owner's positive feedback on Entry is not whole-product approval.

Correct interpretation:

```text
B01 Entry direction = locked for system testing
B01 whole-product OWNER_UI_APPROVED = false
```

The rest of the participant product remains under redesign/system recovery.

## 9. Portfolio lesson

For 50+ Businesses, do not optimize for producing many complete-looking sites quickly. Optimize for **rejecting weak systems after the smallest representative set of screens**.

Reusable process:

```text
REFERENCE TRANSLATION
→ ONE ANCHOR
→ 2–3 HARD ARCHETYPES
→ SIDE-BY-SIDE SYSTEM VERDICT
→ FULL EXPANSION ONLY ON PASS
```

This is the scaling lesson from B01 V7.

## 10. Contrast with B06 methodology

Business 06 is useful because its accepted visual baseline and explicit reference notes preceded later UX expansion.

B01 V7 demonstrates the complementary warning:

> even when an anchor becomes good, do not assume the remaining product has inherited its visual logic until archetype screens prove it.

Together the two cases define the current portfolio design process.
