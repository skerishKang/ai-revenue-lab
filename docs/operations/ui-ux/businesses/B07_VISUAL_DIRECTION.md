# B07 — Personal Meaning Map Visual Direction

Status: `DIRECTION_FROZEN_FOR_PREIMPLEMENTATION_PROGRAM`

New-standard verdict:

```text
REDESIGN
```

Scope of redesign:

```text
KEEP interaction/state contract
REDESIGN product-facing art/material layer
```

Reason:

```text
strong first-impression collision with B06 dark signal-room language
+ portfolio differentiation failure
```

The current interaction concept remains valuable.

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

Canonical numbered live surface:

```text
https://07-personal-meaning-map.pages.dev/
```

Recent lineage:

```text
PR #567 — deep Production audit
PR #568 — Korean display rhythm correction
PR #569 — exact-main deployment verification
```

Current interaction grammar recorded by recent work:

```text
MEMORY → SIGNAL → CONNECT → REVIEW → REFRAME
```

Fresh Batch A evidence:

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
- Korean title rhythm is now technically healthier (`105.84 / 107.957` desktop; `49.14 / 52.58` mobile);
- first viewport is a very dark green field with white/coral giant Korean title and orbit-like linked circular nodes;
- this is visually very close to B06's dark signal field, despite a different product job;
- the full page continues with dark panels and equal-card sequences, reinforcing portfolio-family sameness.

The earlier `KEEP` decision was made against B06 as a **quality bar**; under the new portfolio differentiation rule it must be revised.

---

## 2. Product job

Personal Meaning Map helps a user select memories/records, notice a meaning signal between them, explicitly connect the relevant items, review that interpretation and reframe or undo it.

It is not primarily:

- a social graph;
- a knowledge graph tool;
- a dark data visualization dashboard;
- a feed;
- a memory archive book;
- an AI-generated personality map.

The value is seeing **meaning emerge between personal fragments while the user retains control of the connection**.

---

## 3. Core transformation — preserve

```text
MEMORY → SIGNAL → CONNECT → REVIEW → REFRAME
```

Alternative user-facing expression:

```text
remember
→ notice relation
→ connect deliberately
→ review meaning
→ change / undo
```

This interaction/state system should be retained.

---

## 4. New visual territory — Relational Meaning Field

B07 should leave the dark signal/control-room family.

Reserve a distinct territory:

```text
quiet relational space
light / mineral / translucent field
memory capsules with temporal depth
soft semantic threads
meaning appears between objects, not as a radar signal
```

Target qualities:

```text
reflective
spatial
personal
clear
reversible
non-technical
```

The visual field may be abstract, but it must feel like **personal relationships between remembered moments**, not system telemetry.

---

## 5. Core object

The core object is the **relationship between selected memories**.

Not the individual node by itself.

The interface should make this progression visually legible:

```text
separate memory fragments
→ proximity / tension / shared cue
→ explicit user connection
→ meaning statement
→ reframe / undo
```

---

## 6. Material direction

Prefer a materially distinct system from both B01 and B06.

Possible territory:

- warm-light or pale mineral background;
- subtle translucent memory capsules;
- low-saturation temporal color coding;
- hairline semantic threads;
- depth through blur/opacity only when it clarifies foreground/background memory status;
- small date/place/sensory markers;
- one restrained warm accent for user-created connection;
- meaningful spatial distance between memories.

Avoid:

- black/green signal-room canvas;
- cyan/orange radar language;
- orbit diagrams;
- technical graph/network aesthetics;
- beige paper/archive object language from B01/B19;
- generic cards as the main composition;
- mystical galaxy/constellation clichés;
- personality-test aesthetics.

---

## 7. Reference Translation framework

The next implementation should research relational/field interfaces and editorial spatial systems before code. The required translation must focus on behavior rather than copying a graph visualization.

### Relational spatial composition

**OBSERVE**

Meaning is easier to understand when objects can be compared in one shared field and the relation itself is visually explicit.

**ADOPT**

- spatial separation and approach;
- clear selected/unselected state;
- a connection that has visual weight only after user intent;
- readable relation summary.

**REJECT**

- dense force-directed network;
- technical node-link graph;
- animated orbit/radar system.

**TRANSLATE**

