# Korean AI Platform — Business 14

## Current authority

Business 14 (**B14**) is Padiem's **general AI Router Platform**: a Korean-first provider/model execution layer that can register multiple providers and models, validate executable routes, bind credentials safely, dispatch requests, normalize provider behavior, and evolve toward capability/cost/latency/availability-aware routing.

The current production-oriented product work is narrower than the full platform mission:

```text
B14 = General AI Router Platform
Padiem Routing Profile v1 = first product/customer-specific routing profile
```

Padiem has already selected the routes it wants for the current MVP. Therefore Padiem Profile v1 does not require a generic automatic best-model router to be active.

```text
Padiem Plus = kilo/poolside-laguna-s-2.1-free
Padiem Pro  = kilo/nvidia-nemotron-3-ultra-550b-a55b-free
Padiem Max  = HOLD

PADIEM_PROFILE_V1_AUTO_ROUTING = NO
PADIEM_USER_VISIBLE_AUTO = NO
PADIEM_SILENT_FALLBACK = NO

B14_GENERIC_AUTOROUTER = VALID_FUTURE_CAPABILITY
```

**Important:** the Padiem v1 explicit-route policy is a customer/profile decision, not a permanent B14-wide prohibition on automatic routing. B14's long-term roadmap still includes route scoring/selection, capability-aware routing, cost/latency/availability optimization, bounded fallback/retry, BYOK, direct/OpenAI-compatible provider connections, and additional customer/product routing profiles.

Canonical current charter: [B14 Router Platform & Padiem Routing Profile](docs/B14_ROUTER_PLATFORM_AND_PADIEM_PROFILE.md).

## Authority boundaries

```text
Padiem product/profile declaration
  -> shared product_tier_routes contract
  -> B14 catalog/executability validation
  -> provider/model dispatch
  -> normalized response/error/evidence
```

- Shared Padiem tier declaration: `packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py`
- B14 provider/model execution authority: `apps/korean-ai-platform/app/pilot/**`
- Chat/Claw consume the Padiem profile; they must not become provider/model route authorities.
- A declared route that is retired, unregistered, unavailable, or lacks required credential readiness must fail closed.
- Raw provider credentials must never appear in product-facing route contracts, browser state, logs, or committed documentation.

## Current route state

| Padiem tier | Route | Status |
|---|---|---|
| Plus | `kilo/poolside-laguna-s-2.1-free` | explicit / executable when B14 catalog permits |
| Pro | `kilo/nvidia-nemotron-3-ultra-550b-a55b-free` | explicit / executable when B14 catalog permits |
| Max | `padiem-profile/max-hold` | HOLD / non-executable |

Retired historical routes such as MiniMax M3 and Tencent HY3 must not re-enter the executable catalog or a Padiem tier through stale documentation, fallback, or compatibility defaults.

## Router Platform roadmap

B14's general platform remains free to evolve beyond the current Padiem profile. Valid future platform work includes:

- manual provider/model selection;
- product/customer-specific routing profiles;
- generic automatic route selection;
- capability-aware routing;
- cost/latency/availability-aware optimization;
- bounded and policy-controlled fallback/retry;
- provider portfolio management;
- BYOK and platform-managed credential references;
- OpenAI-compatible and direct provider adapters;
- route evidence, usage and cost observation;
- operator/admin route management;
- additional Korean/domestic/local/self-hosted model access where commercially and technically justified.

Future auto-routing must be explicit, versioned, observable, policy-bounded, and distinguishable from profile-specific explicit routing. An omitted product model must not silently become `b14/auto`.

## Korean-first product policy

- Primary market: Korea.
- Canonical/default product locale: Korean (`ko-KR`).
- English is an explicit secondary locale where provided.
- Provider/model/API identifiers may remain standard English; user-facing explanations default to Korean.

See [Business 14 Product Language Policy](docs/BUSINESS14_LANGUAGE_POLICY.md).

## Historical phase documents

The repository contains Phase 0–3 charters/runbooks from B14's earlier product-development stages. They are retained as **historical design and implementation evidence**. They do not override the current charter or current executable catalog.

Historical lineage includes:

