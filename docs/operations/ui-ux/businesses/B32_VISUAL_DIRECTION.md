# B32 — AI Skill Studio Visual Direction

Status: `DIRECTION_FROZEN · REVIEW_AUTHORITY`  
Verdict: `REDESIGN_ART_LAYER`

Preserve the exact review-authority interaction/state machine; do not casually mutate the unmerged authority. Future visual implementation must follow this direction on a separately authorized path.

`OWNER_UI_APPROVED=false` remains unchanged.

## Evidence

- fresh platform-family audit run `31422928265`, artifact `9076118820`
- canonical `https://32-ai-skill-studio.pages.dev/`
- review authority PR #354 head `73ec4718d0835248ab20d56bc68f3956536112b4`
- proven journey: task → input/evidence → missing/conflict → draft → review/reject/correct → rerun → approve → save skill.

Current beige workbench is functional but visually generic and first real work lands too low on Mobile.

## Product thesis

A bounded organizational task becomes a reusable skill only after evidence gaps/conflicts, human correction and final approval are explicitly resolved.

Core object: **task + evidence bench + saved skill artifact**.

## Reserved territory — Skill Evidence Bench / Skill Foundry

- active workbench with task contract pinned visibly
- evidence pieces grouped as present/missing/conflicting
- draft/correction changes linked to evidence
- human review seal/gate
- final skill card/package looks reusable, not magical

Avoid generic AI workflow cards, chat, beige training poster and autonomous “skill generated” celebration.

## Key surfaces

- Task bench: current task/inputs immediately visible.
- Evidence: missing/conflict conditions spatially obvious.
- Draft/correction: exact changes tied to evidence.
- Review: reject/approve is a human gate.
- Saved skill: reusable scope/input/output limits visible.

## Differentiation

B14 runs AI sessions; B32 builds a reusable skill from evidence. B43 assembles software work contracts; B32 is organizational task knowledge.

## Acceptance criteria

1. task/evidence appears in first Mobile work viewport;
2. missing/conflict states have visual authority;
3. correction visibly changes the draft;
4. human review remains mandatory;
5. saved skill shows scope and evidence lineage;
6. generic beige-card prototype identity is replaced;
7. exact existing state machine remains intact.
