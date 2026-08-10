# B57 — Classic Literature Translation Visual Direction

Status: `DIRECTION_FROZEN`  
Verdict: `REDESIGN`

Preserve the review UX from PR #430: choose public-domain work → compare source/fidelity/modern versions → record translation judgments → choose review edition → finish. Replace the current generic light app/cards.

`OWNER_UI_APPROVED=false` remains unchanged.

## Evidence

- fresh publication-family audit run `31422640921`, artifact `9076026735`
- canonical `https://57-classic-literature-translation.pages.dev/`
- UX authority PR #430 head `930a8dc4c2d13c2537c723ee76eec8217983d8e3`
- current live is a beige shell with ordinary cards and a large heading; interaction is useful but visual product identity is weak.

## Product thesis

A reviewer chooses how a public-domain work should be translated by seeing exactly what each version preserves, modernizes or loses, then records the rationale for a review edition.

```text
SOURCE → PARALLEL TRANSLATIONS → LOSS / FIDELITY → DECISION LEDGER → REVIEW EDITION
```

Core object: **the parallel-text translation proof**.

## Reserved visual territory

**Translation Proof Workshop**

- source language and Korean versions in aligned proof columns
- line/phrase correspondence markers
- fidelity / modernization / loss annotations
- decision ledger attached to exact passages
- restrained publisher-proof material
- edition choice shown as a reviewed textual artifact

Avoid generic two-card comparison, old-library nostalgia, book-cover decoration, chat translation UI and automatic “best translation” scoring.

## Key surfaces

- Library: public-domain work and edition context.
- Compare: source + faithful + modern reading versions aligned by passage.
- Loss/Fidelity: semantic/rhythm/register changes annotated beside exact text.
- Ledger: user marks reasons, not preference scores.
- Review Edition: chosen translation strategy with disclosed simplifications/loss.

## Differentiation

- B11 = language learner reading support; B57 = expert/editorial translation judgment.
- B20 = personal narrative authorship; B57 = source-text fidelity.
- B58 = user's writing voice profile; B57 = translation strategy.

## Acceptance criteria

1. parallel text is the dominant visual object;
2. source-to-translation alignment is clear;
3. loss/fidelity notes attach to exact passages;
4. ledger records human reasoning;
5. no automatic winner/quality score;
6. Mobile uses stacked but synchronized passage groups, not detached cards;
7. public-domain and no-model-call boundaries remain visible and functional.
