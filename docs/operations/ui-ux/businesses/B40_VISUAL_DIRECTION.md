# B40 — Emergency Urgency AI Visual Direction

Status: `DIRECTION_FROZEN` · Verdict: `REDESIGN`

Fresh systems audit: run `31422952294`, artifact `9076111540`, canonical `https://40-emergency-urgency-ai.pages.dev/`. Current generic card template does not express the product's most important authority boundary.

`OWNER_UI_APPROVED=false` remains unchanged.

## Product thesis

Reported facts are separated into known, unknown and AI-derived urgency signals before a human makes the actual triage/dispatch decision.

```text
INTAKE → KNOWN / UNKNOWN → AI SIGNALS → HUMAN DECISION → HANDOFF
```

Core object: **the Known / Unknown triage board**.

## Reserved territory — Known / Unknown Triage Board

- confirmed facts and missing facts visually separate
- AI signal clearly subordinate to facts
- uncertainty/caveats visible beside signal
- human decision area has final authority
- restrained caution color, not red panic scoring

Avoid autonomous severity dial, red danger leaderboard, opaque risk score and generic cards.

## Acceptance criteria

1. known vs unknown facts are immediately distinguishable;
2. AI signals never look like final triage authority;
3. human decision/handoff is visibly final;
4. missing information cannot disappear after scoring;
5. Mobile preserves fact→signal→human order;
6. current emergency/safety boundaries remain intact.
