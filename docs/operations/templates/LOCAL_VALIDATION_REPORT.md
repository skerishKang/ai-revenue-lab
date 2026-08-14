# Independent Local Validation Report

## Revision identity

- Repository:
- PR:
- Expected exact head:
- Actual tested exact head:
- Match? yes/no:
- Repository/worktree state before validation:

## Independence

- Implementation actor:
- Validator actor:
- Same actor? **If yes, this report is not independent validation.**
- Product source modified during validation? yes/no:

If product source was modified, stop and return the new revision to implementation. Do not label the modified run independent `PASSED` evidence.

## Environment

- OS:
- Runtime/toolchain:
- Browser/version:
- Hardware/local service/provider when relevant:
- Font/runtime conditions relevant to rendered typography:

## Commands and results

| Command / journey | Result / exit | Evidence |
|---|---|---|
| | | |

## Visual gate under validation

- N/A / ANCHOR / ARCHETYPE_SYSTEM / FULL_SURFACE / FOCUSED_POLISH:
- Product Visual Thesis/reference evidence supplied:
- Expected anchor route/state:
- Expected archetypes:

## Browser / visual evidence

For applicable visual work record:

- Desktop viewport(s)/states:
- 390px Mobile states:
- Anchor screenshots:
- Archetype screenshots:
- Side-by-side/contact-sheet artifact:
- Full-surface contact sheet, if applicable:
- Reduced motion:
- Keyboard/focus:
- Horizontal overflow:
- Console errors:
- Page errors:
- Failed required requests/assets:
- External requests:

## Visual conformance matrix

| Criterion | Verdict | Notes/evidence |
|---|---|---|
| Reference translation | MATCH / PARTIAL / MISS / N/A | |
| Product identity | MATCH / PARTIAL / MISS / N/A | |
| First-viewport hierarchy | MATCH / PARTIAL / MISS / N/A | |
| Korean typography | MATCH / PARTIAL / MISS / N/A | |
| Asset/material quality | MATCH / PARTIAL / MISS / N/A | |
| Interaction clarity | MATCH / PARTIAL / MISS / N/A | |
| Mobile composition | MATCH / PARTIAL / MISS / N/A | |
| Cross-state coherence | MATCH / PARTIAL / MISS / N/A | |
| Generic UI fallback absent | MATCH / PARTIAL / MISS / N/A | |
| Legacy/cascade leakage absent | MATCH / PARTIAL / MISS / N/A | |

If validating an archetype/full-surface gate, individual screens that look acceptable in isolation do not pass when the set visibly belongs to different design systems.

## Source/cascade observations when supplied

- Active visual entrypoints consistent with expected current system? yes/no/N/A:
- Visible evidence of old-generation leakage:
- Suspicious typography fallback:
- Broken/missing asset source:

## Failure reproduction

For each failure:

- expected:
- actual:
- exact action:
- error/status:
- reproduction:
- likely failure class if visual: concept / reference / anchor / archetype / typography / asset / legacy shell / cascade / mobile:

Do not prescribe a new art direction merely because a later surface failed; report the observation and evidence.

## Secret/private-data check

- Secret leakage:
- Private data leakage:
- Sanitization notes:

## Validation disposition

```text
PASSED / FAILED / BLOCKED / INVALIDATED_BY_NEW_REVISION
```

Also record the evidence-supported visual gate verdict when applicable, but do not claim owner approval.

This report is evidence for Web CTO review; it is not the final CTO readiness verdict.
