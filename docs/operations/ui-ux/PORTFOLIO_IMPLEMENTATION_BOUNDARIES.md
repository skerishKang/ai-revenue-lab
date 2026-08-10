# AI Revenue Lab — UI/UX Implementation Boundaries

Status: `AUTHORITATIVE_PROGRAM_BOUNDARY`

Purpose: prevent future UI workers from treating every numbered slot as an internal web implementation target.

Creation baseline:

```text
origin/main = a631122888d30c5a8a62f4b27e192967da331898
```

The repository truth layer remains the authority for lineage. This document states how the new visual-governance program handles those entries.

## No internal web build

| B# | Classification | Successor / authority | Program action |
|---:|---|---|---|
| 03 | external / parallel track | external/parallel work | **DO NOT BUILD internally**; record lineage only |
| 05 | expanded successor | DanjiOn / `skerishKang/02-danji-on` | **DO NOT BUILD internally** |
| 23 | external implementation | LoveBud | **DO NOT BUILD internally** |
| 24 | external implementation | LoveTree | **DO NOT BUILD internally** |
| 25 | external implementation | Love Matchmaking | **DO NOT BUILD internally** |
| 26 | integrated successor | Ieeon | **DO NOT BUILD internally** |
| 27 | integrated successor | Sasillo | **DO NOT BUILD internally** |
| 28 | integrated successor | Ieeon | **DO NOT BUILD internally** |
| 30 | expanded successor | 400 AI Finder / `skerishKang/400-ai-finder` | **DO NOT BUILD internally** |
| 31 | integrated successor | Sasillo | **DO NOT BUILD internally** |
| 50 | integrated successor | Ieeon | **DO NOT BUILD internally** |

These entries may be represented truthfully in Portfolio Console with successor/external links where authority is known. Missing successor links must not be invented.

## Non-web

### B54 — AI Model Router

Classification:

```text
CLI / TUI
```

Review authority is non-web. Do not create a website merely to satisfy the visual audit program.

If a later review is required, define a separate CLI/TUI legibility and interaction standard. Web screenshot requirements are `NOT_APPLICABLE` unless a separately authorized web surface is created.

## Intentional numbering gap

### B56

B56 is an intentional numbering gap / no current Business implementation authority.

```text
DO NOT INVENT BUSINESS 56
DO NOT CREATE PLACEHOLDER PRODUCT
```

If future authoritative portfolio data assigns B56, update the truth layer and this boundary document first.

## Protected / special authority reminders

- B29: protected Guided Tutorial authority; preserve its explicit source/merge boundary.
- B32–B35 and other numbered review surfaces may be unmerged review authorities. A visual redesign direction document does not grant permission to mutate or merge those source branches.
- B44: Portfolio Console is an internal special product. Its live browser conformance is currently pending because the headless audit reached a Cloudflare security verification challenge rather than the product.

## Program rule

A future worker must classify the Business **before** opening an implementation branch.

```text
INTERNAL WEB + DIRECTION_FROZEN
    → eligible later for numbered implementation

EXTERNAL / SUCCESSOR
    → no internal implementation

NON_WEB
    → use medium-specific review

NUMBERING GAP / UNKNOWN
    → resolve authority first
```

No visual-governance document changes `OWNER_UI_APPROVED` by inference.
