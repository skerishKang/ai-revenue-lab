# B53 — Embedded AI SDK Visual Direction

Status: `DIRECTION_FROZEN` · Verdict: `REDESIGN`

Fresh systems audit: run `31422952294`, artifact `9076111540`, canonical `https://53-embedded-ai-sdk.pages.dev/`. Current generic cards do not make embedding/host compatibility visually legible.

`OWNER_UI_APPROVED=false` remains unchanged.

## Product thesis

A host product defines an insertion point and interface contract; compatibility is checked and a bounded integration specification is produced.

```text
HOST → INSERTION SLOT → IO / PERMISSION CONTRACT → COMPATIBILITY → INTEGRATION SPEC
```

Core object: **the host application frame with an explicit embedded slot and contract overlay**.

## Reserved territory — Host Insertion Frame

- simplified host product frame
- insertion region visibly highlighted
- input/output/events/permissions around the slot
- compatibility issues attached to exact interface edge
- final integration spec derived from the frame

Avoid API-docs marketing page, code-only console, generic cards and B49 schema-map duplication.

## Acceptance criteria

1. host + insertion slot visible immediately;
2. IO/events/permissions attach to the slot;
3. compatibility errors have exact interface context;
4. final spec preserves host/SDK boundaries;
5. generic systems template is replaced;
6. Mobile shows host→slot→contract sequentially;
7. current no-runtime-integration boundaries remain intact.
