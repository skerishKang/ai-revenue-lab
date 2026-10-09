# PADIEM public web search priority — Owner decision (#3385)

**Decision date:** 2026-10-10  
**Authority:** Owner; replaces all earlier "no automatic fallback", "TinyFish only", or "choose one web provider" directions **for the public-web search quota path only**.  
**Scope:** B54/Padiem Chat/Claw live public-web Search and its existing Core-owned provider adapters. No change to AI model/B14 dispatch policy.

## Exact provider order

| Situation | Search decision | Actual result provider |
| --- | --- | --- |
| Ordinary public-web search | TinyFish Search first | `tinyfish` |
| TinyFish reports HTTP **402** (quota/credits gate) | Once to Daum Search | `daum` |
| TinyFish reports HTTP **429** (rate allowance gate) | Once to Daum Search | `daum` |
| TinyFish responds 200 with an empty valid result list | Return empty; no Daum call | `tinyfish` |
| TinyFish auth failure, timeout, 5xx, malformed response, unsafe result | Surface bounded error; no switch | no fabricated success |
| Daum fails after eligible fallback | Surface error; no third provider or repeated attempt | no fabricated success |
| Explicit Fetch URL | TinyFish Fetch only | `tinyfish` |
| Fetch failure or exhausted allowance | Surface error; **never** pretend Daum has Fetch | no fabricated success |

**Firecrawl is excluded from selected search/fetch routes for cost.** Legacy adapters may remain for source/rollback compatibility; do not call Firecrawl as a hidden third-party extractor. Daum's own Fetch method is not a substitute for native Fetch.

This is **an intentional, Owner-authorized, condition-specific fallback**, not a generic automatic router or a different AI model. Maximum **one TinyFish Search + one Daum Search** per user search; no automatic retry, parallel dual dispatch, or silent rerouting on unrelated failures. The evidence keeps the actual `provider` field, and the user-visible response must not imply a TinyFish origin for Daum results.

## Server configuration

- **Armed live B14 mode (`PADIEM_CHAT_LIVE_ENABLED=true`), no explicit provider override:** `Settings.from_env()` selects `tinyfish_daum` — TinyFish primary, Daum secondary on 402/429.
- **Mock/offline or unarmed B14 mode:** default remains `off` to avoid unexpected egress; an explicitly supplied provider remains authoritative.
- **Explicit live provider:** `PADIEM_CHAT_WEB_PROVIDER=tinyfish_daum` where deployment is explicitly configured; `tinyfish`, `daum`, and `off` still mean their direct behaviors.
- Both previously registered server-side bindings are needed: `TINYFISH_API_KEY` and `PADIEM_CHAT_DAUM_REST_API_KEY`. Owner confirmed credentials **already exist**; do not mint, rotate or ask for keys. A missing live binding is a configuration error, **not** an excuse to silently disable search or use some third provider.
- Merged source is **not** evidence that an already-serving Worker has applied the setting. Check actual served config/bindings/version separately through the standard bounded #3523 gate; no Production mutation is implied by this policy or test PR.

The TinyFish plan includes a zero-priced Search/Fetch tier and Owner confirms paid credits are also available. **Do not add a blanket zero-cost-only runtime gate.** HTTP 402/429 retains its technical meaning regardless of a public pricing table. This policy does not attempt to infer a daily-reset timestamp, quota balance, wallet value, or retained billing history from a response. Each request is bounded. Any future durable quota-aware routing across Worker instances is distinct infrastructure work, not assumed here.

## Data/provenance boundaries

- Send only the public query and bounded standard parameters to the selected search provider. Never send chat history, private Drive/PDF, customer document contents, credentials or identity tokens via this search policy.
- Reuse fixed provider origins, URL normalizers, public evidence and existing size/timeout gates. Avoid logging query values, raw provider errors, API keys or document bodies to provider analytics.
- Separate private data storage and minimal provider disclosure continue under their existing PADIEM authority issues. There are no external customer agreements to change in this source slice; future customer terms are negotiated by the Owner.
- No impact on B66 deterministic quotation, B67 private legal retrieval, private Drive search, or AI model selection/fallback.

## Evidence and operational proof

