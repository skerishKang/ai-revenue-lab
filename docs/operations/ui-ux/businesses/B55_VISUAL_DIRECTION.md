# B55 — Local AI Fleet Visual Direction

Status: `DIRECTION_FROZEN` · Verdict: `REDESIGN`

Fresh systems audit: run `31422952294`, artifact `9076111540`, canonical `https://55-local-ai-fleet.pages.dev/`. Current generic light cards do not communicate physical/local fleet state and visually duplicate the systems family.

`OWNER_UI_APPROVED=false` remains unchanged.

## Product thesis

A human operator sees available local devices, assigns/inspects bounded tasks, understands capacity/availability/incidents and makes the operational judgment.

```text
FLEET → TASK → CAPACITY / AVAILABILITY → INCIDENT → OPS JUDGMENT
```

Core object: **the local hardware topology and capacity state**.

## Reserved territory — Local Hardware Topology

- physical device/node identity
- topology/connection only where real to contract
- capacity, temperature/load or availability shown as bounded operational state
- task assignment attached to devices
- incident/degraded state visible without “AI cloud” abstraction

Avoid model leaderboard, dark engine-room spectacle, generic server cards and B42 control-tower duplication.

## Differentiation

B42 = work/evidence across development operations. B52 = scheduled agent runbook. B55 = local physical compute/device fleet.

## Acceptance criteria

1. devices/topology are primary visual objects;
2. task and capacity state attach to exact device;
3. degraded/unavailable state is explicit;
4. human operations judgment remains final;
5. generic systems template is gone;
6. Mobile provides prioritized device/task status rather than shrunk topology;
7. current local-only/operational boundaries remain intact.
