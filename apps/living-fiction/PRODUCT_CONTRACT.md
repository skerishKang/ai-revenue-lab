# Living Fiction Product Contract

- Status: Approved for Phase 1 implementation
- Date: 2026-07-21
- Related issue: #34
- Implementation model: GLM-5.2 (free tier, provider route `tokenrouter`)

## 1. Target reader and value proposition

**Audience:** Korean adult readers who enjoy short serialized urban mystery.

**Value proposition:** Readers share a common canonical world and can discuss
the same central work, while also receiving optional personal branches that
visibly respond to their explicit choices and short comments — all without
mutating shared canon or auto-publishing.

## 2. Canon, checkpoint, branch and rejoin semantics

### Canon

Canon is the shared factual layer of the fictional world. Accepted canon
snapshots are **immutable and versioned**. A canonical fact cannot be changed
merely because a reader requests a preferred outcome.

### Canon checkpoint

A canon checkpoint is a versioned reference point in the canonical timeline.
A branch must reference exactly one canon checkpoint. Rejoin is allowed only
at an explicit compatible checkpoint.

### Personal branch

A personal branch is a reader-specific divergence from a canon checkpoint. It
references exactly one reader, one prior published episode, and one canon
checkpoint. Branch content may add local branch-only facts but cannot silently
rewrite canon facts.

### Rejoin

A branch may rejoin an approved canon checkpoint only when continuity rules
permit. Rejoin is **rejected** if it would discard unresolved branch
consequences without explanation.

## 3. First episode, choice, branch and feedback loop

```text
shared canon episode (free)
→ reader makes an explicit choice + optional short comment
→ choice/comment persisted (applied once)
→ personal branch episode generated (visibly reflects the choice)
→ continuity and world-state validation
→ pending_review (no auto-publication)
→ later branch may rejoin a compatible canon checkpoint
```

### First canon episode

- Title: "The City That Loses an Hour"
- One free shared opening episode.
- No fabricated applied-feedback record (first canon has no applied reader
  input).
- Establishes: world rules, characters, locations, clues, unresolved threads.

### Reader choice

At the end of the canon episode, the reader chooses how the protagonist
investigates. Example: "cautious investigation" focusing on one character.

### Personal branch

The next episode is generated as a personal branch that visibly applies the
stored reader choice/comment. The branch adds branch-only events and facts
but does not change shared canon.

## 4. Revenue hypothesis and evidence fields

- First canon episode: **free**.
- Four personal branch episodes offered for **KRW 4,900**.
- Payment integration and actual payment are out of scope. Only a
  privacy-safe evidence structure is required.

### Pilot evidence categories (no actual events claimed)

- invitation, consent, episode delivery, explicit choice, engagement,
  correction time, AI/infrastructure cost, revenue hypothesis.
- No payer identity, account/card data, credentials, or private reader text
  in export-safe evidence.

## 5. Authorship and AI disclosure policy

- The service discloses that AI materially generated or transformed text.
- Every episode records its generation provenance: provider, model, prompt
  version, task, latency, token usage, validation result.
- Episodes are labeled as `canon` or `personal_branch`.
- Reader input influence is recorded in the applied reader input field.

## 6. Copyright/IP policy

The first experiment uses **only original project-created characters,
settings, and story material**.

Prohibited:

- continuing an existing copyrighted novel, film, game, comic, or franchise;
- using protected character names or distinctive worlds;
- requesting close imitation of a living author's style;
- real persons, real companies, existing franchises, existing characters;
- training or publishing from unlawfully obtained full texts.

Deterministic validators enforce explicit prohibited references. They do not
prove literary quality or universal originality.

## 7. Privacy, deletion and publication rules

- No automatic publication or canon promotion. All episodes remain
  `pending_review` until explicit human publication.
- Deletion/revocation workflow for reader profile, choices, comments, and
  personal branches.
- Shared canon may remain only after personal linkage is removed according
  to the contract.
- No payer identity, account/card data, credentials, or private reader text
  in export-safe evidence.

## 8. Content boundaries and age classification

- Audience: Korean adult readers (18+).
- Near-future urban mystery genre.
- Prohibited content: sexual content involving minors, sexual violence,
  graphic torture, instructions facilitating real harm.
- Content classification field on every episode.

## 9. Success/failure metrics

### Success (Phase 1 scope — evidence structure only, no actual events)

- one free canon episode generated and validated;
- one personal branch generated from a stored reader choice;
- continuity validation passes;
- generation-run accounting is accurate;
- file-backed close/reopen preserves all state.

### Failure conditions

- readers cannot understand what is canon;
- personalization fragments the audience;
- reader choices produce only superficial wording changes;
- continuity correction consumes more time than human drafting;
- the premise or text is materially derivative of protected work.

## 10. Explicit non-goals

- no changes outside `apps/living-fiction/**`;
- no imports from sibling product apps;
- no shared-package extraction;
- no live external provider call;
- no public signup, OAuth, payment, email, social sharing, or recommendation
  feed;
- no final polished reader/admin UI beyond `/health` smoke boundary;
- no image generation, voice, music, or copyrighted-style imitation;
- no claim of actual readers, payment, revenue, or literary quality.

## 11. Relationship to Personal Edition and Living Travel

Living Fiction is a **conceptual sibling** of Personal Edition and Living
Travel. They share no runtime code. Each product workspace under `apps/` is
an independent revenue experiment with its own implementation, tests,
configuration, and evidence.

## 12. Canon and branch rules (enforced by implementation)

- accepted canon snapshots are immutable and versioned;
- a branch references exactly one reader, prior published episode, and canon
  checkpoint;
- branch content may add local branch-only facts but cannot silently rewrite
  canon facts;
- character identity, relationships, possessions, knowledge, injuries,
  locations, and unresolved clues remain consistent unless an explicit
  validated state delta changes them;
- a reader choice/comment may be applied once to one matching branch request;
- first canon episode has no fabricated applied-feedback record;
- a branch must visibly apply the stored reader input;
- rejoin is allowed only at an explicit compatible checkpoint and cannot
  erase unresolved branch consequences without explanation;
- failed generation leaves the last valid canon/branch state unchanged and
  reader input unapplied;
- no automatic canon promotion or publication.

## 13. Transaction, persistence and accounting

- branch episode creation and choice application commit together in one
  transaction;
- failures leave no orphan episode and do not consume reader input;
- duplicate/retry requests cannot create duplicate episode numbers or apply
  the same input twice;
- generation-run records store provider, model, prompt version, task,
  latency, retry count, token usage, validation result, and privacy-safe
  error category;
- retry usage/latency is aggregated correctly;
- file-backed close/reopen tests prove durable canon, branch, and accounting
  state.
