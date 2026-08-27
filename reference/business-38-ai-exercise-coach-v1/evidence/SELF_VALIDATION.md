# Implementation Self-Validation

Date: 2026-07-29

Status: implementation self-check only. This is **not** independent `LOCAL_VALIDATION_PASS` and does not constitute `UI_APPROVED`.

## Method and browser limitation

The sandbox blocked both `http://127.0.0.1:4173/index.html` and `file://` navigation with `ERR_BLOCKED_BY_ADMINISTRATOR`. The same `index.html`, local CSS, local JavaScript and 13 local SVG files were therefore assembled into one in-memory document and exercised in headless Chromium as the explicitly permitted inline fallback.

A separate independent localhost run remains required before `LOCAL_VALIDATION_PASS` may be declared.

## Static contract tests

Command: `node --test tests/contract.test.mjs`

Result: 6 passed, 0 failed.

Covered:

- exact seven states;
- all required authority labels;
- 13 original local SVG assets and deterministic asset token;
- actual final-element `animationend` authority and no fixed completion timeout;
- keyboard navigation and roving `tabIndex`;
- no external runtime URL in HTML/CSS/JavaScript.

## Browser matrix

Validated 7 states × 3 viewports = 21 combinations:

- 1440×1100;
- 768×1024;
- 390×844.

For every combination:

- selected state exactly 1;
- visible panel exactly 1;
- `aria-selected` and roving `tabIndex` correct;
- horizontal overflow 0;
- Korean/English clipping detected 0;
- visible SVG render failures 0;
- console errors 0;
- page errors 0;
- failed requests 0;
- external runtime requests 0.

## Keyboard

- ArrowRight from cover → profile;
- End → mobile;
- Home → cover;
- focus remains on the active tab.

## Motion

Replay 1 and Replay 2:

- final animation name: `motionFinal`;
- computed duration: `0.1s`;
- computed delay: `0.68s`;
- nominal completion: `0.78s`;
- completion authority: `animationend:motionFinal`;
- final computed style equality: pass;
- final geometry equality: pass;
- replay-button focus stable: pass;
- scroll position stable: pass.

Reduced motion:

- immediate information-complete state;
- authority: `reduced-motion-immediate`;
- persistent labels retained: `UNKNOWN / NOT ASSESSED`, `STOP OR PAUSE CONDITION`, `NOT MEDICAL ADVICE`, `REGRESSION OPTION`.

## Mobile first screen

At 390×844 the following are all contained within the first viewport:

- current movement;
- general form cue;
- regression option;
- exertion check;
- stop/pause boundary;
- next human review;
- non-medical and non-rehabilitation disclosure.

## Phase state

`UI_REVIEW_READY`  
`NOT_VALIDATED_BY_LOCAL`  
`NOT_DEPLOYED_PENDING_UI_APPROVAL`  
`UX_NOT_STARTED`  
`BACKEND_FROZEN`