Personal memories exist as calm capsules; selecting two or more reveals shared cues, then the user deliberately commits a semantic thread.

**SURFACE**

- root/workspace;
- selection;
- connected state;
- review/reframe.

**VERIFY**

Screenshots must be visually distinguishable from B06 at thumbnail size while preserving an obvious relationship field.

---

## 8. Key surface direction

### 8.1 Entry / root

The first viewport should demonstrate the product rather than merely announce it.

Required:

- concise Korean thesis;
- 2–4 memory fragments visible in a calm field;
- one relationship beginning to emerge;
- one primary action such as `기억 연결 시작하기`;
- `30초 사용법` secondary entry;
- no giant dark title/orbit composition as the dominant identity.

A new user should understand that this is about **connecting personal memories**, not scanning signals.

---

### 8.2 Memory selection

Selection should feel deliberate and reversible.

Use:

- date/place/context cues;
- compact memory excerpts;
- clear selected state;
- explicit minimum selection requirement;
- direct Undo/Reset access.

Avoid checkbox-card grids if a spatial field can communicate selection more naturally.

---

### 8.3 Signal / relation emergence

Before connection is committed, show a tentative relation as **provisional**.

The UI should distinguish:

```text
observed shared cue
≠ confirmed meaning
```

Use soft thread/proximity/annotation rather than a bright system alert.

---

### 8.4 Connect

The user's explicit connection action is the decisive moment.

After Connect:

- relation thread becomes more concrete;
- meaning summary appears close to connected memories;
- provenance of the interpretation remains understandable;
- user can undo.

---

### 8.5 Review / Reframe

Do not show a generic modal or form card.

Keep the connected memories visible while the user:

- accepts the framing;
- edits/reframes it;
- disconnects;
- resets.

The product should demonstrate that meaning is **editable**, not an AI verdict.

---

## 9. Typography

Recent B07 Korean typography polish is useful and should be preserved as a minimum quality baseline:

```text
desktop ~105.84 / 107.96
mobile  ~49.14 / 52.58
```

However, the next art direction should rely less on giant display typography as the main visual identity.

Use title scale to support the relational field, not overpower it.

---

## 10. Motion grammar

B07 motion should express **relation formation**, not signal scanning.

Allowed:

- memory capsules gently reposition when selected;
- a tentative thread appears after shared cue detection;
- explicit Connect firms the relation;
- Reframe changes thread label/shape/relationship emphasis;
- Undo visibly restores prior separation.

Avoid:

- orbiting nodes;
- radar sweeps;
- continuous autonomous motion;
- decorative particle fields;
- B06-style stream/shift behavior.

Reduced motion must preserve all meaning states immediately.

---

## 11. Mobile composition

390px should not become a giant title followed by offscreen nodes.

Target:

- compact title/value statement;
- at least two memory fragments visible early;
- selection/connect action within a reasonable first interaction depth;
- relation summary appears adjacent to connected memories;
- Undo/Reset remain easy to find;
- no sticky chrome covering the field.

---

## 12. Differentiation

### vs B06 World Feed

B06:

```text
external world
current signals
dark active dispatch
stream / shift
```

B07:

```text
personal memories
quiet relation
light/mineral relational field
connect / reframe
```

Thumbnail-level distinction is mandatory.

### vs B01 Personal Edition

B01 turns fragments into a collectible publication object.

B07 keeps memories as separate items and makes their **relationship** the result.

No archive envelope/book material as B07's primary language.

### vs B19 Memory Book

B19 should emphasize chronology/provenance/binding.

B07 emphasizes semantic relation and user-controlled reframing.

---

## 13. Observable acceptance criteria

A future B07 redesign passes only if screenshots show:

1. current MEMORY → SIGNAL → CONNECT → REVIEW → REFRAME interaction preserved;
2. art direction no longer strongly resembles B06;
3. relation, not node/card/title, is the core visual object;
4. selected memories and provisional relation are clearly distinguished;
5. Connect visibly changes the relation state;
6. Review/Reframe happens with source memories still in context;
7. Undo/Reset remain obvious and functional;
8. Korean typography remains at least as healthy as the recent polish;
9. 390px shows actual memory relation early, not only a large headline;
10. technical interaction contracts remain green;
11. direct side-by-side screenshot review against B06 confirms clear portfolio differentiation.
