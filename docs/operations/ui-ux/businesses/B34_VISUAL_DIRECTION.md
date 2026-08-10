# B34 — AI Dubbing Studio Visual Direction

Status: `DIRECTION_FROZEN · REVIEW_AUTHORITY`  
Verdict: `REDESIGN_ART_LAYER`

Preserve the rights-first deterministic journey and safety boundary. Replace the generic light cards with a dubbing-specific production/review environment.

`OWNER_UI_APPROVED=false` remains unchanged.

## Evidence

- fresh platform-family audit run `31422928265`, artifact `9076118820`
- canonical `https://34-ai-dubbing-studio.pages.dev/`
- review authority PR #412 head `4e77ce30ffc266997ba26fa55fd835c6fca32c85`
- journey: rights checks → segments/timing → non-real-person synthetic voice direction → human review → finish.

## Product thesis

A dubbing job is allowed to proceed only after rights are explicit, segments/timing are visible, a non-real-person synthetic voice direction is chosen and human review confirms meaning/timing/identity boundaries.

Core object: **rights slate + segment timeline + synthetic voice direction**.

## Reserved territory — Rights-First Dubbing Suite

- opening rights slate/check sheet
- horizontal segment/timing track
- script/meaning beside each segment
- synthetic voice direction as tonal palette, not celebrity/avatar picker
- review storyboard with meaning/timing/identity checks

Avoid generic cards, waveform spectacle, real-person likeness, voice-cloning UI and editing software imitation.

## Key surfaces

- Rights: 3 explicit rights checks as a production slate.
- Segments: duration/timing is visual and comparable.
- Voice: abstract tonal direction; no real-person identity.
- Review: segment + script + selected direction remain in context while human checks complete.

## Differentiation

B34 is rights/timing/synthetic-voice review. B22 is multi-media story production. B39 is live bilingual emergency interpretation.

## Acceptance criteria

1. rights state dominates before any voice selection;
2. segment timing is a real visual timeline, not text cards;
3. voice directions cannot imply real-person imitation;
4. review retains meaning/timing/identity context;
5. generic light prototype shell is replaced;
6. Mobile keeps rights→segments→voice→review order;
7. no actual audio generation/persistence/backend behavior is introduced by visual redesign.
