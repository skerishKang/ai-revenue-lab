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
