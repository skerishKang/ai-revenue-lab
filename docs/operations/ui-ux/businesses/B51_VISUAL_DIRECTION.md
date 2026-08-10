# B51 — AI Workflow Marketplace Visual Direction

Status: `DIRECTION_FROZEN` · Verdict: `REDESIGN`

Fresh systems audit: run `31422952294`, artifact `9076111540`, canonical `https://51-ai-workflow-marketplace.pages.dev/`. Current generic cards reproduce the systems template and also risk a generic app-store grid.

`OWNER_UI_APPROVED=false` remains unchanged.

## Product thesis

A user finds a bounded workflow package, inspects inputs/outputs/permissions and risks, checks installation requirements and only then forms an apply/install plan.

```text
FIND → PACKAGE DETAIL → PRE-INSTALL CHECK → APPLY PLAN
```

Core object: **the workflow package contract**, not the marketplace card.

## Reserved territory — Workflow Package Shelf

- package modules/shelves organized by job
- each package exposes inputs, outputs, permissions, required connectors and human gates before install
- detail sheet is stronger than discovery grid
- compatibility/pre-install checklist attached to package

Avoid app-store marketing, popularity rankings, logo wall, generic marketplace cards and one-click install spectacle.

## Acceptance criteria

1. package contract is visible before install/action;
2. permissions/connectors/outputs are easy to compare;
3. pre-install incompatibilities are explicit;
4. no popularity or “best workflow” visual bias;
5. generic systems card template is replaced;
6. Mobile prioritizes package contract over marketplace browsing;
7. current no-install/backend boundaries remain intact.
