# Reference notes

Research date: 2026-07-30

## Comparable routing and gateway systems

1. **OpenRouter — provider routing and ordering**  
   Reviewed for explicit provider-order, fallback and data-policy controls.
2. **LiteLLM Router**  
   Reviewed for bounded routing strategy, retries, fallbacks and provider abstraction.
3. **Portkey AI Gateway — conditional routing**  
   Reviewed for rule-based conditions and ordered fallback semantics.
4. **AWS Bedrock Intelligent Prompt Routing**  
   Reviewed for the distinction between route-selection policy and the underlying models.
5. **Model gateway governance patterns**  
   Reviewed for cost, latency, privacy and availability as separate decision inputs rather than one score.

### Adopted

- hard constraints are evaluated before weighted preferences;
- route selection retains the reason for every exclusion;
- fallback is an explicit policy branch, not silent duplicate execution;
- availability and evidence provenance remain visible;
- primary route, fallback and no-safe-route are separate outcomes;
- model execution and provider activation remain outside the policy record;
- human approval is a separate final authority.

### Rejected

- provider logos, real model names and copied gateway interfaces;
- cheapest-model-wins or highest-score-wins automation;
- one composite leaderboard score;
- estimated quality, latency or cost presented as measured benchmark evidence;
- privacy as a negotiable preference;
- unavailable candidates shown as selectable;
- live request logs, API-key controls, invoices or billing meters;
- universal “best model” claims.

## Editorial and visual references

1. **NASA Graphics Standards Manual** — adopted disciplined labeling, route color grammar and technical-document hierarchy; rejected agency branding and exact layouts.
2. **Harry Beck / London Underground diagram tradition** — adopted abstract route clarity and junction logic; rejected geographic-map imitation and official transit identity.
3. **The Pudding visual essays** — adopted progressive explanation and responsive editorial pacing; rejected narrative scrolling as a required UX flow.
4. **Industrial dispatch and rail-switching ledgers** — adopted manifest, siding, signal and dispatch metaphors; rejected photorealistic rail simulation and operational-control claims.

## Product distinction

- **Business 14** provides governed access to external, domestic and self-hosted models. Business 54 decides a bounded route policy; it does not provide access.
- **Business 53** specifies how an approved AI capability fits into a host product. Business 54 does not design an embed surface or host integration.
- **Business 55** governs local devices, model inventory, capacity, jobs and incidents. Business 54 does not operate a local-model fleet.
- **Business 48** verifies evidence and approvals. Business 54 consumes evidence status as an input but owns the routing-policy decision artifact.

## Visual direction

`Model Routing Switchyard / AI 모델 분기 조차장`

The system uses a task manifest, route tracks, constraint gates, candidate tickets, availability signals, fallback sidings and a human dispatch ledger. It deliberately avoids a generic comparison table, leaderboard, cloud dashboard, provider wall, API console or engine room.
