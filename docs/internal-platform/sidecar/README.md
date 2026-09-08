# IP-SIDECAR — Padiem Embedded AI Runtime

```text
INTERNAL_PLATFORM_ID = IP-SIDECAR
CANONICAL_NAME = Padiem Embedded AI Runtime
REPOSITORY = skerishKang/ai-revenue-lab
PROPOSED_SOURCE = packages/padiem-embedded-runtime/
SOURCE_DIRECTORY_CREATED = NO
BUSINESS_NUMBER = NONE
PRIMARY_COMMERCIAL_PRODUCT = B53 Padiem Sidecar
STATUS = proposed (registry/boundary S1 only; no runtime implementation)
```

## S2 runtime contract (non-production)

S2 lands the minimal package-level contract at
`packages/padiem-embedded-runtime/` (stdlib-only, no I/O):

- browser-safe bootstrap/config contract (bounded non-secret metadata);
- shell lifecycle `closed -> opening -> open -> closing -> closed` plus
  `disabled` fail-safe;
- host-context envelope (untrusted by default, never authority);
- public-safe event projection primitives (allowlisted types, bounded text);
- abstract Engine port + deterministic fake (tests/demo only, no transport);
- repository-local reference host demo driven by a deterministic fixture;
- focused unittest contract tests (20 tests, stdlib only).

Run: `cd packages/padiem-embedded-runtime && python -m unittest discover -s tests -t .`

S2 performs no Engine connectivity, provider calls, OAuth, product
migration, or deployment. Real Engine transport remains a later slice.

## Role

Reusable, browser-safe embedded shell/context/event/presentation/bootstrap
primitives for AI surfaces that live inside host products.

## Ownership boundary

```text
Host/Product Adapter
  -> IP-SIDECAR (embedded shell/context/event/presentation/bootstrap only)
  -> IP-ENGINE (service identity/transport)
  -> IP-CORE (shared AI contracts and runtimes)
  -> B14 (provider/model/routing authority)
  -> Provider / model

Control Plane = canonical identity/tenant/entitlement/usage/billing/audit authority
```

IP-SIDECAR owns reusable embedded primitives only. It must not own
product-domain semantics, Engine service identity/transport, Core AI
semantics, B14 provider routing/credentials, Control Plane authority, or
browser-visible secrets.

## Relationship to B53

B53 Padiem Sidecar (`reference/business-53-embedded-ai-sdk-v1/`, Business
registry `n:53`) owns commercial/product/embed UX. IP-SIDECAR owns the
reusable embedded runtime primitives B53 and future hosts build on. B53
remains a numbered Business; it is the primary commercial consumer, not the
owner, of IP-SIDECAR.

## Overlap audit (S1, read-only; no product mutated)

Bounded extraction candidates only — reference links, no source changes:

- B30 Civic AI Navigator (`n:30`, external/proposed) — host-side AI surface
  consumer candidate. No local runtime to extract from.
- B61 StoryMemory (`n:61`, active) — embedded-surface consumer candidate via
  the existing IP-ENGINE identity authority. No ownership claimed.
- LoveBud (`skerishKang/LoveBud`, external implementation) — host-surface
  consumer candidate. External repository; reference only, never mutated.
- B62 Padiem Chat (`apps/padiem-chat/`) — chat/product surfaces stay
  product-local. IP-SIDECAR claims no ownership over B62 UI or routes.
- B54 Padiem Claw (`apps/korean-ai-code-agent/`) — agent runtime stays
  product-local. IP-SIDECAR claims no ownership over B54 runtime.

## Reuse rule (do not duplicate)

IP-SIDECAR is a downstream consumer of the Engine completion program #1743.
Generic capabilities must be reused from their canonical owners, never
duplicated in IP-SIDECAR:

- Web/Research #1744, Evidence/Citation #1745, Tool Runtime #1746,
  Memory/RAG #1748, Agent/Skill #1749, File/Multimodal #1750,
  Tenant/Entitlement/Usage #1751, final capability conformance #1752.

## Canonical source-path decision (S1)

```text
PROPOSED_SOURCE_PATH = packages/padiem-embedded-runtime/
PATH_CONFLICT_AUDIT = PASS
SOURCE_DIRECTORY_CREATED = NO
```

Repository-wide audit found no existing shared-runtime path owning
browser-safe embedded primitives (zero `sidecar` paths; B53 holds only a
reference pack; Engine owns transport; Core owns AI semantics). The path
above is reserved by this document only; runtime language/binding and
scaffolding are deferred to a later implementation slice.

## Start here

- Platform registry: `docs/internal-platform/INTERNAL_PLATFORM_REGISTRY.md`
- Console manifest: `apps/portfolio-console/internal-platform-manifest.js`
- Adoption playbook: `docs/internal-platform/AI_ADOPTION_PLAYBOOK.md`

Canonical Issue prefix for new work: `[IP-SIDECAR]`.

Refs #1739.