LOCAL3's pinned Search comparison: TinyFish **14/14**, Daum **14/14**. TinyFish had better source diversity/official relevance on that sample; Daum had shorter median latency and more publication-date metadata. The subsequent TinyFish Fetch 16-case report found 14 usable, one timeout and one expected 404. Original raw files were off-repo and not independently replayed by CENTRAL. Historical benchmark implementation and its last 404-classification patch are merged via #3624, #3813/#3814, #3950, #3957, #3973.

**Completion evidence for priority source:** mock-transport tests: successful TinyFish (1 request), 402→Daum (2 requests), 429→Daum (2 requests), 500/no result→no fallback (1 request), Daum second failure→no third call, Fetch→TinyFish only, invalid/missing keys fail closed, explicit off preserved. All CI must use zero live provider traffic.

**Production verification is separate:** read the served B54 config without exposing secrets; verify provider selection, actual two-key binding existence, exact deployed revision and rollback; only then assert that the deployed service follows this Owner-approved priority. Retain #3523 until its complete authenticated Claw E2E is proven.

Issue #3966 is managed independently by the Owner; this policy does not modify or close it.


## 2026-10-10 served Worker read-only checkpoint — source merged, live Search NOT activated

- **Source:** #3975 was squash merged into main `08580ef3be78279057598322c31a630ddc741981` after **24/24 successful exact-head CI workflows**; prior cancellation-only CI was rerun to completion. All search-routing logic, tests, default rules and policy above are *repository source*.
- **Live read-only evidence:** [B62 Cloudflare live-config run 37973006625](https://github.com/skerishKang/ai-revenue-lab/actions/runs/37973006625) completed successfully on exact merge SHA, with `PRODUCTION_MUTATION=0` and `B62_CLAW_LIVE_CONFIG_DISPOSITION=ALREADY_EXACT` for existing Engine/identity/R2 service bindings. That result does **not** attest to web search provider readiness.
- **Current served binding inventory:** padiem-chat Worker is **not bound** to `TINYFISH_API_KEY`, `PADIEM_CHAT_DAUM_REST_API_KEY` or `PADIEM_CHAT_WEB_PROVIDER`. The run intentionally showed only binding names and types, not secret/plain-text values. Do not assert live Search activation, active B14 mode, or model/Claw readiness from this output.
- **Existing secret location:** authorized read-only metadata inventory confirmed **both keys already exist** in Cloudflare Secrets Store in a *different Cloudflare account* from the padiem-chat Worker (existing source labels `PADIEM_TINY_FISH_API_KEY` and `PADIEM_KAKAO_API_KEY`). There is no need to generate, purchase or replace either provider credential. This is a **binding/account-scope mismatch**, not a claim that the Owner lost credentials.
- **Official Cloudflare behavior:** Secrets Store is account-scoped; its secret values cannot be decrypted/read back through API or dashboard after storage. Workers Secrets Store bindings require account-side deployment authority and are retrieved asynchronously using `get()`, unlike the current synchronous Chat string config. A direct cross-account reuse path was not verified. Avoid inventing one or secretly copying values via GitHub logs/repository. Sources: [Cloudflare Secrets Store](https://developers.cloudflare.com/secrets-store/manage-secrets/), [Workers integration](https://developers.cloudflare.com/secrets-store/integrations/workers/).
- **Next acceptance under #3523:** only via approved private credential-placement path, bind the **existing** values into the Padiem Worker account with appropriate Worker-compatible bindings and no secret output; perform exact served Worker configuration/readback, preserve `PADIEM_CHAT_LIVE_ENABLED` deadman policy, and then use bounded live/public Search with TinyFish nominal + 402/429 Daum switch. Production code deploy requires independent P01/identity/D1/secret-set gates. No automatic activation or code deployment was performed at this checkpoint.

```text
WEB_SEARCH_SOURCE_MERGED=YES
WEB_SEARCH_OWNER_PRIORITY=TINYFISH_THEN_DAUM_ON_402_429
WEB_SEARCH_CREDENTIALS_EXIST=YES_OTHER_ACCOUNT
WEB_SEARCH_SERVED_BINDINGS=ABSENT
WEB_SEARCH_LIVE_ACTIVATED=NO
WEB_SEARCH_DEFAULT_B14_DEADMAN_BYPASS=NO
PRODUCTION_MUTATION=0
ISSUE_3385=CLOSED_SOURCE_COMPLETE
ISSUE_3523=OPEN_LIVE_GOLDEN_PATH
```
