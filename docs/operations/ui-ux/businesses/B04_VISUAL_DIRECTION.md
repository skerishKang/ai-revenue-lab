# B04 — Living Learning / Adaptive Learning Visual Direction

Status: `DIRECTION_FROZEN_FOR_PREIMPLEMENTATION_PROGRAM`

New-standard verdict:

```text
FOCUSED_POLISH
```

Preserve the current Adaptive Protocol product concept and learner journey. Correct portfolio-level visual collision and Korean display compression rather than performing another full product reset.

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

Canonical live surface:

```text
https://ai-revenue-living-learning.pages.dev/
```

Recent lineage:

```text
PR #548 — Adaptive Protocol V2 landing/Guide
PR #564 — read-only deep visual audit
PR #565 — Adaptive Workspace V3 across learner journey
PR #566 — exact-main Production deployment/verification
```

Fresh Batch A Chromium evidence:

```text
run      = 31421541852
artifact = 9075565375
sha256   = cacecf7ab056a7c3478f3cd078bf8edb080780a3e8ab7afbb960fd6bee58f0e2
viewports = 1440×1100, 390×844
```

Observed root/Guide:

- HTTP 200;
- overflow 0;
- console/page errors 0;
- visible `<img>` count 0;
- Adaptive Protocol board is product-specific and communicates learning adaptation;
- however the first impression still uses the portfolio's repeated dark-panel + oversized-display pattern;
- Korean root/Guide H1 desktop `78px / 76.44px`;
- Korean root/Guide H1 mobile `49.53px / 47.5488px`;
- both ratios are below 1.0 and fail the new default Korean typography rule.

---

## 2. Product job

Living Learning makes the **next lesson change because of the learner's current performance and feedback**.

It is not primarily:

- a course catalogue;
- a generic LMS dashboard;
- a static online lecture;
- an AI tutor chat;
- a dark analytics console.

The differentiating promise is visible adaptation over time.

---

## 3. Core transformation — preserve

```text
GOAL → DIAGNOSTIC → LESSON → FEEDBACK → ADAPT
```

The product should make the causal relationship explicit:

```text
what I tried
+ where I struggled / succeeded
+ what I said I need
→ what changes in my next lesson
```

This is the strongest current idea and should remain intact.

---

## 4. Visual world — Adaptive Learning Studio

Reserve B04 as a **learning-editing / adaptive lesson studio**, not a control room.

Target qualities:

```text
focused
instructional
progressive
editable
calmly analytical
learner-centered
```

The product should feel like a working study surface in which lesson structure changes in response to evidence.

---

## 5. Core object

The core object is the **lesson and its visible adaptation trace**.

Not the dashboard, not the metric strip, not a decorative diagram.

The user should be able to see:

```text
LESSON BEFORE
→ learner signal / feedback
→ LESSON AFTER
```

as a recurring product object.

---

## 6. Material and composition direction

Preserve the sharp editorial/protocol quality but reduce dependency on a monolithic dark exhibition board.

Prefer:

- light or neutral study/work surfaces for sustained learner tasks;
- a restrained dark/navy adaptation layer only where contrast communicates a state change;
- blue as an instructional/editing accent rather than a generic neon/console signal;
- ruled lesson structure, annotation rails, progress traces and comparison states;
- clear lesson text and actionable controls.

Avoid:

- every surface as a dark control panel;
- huge display headline carrying the whole identity;
- generic rounded LMS cards;
- KPI dashboards as learner home;
- chatbot-first tutoring;
- B06-style signal/orbit visuals.

---

## 7. Reference Translation approach

B04 currently has a stronger product metaphor than a specific named external visual reference set. Future implementation must therefore use **product-behavior references**, not invent vague mood references after the fact.

### Adaptive editing / revision behavior

**OBSERVE**

The strongest current pattern is an editorial/protocol comparison that makes learning change visible.

**ADOPT**

- before/after lesson structure;
- margin-level feedback signal;
- explicit adaptation trace;
- clear current step.

**REJECT**

- generic course progress bars;
- analytics dashboards where the learner's task disappears.

**TRANSLATE**

Treat each lesson as an editable learning document whose next version is visibly revised from the learner's evidence.

**SURFACE**

- Diagnostic result;
- Lesson result;
- Feedback;
- Changes/Adaptation;
- next lesson;
- progress/history.

**VERIFY**

Screenshots should show the actual lesson changing, not merely a label saying `ADAPTIVE`.

---

## 8. Key surface direction

### 8.1 Entry

The current thesis is good:

> 10분 뒤, 다음 수업이 나에게 맞게 달라집니다.

Keep the idea, but make the first viewport feel like a learner's adaptive study environment rather than a dark product-presentation board.

Required:

- short Korean thesis;
- one first action;
- visible adaptation example or lesson fragment;
- compact `30초 사용법`;
- less decorative dark mass.

---

### 8.2 Goal / Diagnostic

The learner should understand what the system is trying to learn about them.

Use:

- task/goal statement;
- current answer attempt;
- observable skill signal;
- clear next action.

Do not present a generic form wizard.

---

### 8.3 Lesson

Lesson content is the hero.

Keep the working text large enough to read but do not let display typography overpower the exercise.

Feedback and annotations should sit close to the exact task they refer to.

---

### 8.4 Feedback → Changes

This is B04's strongest payoff.

Make the causal chain visible:

```text
learner answer / preference
→ interpretation
→ exact lesson element changed
```

Use highlighted revisions, moved emphasis, changed difficulty/order or new practice block rather than a generic “personalized successfully” confirmation.

---

### 8.5 History / Progress

Show how lessons changed over time, not only completion percentage.

A compact adaptation history is more product-specific than a dashboard of metrics.

---

## 9. Korean typography correction

Fresh root/Guide evidence currently violates the new default:

```text
desktop 78 / 76.44
mobile 49.53 / 47.5488
```

Required focused correction in the future implementation phase:

- Korean display line-height >= 1.0 by default;
- reduce size if necessary rather than compressing Hangul;
- deliberate line breaks for the 390px title;
- keep body/lesson text comfortably readable;
- avoid using compressed Latin/display logic for Korean headlines.

This is a bounded polish item, not a reason to discard the product concept.

---

## 10. Mobile composition

The recent V3 learner-workspace work already reduced earlier chrome problems; preserve that.

Future checks:

- primary learning content begins near the top;
- no sticky shell covers the lesson;
- adaptation context may precede a title only when it materially helps the task;
- CTA and first exercise are visible without long decorative scrolling;
- dark adaptation blocks do not dominate every screen.

---

## 11. Differentiation

### vs B06

B06 = outward signal discovery.

B04 = inward skill revision / changing lesson.

No radar/orbit/signal-room language.

### vs B14 / B32 / B42

Those are AI/workflow/platform/control products.

B04 must remain visibly about **learning content and learner change**, not system configuration.

---

## 12. Observable acceptance criteria

Future focused polish is complete only if screenshots show:

1. current Adaptive Protocol concept preserved;
2. learner journey remains coherent across internal routes;
3. lesson/adaptation trace is the core visual object;
4. root/Guide Korean display line-height visually safe >=1.0 by default;
5. first viewport less dependent on generic dark-board presentation;
6. learner content outranks decoration;
7. Mobile chrome does not delay the task;
8. feedback visibly causes a specific next-lesson change;
9. visual identity remains clearly distinct from B06/control-room products;
10. all existing deterministic learning/state contracts still pass.
