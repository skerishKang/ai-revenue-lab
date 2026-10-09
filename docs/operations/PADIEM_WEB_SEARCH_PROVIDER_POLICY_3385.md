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


## 2026-10-10 served Worker read-only checkpoint — ACCOUNT CORRECTION, source merged, Search binding pending

**FINAL CORRECTION (supersedes the earlier wrong account-assignment diagnosis): the `padiem-chat` Worker and the existing TinyFish/Daum Secrets Store are in the SAME Cloudflare account, Charliekant.** There is no cross-account secret replication task.

- **Exact direct proof, not name inference:** Authenticated Wrangler read-only `deployments list --name padiem-chat --json` with Charliekant Account ID `9be14bb7b8974e65d0afba647ab16932` succeeded and returned deployment history. The identical request under separately named Padiem Account ID `5a305a04650f4ad419062f8d4a96a41d` returned Cloudflare **10007: Worker does not exist on your account**. Therefore the correct target for Search bindings is **Charliekant**, not Padiem. This checkpoint did not separately read the `padiem.net` DNS zone's Account ID, and it must not be inferred from a Worker name.
- **Existing secrets:** The **same Charliekant account's** default Secrets Store has active secrets named `PADIEM_TINY_FISH_API_KEY` and `PADIEM_KAKAO_API_KEY`, independently confirmed using remote Wrangler metadata-only list. Both provider keys already exist; no provider re-issuance, key replication or secret-value retrieval is required.
- **Source implementation:** PR #3975 merged in commit `08580ef3be78279057598322c31a630ddc741981` after **24/24 successful exact-head CI workflows**, including previously cancelled CI rerun to completion. Priority remains TinyFish Search first, single Daum Search on TinyFish HTTP 402/429, TinyFish-only Fetch; never use Firecrawl, and no AI model fallback.
- **Served Worker binding inventory:** [B62 Cloudflare read-only workflow 37973006625](https://github.com/skerishKang/ai-revenue-lab/actions/runs/37973006625) succeeded and showed existing Engine/identity/R2 bindings with `B62_CLAW_LIVE_CONFIG_DISPOSITION=ALREADY_EXACT` for those legacy bindings, but **did not show** web key bindings `TINYFISH_API_KEY`, `PADIEM_CHAT_DAUM_REST_API_KEY` or explicit `PADIEM_CHAT_WEB_PROVIDER`. It was not proof that Search is live. No secret values were read or exposed.
- **Canonical same-account connection:** Cloudflare's [official Workers Secrets Store integration](https://developers.cloudflare.com/secrets-store/integrations/workers/) specifies `[[secrets_store_secrets]]` with `binding`, `store_id`, `secret_name`, and async `await env.<binding>.get()`. Connect the **existing same-account** records using appropriate Worker-facing aliases; the current Python Worker `settings_from_worker_bindings(env)` assumes web keys are synchronous string values, so test/adapt its asynchronous request-path resolution. A binding alone cannot be treated as a plaintext string.
- **Production acceptance under #3523:** establish approved same-account Secrets Store bindings and Python Worker async secret access, perform existing deployment guard and exact served-version/config readback; prove TinyFish nominal and bounded 402/429 Daum Search fallback without exposing secret values or relaxing B14/Claw live-deadman gates. No Production changes were made in this checkpoint.

```text
WEB_SEARCH_SOURCE_MERGED=YES
WEB_SEARCH_OWNER_PRIORITY=TINYFISH_THEN_DAUM_ON_402_429
WORKER_ACCOUNT=CHARLIEKANT
SECRETS_STORE_ACCOUNT=CHARLIEKANT
WEB_SEARCH_CREDENTIALS_EXIST=YES_SAME_ACCOUNT
CROSS_ACCOUNT_TRANSFER_REQUIRED=NO
WEB_SEARCH_SERVED_BINDINGS=ABSENT_AT_LAST_READBACK
WEB_SEARCH_LIVE_ACTIVATED=NO
WEB_SEARCH_DEFAULT_B14_DEADMAN_BYPASS=NO
PRODUCTION_MUTATION=0
ISSUE_3385=CLOSED_SOURCE_COMPLETE
ISSUE_3523=OPEN_LIVE_GOLDEN_PATH
```

## Same-account Secrets Store → Chat Worker binding activation (2026-10-10)

The served `padiem-chat` Worker and the Owner's existing active public-web keys
are in the **same Charliekant Cloudflare account**. No key issue, copying,
rotation or cross-account migration is necessary.

| Worker alias | Existing Secrets Store secret name |
| --- | --- |
| `TINYFISH_API_KEY` | `PADIEM_TINY_FISH_API_KEY` |
| `PADIEM_CHAT_DAUM_REST_API_KEY` | `PADIEM_KAKAO_API_KEY` |

Both records are in the existing store ID `f0b09ca04a7b43248154c773704a5616`.
Cloudflare's official *same-account* binding syntax is:

```toml
[[secrets_store_secrets]]
binding = "TINYFISH_API_KEY"
store_id = "f0b09ca04a7b43248154c773704a5616"
secret_name = "PADIEM_TINY_FISH_API_KEY"

[[secrets_store_secrets]]
binding = "PADIEM_CHAT_DAUM_REST_API_KEY"
store_id = "f0b09ca04a7b43248154c773704a5616"
secret_name = "PADIEM_KAKAO_API_KEY"
```

The Python Worker resolves selected bindings via async `.get()`, preserving
direct `secret_text` string compatibility. Mock/off never calls the store.
Public query only: never send private Drive/PDF, history or credentials.

Deploy in authority order: (1) merge source + adapter + guard tests;
(2) establish exact Charliekant served-version and all-binding readback;
(3) add these two *existing* records to the Worker bindings (Cloudflare
Dashboard > Worker Settings > Bindings > Secrets Store, or verified equivalent);
(4) deploy exact approved main through the canonical B62/#3523 gate,
which preserves the existing Engine/identity/D1/secret set; (5) read back
the actually served version and name/type inventory; (6) bounded public
TinyFish nominal + simulated 402/429 Daum failover. **Do not** claim live
Search from source, account inventory or settings-plane metadata alone.
Existing live deadman policy and model selection are unchanged.

## 2026-10-10 controlled atomic Search Secrets Store attachment (#3523)

Owner-approved live release uses the existing Charliekant account and existing
Secrets Store records only. Cloudflare binding metadata (not API key values):

| B62 Worker alias | Secrets Store record |
| --- | --- |
| `TINYFISH_API_KEY` | `PADIEM_TINY_FISH_API_KEY` |
| `PADIEM_CHAT_DAUM_REST_API_KEY` | `PADIEM_KAKAO_API_KEY` |

Store ID `f0b09ca04a7b43248154c773704a5616`. Confirmed both secrets are
`active` with `workers` scope in the same account as `padiem-chat`.

DO NOT issue fresh keys, duplicate keys, read key values or first deploy
the old code with new bindings. Instead use B62 Production Code Deploy Gate
on an exact newly approved current `main` SHA, with
`mode=deploy_production_code`, the established exact confirmation string,
and `attach_existing_web_secrets_store=true`. This is a separately gated
opt-in; normal production deploy paths remain unchanged.

Guardrails: the pre-deploy Cloudflare served version is recorded as rollback
anchor. The generator uses trusted actual live settings, preserving all
existing service, Engine, identity, D1, R2, vars and secret bindings, and
adds only the two fixed names/store/records above. The served binding-state
and served-version full-secret-set guards permit only those *exact* additions,
reject wrong identities, and continue to enforce all existing bindings.
Post-deploy verify 100% newly served exact-main Worker, both exact bindings,
health/quotas, nominal public-only TinyFish and 402/429 Daum Search fallback.
Never expose API values in logs or permit private workspace egress.
Without all guards PASS do not claim production Search activation.

## 2026-10-10 #3523 Evidence selection remediation / bounded production diagnostics

Actual served /api/chat Search requests returned web_unavailable intermittently
and on one successful TinyFish-route Search HTTP 404 no_evidence. The latter
means upstream Search success is not by itself sufficient for answer grounding.
Source quality requires exact entity-token overlaps with min_relevance_score=0.18.
A navigational query such as `서울특별시 공식 누리집` can score just 0.1667
when only the topical entity appears in the title and the remaining
`공식` / `누리집` boilerplate does not appear literally. This is a reproducible
example; do NOT claim it is proven to be the sole served 404 root cause.

Navigation-term normalization now applies only when a website/navigation
intent cue is present AND at least one distinct topical token remains.
It drops navigational terms for matching only; it never changes the user's
actual provider query or adds/substitutes a search call, lowers the global
relevance threshold, permits substring entity matches or changes provider
priority/402-429 fallback policy. Examples: `서울특별시` must NOT match
`서울시` by substring, unrelated official sites remain irrelevant,
and `피타고라스 공식` still treats `공식` as topical.

Runtime emits only fixed safe diagnostic categories:
`TINYFISH_SEARCH_NORMALIZATION=UPSTREAM_EMPTY|NO_USABLE_URL|USABLE`,
`GROUNDING_SEARCH_EVIDENCE=PROVIDER_EMPTY|QUALITY_FILTER_REJECTED|QUALITY_SELECTED`.
No raw text, URL, API credential, provider body, error detail or user query
is printed. These markers clarify whether served no_evidence is provider
empty, invalid/unsafe normalized URLs, or Core source-quality rejection.
No private workspace data is sent to the search providers.

Acceptance: exact-head CI, deploy newest reviewed main with existing
29 Cloudflare bindings preserved, independently probe one public-only
Search query while observing fixed labels; verify genuine evidence selection
but do not claim full model completion while B14 user-selected executable
profile is HOLD. B14 model selection is a separate authority, NOT automatic.
