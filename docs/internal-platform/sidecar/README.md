# IP-SIDECAR — Padiem Embedded AI Runtime

```text
INTERNAL_PLATFORM_ID = IP-SIDECAR
CANONICAL_NAME = Padiem Embedded AI Runtime
REPOSITORY = skerishKang/ai-revenue-lab
SOURCE = packages/padiem-embedded-runtime/
SOURCE_PRESENT = YES
S2_MINIMAL_RUNTIME_CONTRACT = LANDED
ENGINE_CONNECTIVITY = NO
LIVE_PROVIDER_EXECUTION = NO
PRODUCTION_ACTIVE = NO
BUSINESS_NUMBER = NONE
PRIMARY_COMMERCIAL_PRODUCT = B53 Padiem Sidecar
STATUS = source-present / non-production runtime contract
```

## Current runtime contract

The S2 minimal package-level contract is present at `packages/padiem-embedded-runtime/` and is intentionally bounded to stdlib-only, no-I/O embedded runtime primitives:

- browser-safe bootstrap/config metadata;
- shell lifecycle `closed -> opening -> open -> closing -> closed` plus fail-safe `disabled`;
- untrusted-by-default host-context envelopes;
- public-safe event projection primitives;
- abstract Engine port plus deterministic fake for tests/demo only;
- repository-local fixture-driven reference host;
- focused unittest contract tests.

Run:

```text
cd packages/padiem-embedded-runtime
python -m unittest discover -s tests -t .
```

S2 does **not** provide Engine connectivity, provider calls, OAuth, product migration, credential transport, or Production deployment. Real Engine transport and Production activation remain separate later gates.

## Role

IP-SIDECAR owns reusable, browser-safe embedded shell/context/event/presentation/bootstrap primitives for AI surfaces that live inside host products.

## Ownership boundary

```text
Host/Product Adapter
  -> IP-SIDECAR  embedded shell/context/event/presentation/bootstrap only
  -> IP-ENGINE   service identity / cross-runtime transport
  -> IP-CORE     shared AI contracts and runtimes
  -> B14         provider/model/routing/execution authority
  -> Provider / Model

IP-CONTROL = canonical identity / tenant / entitlement / usage / billing / audit authority
```

IP-SIDECAR must not own product-domain semantics, Engine service identity/transport, Core AI semantics, B14 provider routing/credentials, Control Plane authority, or browser-visible secrets.

## Relationship to B53

B53 Padiem Sidecar (`reference/business-53-embedded-ai-sdk-v1/`, Business registry `n:53`) remains the commercial product: onboarding, packaging, embed UX, customer journey, product-local authorization and commercial evidence.

IP-SIDECAR is the reusable embedded runtime layer that B53 and future approved hosts may consume. B53 remains a numbered Business and is the primary commercial consumer, not the owner, of IP-SIDECAR.

## S1 overlap audit — historical basis

The S1 overlap audit remains useful historical evidence for why the shared runtime boundary was created. It identified bounded consumer/extraction candidates without transferring their domain ownership:

- B30 Civic AI Navigator — host-side AI surface candidate;
- B61 StoryMemory — embedded-surface consumer candidate through accepted Engine boundaries;
- LoveBud — external host-surface candidate, reference only;
- B62 Padiem Chat — chat/product surfaces stay product-local;
- B54 Padiem Claw — agent/runtime product semantics stay product-local.

## Reuse rule

IP-SIDECAR is downstream of the shared Engine/Core capability program. Generic capabilities must be reused from their canonical owners rather than duplicated in the embedded runtime:

- Web/Research #1744;
- Evidence/Citation #1745;
- Tool Runtime #1746;
- Memory/RAG #1748;
- Agent/Skill #1749;
- File/Multimodal #1750;
- Tenant/Entitlement/Usage #1751;
- final capability conformance #1752.

## Source-path decision

```text
SOURCE_PATH = packages/padiem-embedded-runtime/
PATH_CONFLICT_AUDIT = PASS
SOURCE_DIRECTORY_CREATED = YES
S2_RUNTIME_CONTRACT_PRESENT = YES
```

The earlier S1 statement that the path was only reserved is historical and no longer current. The S2 source now occupies that canonical path. This does not imply Engine transport or Production activation.

## Start here

- Package contract: `packages/padiem-embedded-runtime/README.md`
- Platform registry: `docs/internal-platform/INTERNAL_PLATFORM_REGISTRY.md`
- Console manifest: `apps/portfolio-console/internal-platform-manifest.js`
- Adoption playbook: `docs/internal-platform/AI_ADOPTION_PLAYBOOK.md`

Canonical Issue prefix for new work: `[IP-SIDECAR]`.

Refs #1739 #2135.
