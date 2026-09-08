# Business 14 Documentation Index

This index separates **current authority** from **historical phase evidence** so old model lists, routing chains, credential assumptions, or pilot constraints cannot accidentally become current runtime policy.

## Current authority

Read these first for current B14 work:

1. [`B14_ROUTER_PLATFORM_AND_PADIEM_PROFILE.md`](B14_ROUTER_PLATFORM_AND_PADIEM_PROFILE.md) — current product/routing authority.
2. [`../README.md`](../README.md) — current implementation and issue map overview.
3. [`BUSINESS14_DECISION_LOG.md`](BUSINESS14_DECISION_LOG.md) — chronological decisions, including the 2026-09-08 Router Platform/Padiem-profile clarification.
4. [`BUSINESS14_LANGUAGE_POLICY.md`](BUSINESS14_LANGUAGE_POLICY.md) — Korean-first product language authority.
5. Current source/tests — final truth for executable catalog, provider adapters, errors, and endpoint behavior.

Precedence when documents disagree:

```text
CURRENT SOURCE + TESTS
  + B14_ROUTER_PLATFORM_AND_PADIEM_PROFILE.md
  > historical phase documents
```

## Current architecture summary

```text
B14 = General AI Router Platform
Padiem Routing Profile v1 = first product/customer-specific profile

Plus = kilo/poolside-laguna-s-2.1-free
Pro  = kilo/nvidia-nemotron-3-ultra-550b-a55b-free
Max  = HOLD

PADIEM_PROFILE_V1_AUTO_ROUTING = NO
PADIEM_USER_VISIBLE_AUTO = NO
PADIEM_SILENT_FALLBACK = NO
B14_GENERIC_AUTOROUTER = VALID_FUTURE_CAPABILITY
```

The shared Padiem profile declaration and B14 execution authority are separate. Product code declares intent; B14 decides whether that route is currently executable.

## Historical phase evidence

The following documents remain intentionally preserved. They describe earlier pilots and must be interpreted in their original phase/time context.

| Document | Classification | Current-use rule |
|---|---|---|
| `API_PROVIDER_PHASE0_CHARTER.md` | Historical Phase 0 product charter | Preserve original Korean AI API-provider thesis; not current catalog authority. |
| `PHASE1_BYOK_GATEWAY_CHARTER.md` | Historical Phase 1 charter | Single-provider BYOK pilot evidence; generic BYOK future work now follows current B14 architecture/issues. |
| `PHASE1_PILOT_RUNBOOK.md` | Historical Phase 1 runbook | Do not assume commands/endpoints/config are current without source verification. |
| `PHASE1_SECURITY_BOUNDARY.md` | Historical Phase 1 security record | Reuse security rationale where still applicable; current source/gates control runtime. |
| `PHASE2_MULTI_PROVIDER_CHARTER.md` | Historical Phase 2 charter | Evidence that multi-provider routing is part of B14 lineage; not current Padiem profile mapping. |
| `PHASE2_ROUTING_CONTRACT.md` | Historical Phase 2 routing contract | Explicit model→provider registry design evidence; current catalog/contracts supersede exact details. |
| `PHASE2_PILOT_RUNBOOK.md` | Historical Phase 2 runbook | Operational history only unless reconfirmed against current source. |
| `PHASE3_SESSION_WORKSPACE_CHARTER.md` | Historical Phase 3 charter | Workspace pilot history; B14 is not redefined as a consumer chat product. |
| `PHASE3_SESSION_SECURITY_CONTRACT.md` | Historical Phase 3 security record | Security evidence; validate current implementation separately. |
| `PHASE3_WORKSPACE_RUNBOOK.md` | Historical Phase 3 runbook | Operational history only unless reconfirmed. |
| `CLOUDFLARE_WORKER_DEPLOYMENT.md` | Deployment history/reference | Current Production deployment authority is the exact-SHA repository-owned gate, not an old manual procedure. |
| `providers/AGNES_AI_V1.md` | Provider research/evidence | Provider-specific historical evidence, not current route authority. |
| `providers/AGNES_AI_LOCAL_HANDOFF.md` | Provider handoff evidence | Historical/local integration note; never a credential or production activation authority. |
| `providers/README.md` | Provider-notes index | Supplementary only. |
| `providers/STATUS.md` | Provider-note status snapshot | Snapshot only; current route state must come from source/current issues. |

## Historical-document safety rules

When reading any historical file:

- old model IDs do not become executable by documentation reference;
- old `b14/auto` or fixed-chain descriptions do not authorize Padiem v1 auto-routing;
- retired routes do not regain authority;
- old BYOK/header/credential patterns do not override current secret boundaries;
- old deployment instructions do not authorize Production mutation;
- old endpoint lists must be verified against current source/tests.

Do not erase historical decisions simply because the runtime evolved. Add a current clarification here or in the Decision Log instead.

## Current issue ownership

```text
#2085 current B14/Padiem product objective
#2099 Padiem routing-profile source of truth — completed
#2100 Chat/Claw shared Padiem profile consumption
#2101 implicit b14/auto removal from Padiem-facing contracts
#2102 Padiem Max route evidence/selection
#2103 generic B14 BYOK/credential policy
#2104 Padiem Pro Nemotron evidence
#2107 future Padiem provider/model operator console
#1955 B14 exact-SHA Production deployment gate
```

Cross-product issues that merely consume or mention B14 do not become B14 route-policy authority.
