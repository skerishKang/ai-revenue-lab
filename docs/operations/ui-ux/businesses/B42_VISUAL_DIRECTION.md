# B42 — AI Development Control Tower Visual Direction

Status: `DIRECTION_FROZEN` · Verdict: `REDESIGN`

Fresh systems audit: run `31422952294`, artifact `9076111540`, canonical `https://42-ai-development-control-tower.pages.dev/`. This is one product where a dense control-tower metaphor is justified, but the current generic light-card template does not deliver it.

`OWNER_UI_APPROVED=false` remains unchanged.

## Product thesis

A human operator sees development work, evidence, blockers and review state together, judges what needs attention and produces an operations summary.

```text
WORK QUEUE → EVIDENCE → JUDGMENT → OPS SUMMARY
```

Core object: **the development operations map / evidence-linked work queue**.

## Reserved territory — Development Control Tower

- dense but legible work queue
- dependency/blocker topology
- evidence/check state attached to work items
- exception/risk surfaced by operational consequence
- human judgment lane and concise ops summary

A dark or technical surface is allowed here if it improves dense operational reading; it must still be distinct from B06's world-signal room and B14's single-session workspace.

Avoid decorative radar, generic KPI dashboard and current equal-card prototype.

## Acceptance criteria

1. many work items/dependencies can be scanned without losing hierarchy;
2. evidence is linked to exact work items;
3. blockers/exceptions have operational context;
4. human judgment and summary remain explicit;
5. Mobile becomes a prioritized ops queue, not a shrunk desktop tower;
6. visually distinct from B06/B14/B43/B52/B55.
