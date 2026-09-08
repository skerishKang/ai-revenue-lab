# Padiem Claw Source of Truth

## Identity

```text
BUSINESS_ID = B54
PRODUCT_NAME = Padiem Claw
PRODUCT_FAMILY = Padiem Agents
CANONICAL_CODE_PATH = apps/korean-ai-code-agent/**
NEW_BUSINESS_NUMBER = NO
```

`Padiem Agent` is the product-family/category description. The representative user-facing execution product is `Padiem Claw`.

## Authority order

1. current merged GitHub source and accepted product contracts under `apps/korean-ai-code-agent/**`;
2. repository-wide Padiem AI cross-layer architecture: `../../../docs/architecture/PADIEM_AI_VERTICAL_STACK.md`;
3. current reviewed B54 product/architecture/security/operations Markdown;
4. accepted GitHub product/architecture issues and exact-head PR/CI evidence;
5. Drive Google Docs mirrors;
6. HTML overview/landing copy;
7. historical/dated snapshots and superseded working artifacts.

A B54 document may specialize Claw product behavior, but it cannot move generic AI semantics, cross-runtime transport, provider/model routing, or canonical account/entitlement authority away from the owning shared layer.

Draft PRs and working branches are candidate future contracts, not higher authority than current merged source/main.

## Shared-platform boundary

```text
B54 Padiem Claw
  -> Product Adapter
  -> IP-ENGINE for cross-runtime shared execution
  -> IP-CORE shared AI semantics
  -> B14 Router Platform
  -> Provider / Model

IP-CONTROL = cross-cutting identity/workspace/entitlement/usage/audit authority
```

A same-runtime/local path may use accepted Core library contracts directly where explicitly designed. That does not grant B54 generic Agent/Tool/Connector/Memory or provider-routing authority.

## B65 correction

The former Drive artifact `B65_PADIEM_AGENT` and its charter were early working artifacts, not a canonical Business assignment. After the existing B54 product authority was identified, the B65 creation direction was withdrawn. Preserve those materials as `SUPERSEDED` evidence rather than current authority.

## Change policy

- B54 product-boundary change: Issue/work order -> bounded branch -> reviewed PR.
- Cross-layer architecture change: update/review the owning shared-layer authority and `PADIEM_AI_VERTICAL_STACK.md` as required.
- IP-CORE / IP-ENGINE / B14 / IP-CONTROL authority changes belong to those owner layers, not a Claw-only task.
- If documentation and merged source conflict, classify whether the conflict is product behavior, shared architecture, runtime availability or historical evidence; reconcile the owning current document rather than averaging contradictory text.
- secret, credential, provider key, raw private reasoning or private customer data must not appear in documentation/HTML/evidence.
- `SOURCE_PRESENT`, `DEPLOYED`, `PRODUCTION_ACTIVE` and `LIVE_VERIFIED` are distinct states.