- Phase 0 Korean AI API Provider concept/demo
- Phase 1 single-provider BYOK Gateway pilot
- Phase 2 multi-provider registry/routing pilot
- Phase 3 Korean-first session workspace pilot
- provider-specific research/handoff notes

When a historical document contains an old model list, old chain, old credential assumption, or old route policy, treat it as evidence of that phase only. Current route/executability truth comes from current source + the current B14/Padiem charter.

## Runtime modes

B14 retains deterministic mock/testing support and live provider execution paths implemented by current source.

Typical local start:

```bash
cd apps/korean-ai-platform
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Useful local surfaces may include the workspace and pilot APIs exposed by the current application. Always verify endpoint availability against current source/tests rather than historical phase docs.

## Security boundary

- Provider origins/endpoints are server-controlled and validated.
- Redirect/timeout/response-size policies fail closed.
- Provider secrets remain server-side and are never returned to the browser.
- Credential values are never committed.
- Product route declarations contain identities/references, not secret values.
- Unknown, retired, disabled, or unsupported routes fail closed.
- Production mapping/deployment changes require their own accepted gate.
- A credential being available does not itself authorize a route selection.
- A route being selected does not itself authorize silent fallback.

## Testing

Primary B14 suite:

```bash
cd apps/korean-ai-platform
python -m pytest -q
```

Run the repository's current targeted/integration/browser suites appropriate to the changed slice. Tests that use deterministic transports do not prove live provider availability; live evidence is tracked separately and must use synthetic/non-sensitive inputs unless explicitly authorized otherwise.

## Production/release rule

Source merge and Production activation are separate events.

A B14 Production release must use the repository-owned exact-SHA deployment gate and verify the current `main` SHA before mutation. Production claims require post-deploy version/readback and bounded first-party smoke evidence. See issue #1955 and the current repository workflow for the authoritative release contract.

## Documentation index

### Current authority

- [B14 Router Platform & Padiem Routing Profile](docs/B14_ROUTER_PLATFORM_AND_PADIEM_PROFILE.md)
- [Business 14 Product Language Policy](docs/BUSINESS14_LANGUAGE_POLICY.md)
- [Business 14 Decision Log](docs/BUSINESS14_DECISION_LOG.md)

### Historical phase evidence

- [API Provider Phase 0 Charter](docs/API_PROVIDER_PHASE0_CHARTER.md)
- [Phase 1 BYOK Gateway Charter](docs/PHASE1_BYOK_GATEWAY_CHARTER.md)
- [Phase 1 Pilot Runbook](docs/PHASE1_PILOT_RUNBOOK.md)
- [Phase 1 Security Boundary](docs/PHASE1_SECURITY_BOUNDARY.md)
- [Phase 2 Multi-Provider Charter](docs/PHASE2_MULTI_PROVIDER_CHARTER.md)
- [Phase 2 Routing Contract](docs/PHASE2_ROUTING_CONTRACT.md)
- [Phase 2 Pilot Runbook](docs/PHASE2_PILOT_RUNBOOK.md)
- [Phase 3 Session Workspace Charter](docs/PHASE3_SESSION_WORKSPACE_CHARTER.md)
- [Phase 3 Session Security Contract](docs/PHASE3_SESSION_SECURITY_CONTRACT.md)
- [Phase 3 Workspace Runbook](docs/PHASE3_WORKSPACE_RUNBOOK.md)
- [Cloudflare Worker Deployment notes](docs/CLOUDFLARE_WORKER_DEPLOYMENT.md)
- `docs/providers/**` provider research/handoff evidence

## Current issue map

- #2085 — canonical B14/Padiem product objective and current profile
- #2099 — Padiem routing-profile source of truth (completed)
- #2100 — shared Padiem tier declaration consumption by Chat/Claw
- #2101 — remove implicit `b14/auto` defaults from Padiem-facing execution contracts while preserving future generic autorouter capability
- #2102 — Padiem Max route evidence/selection
- #2103 — generic B14 BYOK/credential policy + Padiem boundary
- #2104 — evidence backfill for the current Padiem Pro Nemotron route
- #2107 — future Padiem operator/provider-model console
- #1955 — exact-SHA B14 Production deployment gate

The current business rule is simple: **finish reliable explicit Padiem route connectivity now; preserve and develop B14 as the general AI Router Platform over the long term.**
