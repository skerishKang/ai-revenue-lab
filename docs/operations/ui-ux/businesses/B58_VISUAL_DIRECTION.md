# B58 — Personal Writing Voice Visual Direction

Status: `DIRECTION_FROZEN`  
Verdict: `REDESIGN`

Preserve PR #431's deterministic UX: select multiple fictional samples → inspect adjustable voice features → compare synthetic drafts → review use/prohibition/control trace → finish. Replace the generic light card application.

`OWNER_UI_APPROVED=false` remains unchanged.

## Evidence

- fresh publication-family audit run `31422640921`, artifact `9076026735`
- canonical `https://58-personal-writing-voice.pages.dev/`
- UX authority PR #431 head `135a0cd0901ca132346ad2d1e1537d1c6fef8444`

## Product thesis

The user's writing voice is not one opaque score. Multiple source samples produce an inspectable, adjustable voice profile that the user can compare across drafts and control or discard.

```text
SAMPLES → VOICE FEATURES → ADJUST → DRAFT COMPARISON → USER CONTRACT
```

Core object: **the textual voice fingerprint and side-by-side draft differences**.

## Reserved visual territory

**Writing Voice Studio / Sample Wall**

- source samples pinned as readable text fragments
- sentence length/rhythm/directness/detail features visualized as textual traces, not personality scores
- adjustable sliders connected to immediate prose preview
- multiple draft columns with sentence-level differences
- user-control/prohibition contract as final proof layer

Avoid generic three-card grids, radar/personality charts, living-author mimicry, AI chat, “100% your voice” claims and opaque embedding/model language.

## Reference translation

Adopt from editorial style guides and writing revision tools:
- show evidence in actual sentences
- treat style as several adjustable dimensions
- compare outputs before committing

Reject:
- biometric/personality metaphor
- author-cloning spectacle
- black-box similarity percentage

Translate:
- writing samples form a visible textual fingerprint; changing a feature immediately changes a deterministic draft and its explanation.

## Key surfaces

- Samples: multiple source voices/context visible.
- Profile: features linked to sample evidence.
- Adjustment: controls and prose preview together.
- Draft Compare: three distinct drafts with highlighted changes.
- Contract/Trace: use scope, prohibitions, selected samples and current parameters.

## Differentiation

- B20 = authoring a narrative from memories; B58 = controlling stylistic characteristics.
- B57 = translation fidelity; B58 = writing voice.
- B12 = multi-format creator production; B58 = prose-style profile.

## Acceptance criteria

1. actual sentences, not cards/scores, are the dominant evidence;
2. feature controls are traceable to sample text;
3. draft changes are visible at sentence level;
4. no real/living author imitation affordance;
5. user can adjust/discard profile clearly;
6. Mobile keeps sample → feature → draft relation understandable;
7. all no-training/no-persistence/no-publishing boundaries remain intact.
