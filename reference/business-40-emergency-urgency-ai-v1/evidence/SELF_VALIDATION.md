# Implementation self-validation

Date: 2026-07-29  
Scope: `reference/business-40-emergency-urgency-ai-v1/**`  
Status: implementation self-check only — **not** independent `LOCAL_VALIDATION_PASS`.

## Matrix

- 7 exact states × 3 viewports = 21 combinations.
- Viewports: 1440×1100, 768×1024, 390×844.
- Exactly one selected tab and one visible panel in every combination.
- `aria-selected`, roving `tabIndex`, ArrowLeft/ArrowRight/Home/End and Enter/Space navigation implemented.
- Horizontal document overflow: 0 in all 21 combinations.
- Korean/English label overlap: no observed failure in generated captures.
- The 390px `mobile` state keeps source, uncertainty, conflict, missing information, clarification, provisional status, human-only authority and no-dispatch boundary inside the first 844px viewport.
- 12 repository-local original SVG assets are referenced and rendered in the inline browser fallback.
- Console errors: 0. Page errors: 0. Failed requests: 0. External runtime requests: 0.

## High-stakes boundary check

- Source statement remains unverified and separated from verified fact.
- Observable indicator remains separated from interpretation.
- Confidence is labeled as not certainty.
- No single urgency score or autonomous priority output exists.
- Missing information is explicitly not negative evidence.
- Conflicting evidence and unresolved uncertainty remain visible after motion completion.
- Provisional rationale is separated from final human authority.
- No diagnosis, threat prediction, dispatch, resource allocation or emergency advice is present.
- No protected/proxy characteristic is used.
- No response-time, survival, safety or correctness guarantee is made.

## Motion check

- Completion authority: actual final-element `animationend`.
- No fixed completion timeout.
- Nominal completion: 760 ms.
- Replay 1/2 computed styles and geometry: equal.
- Focus: stable on replay control.
- Scroll: stable.
- Reduced motion: immediate information-complete state.

## Browser limitation and fallback

The implementation environment allowed the localhost server process to start and respond to Python, but Chromium navigation to `127.0.0.1` was blocked by administrator policy (`ERR_BLOCKED_BY_ADMINISTRATOR`). Per the execution contract, validation used an **inline fallback** that embedded the local CSS, JavaScript and all SVG assets into the same document. The inline fallback completed the 21-combination, replay, geometry, focus, scroll, reduced-motion and error checks.

Independent localhost browser validation is still required. This implementation self-check must not be reported as `LOCAL_VALIDATION_PASS`.
