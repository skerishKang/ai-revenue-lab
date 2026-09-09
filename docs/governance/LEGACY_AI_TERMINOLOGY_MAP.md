# Legacy AI Documentation Terminology Map

```text
DOC_STATUS = CANONICAL_GOVERNANCE
OWNER = repository documentation governance
SCOPE = interpretation of legacy Padiem AI names and route/profile terminology
LAST_VERIFIED = 2026-09-08
```

This document prevents historical terminology from being mistaken for current architecture or route authority.

## Current canonical identities

```text
IP-CORE     = Padiem AI Core
IP-ENGINE   = Padiem AI Engine
IP-CONTROL  = Padiem Control Plane
IP-SIDECAR  = Padiem Embedded AI Runtime [proposed / separately activated]
B14         = Korean AI Platform / general AI Router Platform
B62         = Padiem Chat
B54         = Padiem Claw / Korean AI Code Agent
B61         = StoryMemory
B53         = Padiem Sidecar commercial product
```

## Legacy identifier mapping

| Legacy / historical term | Current interpretation | Rule |
|---|---|---|
| `P01`, `Padiem Core P01` | `IP-CORE` | historical alias only; do not use as current platform ID |
| `LOW / MEDIUM / HIGH` B62 profiles | historical Chat model-profile vocabulary | not current Plus/Pro/Max route authority |
| `MEDIUM -> Laguna` | historical intermediate assignment | superseded by current Padiem Plus/Pro/Max declaration |
| `LOW/HIGH UNASSIGNED` | historical B62 state | superseded for current product routing documentation |
| `b14/auto` as ordinary product default | compatibility/history concept | current Padiem Profile v1 must not silently use it |
| MiniMax M3 / Tencent HY3 in current Padiem tier lists | retired historical lanes | must not re-enter current executable product tiers through stale docs |
| Phase 0/1/2/3 Provider/model lists | dated phase evidence | do not treat as current B14 catalog truth |
| `Sidecar` used ambiguously | must distinguish B53 vs IP-SIDECAR | B53 is commercial product; IP-SIDECAR is reusable embedded runtime candidate |

## Current Padiem route vocabulary

Current shared product-level declaration is expressed as:

```text
Padiem Plus = Laguna
Padiem Pro  = Nemotron
Padiem Max  = HOLD

USER_VISIBLE_AUTO = NO
SILENT_FALLBACK = NO
```

Exact route IDs and current executability must be verified from current source:

```text
packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py
apps/korean-ai-platform/app/pilot/**
```

## Historical-document rule

A historical document is not wrong merely because it contains the old terminology that was correct at its recorded date. It becomes a problem only if it is presented as current authority.

Therefore:

```text
HISTORICAL TERM IN DATED SNAPSHOT = ALLOWED
HISTORICAL TERM AS CURRENT AUTHORITY = NOT ALLOWED
```

When a historical or issue-specific document conflicts with current architecture, use this precedence:

```text
1. current merged executable contract / source for volatile runtime facts
2. canonical architecture and registries
3. current product/component README
4. accepted ADR
5. dated audit/evidence snapshot
6. historical issue/PR discussion
```

## Canonical references

- `docs/README.md`
- `docs/architecture/PADIEM_AI_VERTICAL_STACK.md`
- `docs/architecture/PADIEM_AI_CAPABILITY_OWNERSHIP_REGISTRY_v1.md`
- `docs/internal-platform/INTERNAL_PLATFORM_REGISTRY.md`
- `docs/product/AI_PRODUCT_CONSUMER_MATRIX.md`
- `docs/governance/DOCUMENTATION_AUTHORITY_MODEL.md`
