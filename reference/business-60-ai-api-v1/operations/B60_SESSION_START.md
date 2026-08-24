# B60 Session Start

Status: **REQUIRED STARTUP CONTRACT**  
Effective: **2026-08-25**  
Tracks: #704

This file exists so B60 can continue correctly after chat/session turnover. A future assistant or operator must not depend on old conversation memory as the source of truth.

## 1. Required read order

Before making a product-direction decision or mutation, read:

1. `operations/B60_PRODUCT_CANON.md`
2. `operations/B60_EDITORIAL_OPERATIONS.md`
3. `operations/B60_VISUAL_RULES.md`
4. `README.md` for historical/technical context
5. current B60 issue/PR relevant to the task

If the current request is about a particular data/review mechanism, also inspect the relevant source/tests rather than relying on this summary.

## 2. Fresh remote state first

GitHub remote is the operational source of truth.

At the start of substantive work, freshly check:

```text
current main full SHA
open B60 issues
open B60 PRs
current target PR head/base
changed files
mergeability/draft state
relevant CI / exact-head status
collision with another active B60 task
```

Numbers/SHA values written in old chats or handoffs are bootstrap hints only.

## 3. Default product mental model

Remember this before doing anything else:

```text
B60 Priority 1 = timely free / credit / promotion discovery
B60 Priority 2 = always-free access reference
Priority 3     = provider/API execution elsewhere
```

The homepage is an **editorial opportunity radar**, not a provider directory.

## 4. When the owner sends X/web links

Default action:

```text
link(s)
→ inspect
→ extract benefit
→ verify material claims
→ classify temporary vs always-free vs pending
→ choose editorial importance
→ choose real/official/licensed image or screenshot
→ update B60 data/presentation
→ render/review if visual change is material
```

Do not respond by proposing mass provider expansion unless the owner asks for that.

Do not respond by proposing automation merely because the link arrived manually.

## 5. Manual curation rule

Manual owner discovery is a supported permanent workflow at the current stage.

Automation is optional and secondary. Build automation only when repeated volume makes it worthwhile or when explicitly requested.

## 6. Visual invariants

Current editorial surface must preserve:

- benefit-first presentation
- image-led editorial hierarchy
- real/official/licensed raster imagery or screenshots where useful
- no new decorative/simple SVG filler
- no generic black/purple/neon/glass AI-SaaS aesthetic by default
- varied editorial rhythm rather than a uniform card wall
- clear distinction between temporary and always-free access
- mobile benefit visibility early in the flow

## 7. Truth invariants

Never weaken these for presentation speed:

- do not fabricate expiry dates or limits;
- social posts may be discovery leads but not automatic facts;
- use primary/official verification for material claims when available;
- unverified expiry stays pending/checking;
- `종료 임박` requires verified expiry;
- keep source/provenance and verification timestamps;
- preserve explicit human-review/publication boundaries in the existing review pipeline.

## 8. Current architecture boundary

B60 may discover / verify / compare / explain access.

Do not introduce provider-call execution, key storage, billing, auth, or provider proxy behavior into B60 unless the owner explicitly changes the product boundary.

## 9. Session handoff rule

Before ending a long session that materially changes B60:

1. update the canonical document if product/visual/operations rules changed;
2. ensure important decisions exist in GitHub issue/PR/docs, not only chat;
3. record current PR/issue state and exact head in the PR/issue if useful;
4. leave temporary QA workflows/artifacts out of the permanent product diff unless intentionally required;
5. state the next concrete task in durable GitHub context.

A future session should be able to continue by reading the repository without reconstructing the previous chat.

## 10. Conflict resolution

Order of authority:

```text
explicit current owner instruction
→ canonical B60 operation docs
→ current accepted GitHub issue/PR decisions
→ README/history
→ old chat/handoff memory
```

If an explicit owner instruction changes the canon, update the relevant canonical file so the change survives the session.
