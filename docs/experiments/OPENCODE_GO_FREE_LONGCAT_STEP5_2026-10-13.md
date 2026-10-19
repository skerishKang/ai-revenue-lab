# OpenCode Go Free models — LongCat 2.5 / Step 5 Free suitability (#4505)

Date: 2026-10-13 (KST). LOCAL3 source-only investigation. No activation, no
live provider call, no tier change. Both models stay OFF.

## Provider-qualified targets

| Exact B14 ID | Registry | Provider | context_window | Wire |
|---|---|---|---|---|
| `opencode-go/longcat-2.5-preview-free` | OFF | `opencode-go` OFF | `0` = UNKNOWN | `chat/completions` |
| `opencode-go/step-5-preview-free` | OFF | `opencode-go` OFF | `0` = UNKNOWN | `chat/completions` |

Source: `apps/korean-ai-platform/app/pilot/b14_models.json`;
wire map `app/pilot/opencode_go_wire.py:26-27`.
`context_window: 0` is an UNKNOWN sentinel, never a 0-token budget.

## Owner-reported symptoms

- LongCat: usable input feels small (2026-10-13).
- Step 5: frequent server load / concurrency errors (2026-10-13).

## Input-limit boundary analysis (LongCat)

| Boundary | Rule | Applies to provider request? |
|---|---|---|
| Chat UI composer | `maxlength=4000` ONLY in Claw manual-workflow view (`apps/padiem-chat/static/app.js:2057-2068`); the same composer removes that attribute for general Chat/Claw | No — this one documented UI guard does not establish all clients' limits |
| Inspected B14 gateway/provider source | No explicit prompt-character/token cap found in the inspected route and Go adapter; `MAX_RESPONSE_BYTES = 1 MiB` (`app/pilot/platform.py`) is **a response cap**, not an input guarantee | Other upstream, hosting, HTTP and consumer limits remain unverified |
| Upstream Go free model | Context / max-input / concurrency all UNSTATED in official docs (checked 2026-10-13) | Unknown — most likely rejection point |

Possible causes (not measured or ranked): **upstream undisclosed input cap**,
**view-specific Claw-manual 4k UI guard**, and **other uninspected client,
transport or hosting request limits**. No provider or full-path limit was
measured; a source-inspection result must not be reported as an unlimited
B14 or general-Free-chat guarantee.

Official-document cross-check (2026-10-13, CENTRAL review):
- `https://docs.opencode.ai/docs/go/` is currently accessible and advertises
  LongCat 2.5 Preview Free, but its visible current roster **does not list**
  Step 5. Earlier LOCAL3's 404 observation is retained as a per-client
  observation, **not** a current claim that the document universally 404s.
- `https://dev.opencode.ai/v2/docs/console/go/` currently lists **both**
  LongCat 2.5 Preview Free and Step 5 Preview Free as limited-time free.
  The two public pages are not identical; **do not infer current account-level
  Step 5 API entitlement or live availability** from either static list.
- OpenCode Go explicitly says the service is designed for OpenCode or **other
  coding agents making comparable requests**. That constraint is distinct
  from the zero-dollar token price: **do not assign either model to unrestricted
  PADIEM general-purpose Free Chat**, even with a successful coding-agent
  technical probe, until the provider permits that intended use in writing.
- Official model pricing/usage statements do not document maximum accepted
  prompt tokens, per-minute concurrency, or server overload isolation.
  Those remain UNKNOWN in this evaluation.

## Official trial-period caveats (dated 2026-10-13)

- Both models listed as "Free" token price with monthly limit "Unlimited"
  and estimated requests "Unlimited", labelled **"limited time"** — no start
  or end date published.
- No numeric rate-per-time, context window, max-input, or concurrency limit
  stated for either model. No Go-specific 429/5xx/timeout semantics stated.
- "Free" is the model token price inside paid Go plans ($10/$40 + API key),
  not a promise of infinite context, capacity, or indefinite availability.
- Coding-agent conditions: own user-agent, stable per-conversation
  `x-opencode-session` — consistent with `opencode_go_wire.py` session rules.

## Step 5 error taxonomy (OpenCode Go path, B14 `_raise_upstream_error`)

| Outcome | B14 class | Meaning at this layer |
|---|---|---|
| 200 | success (metadata-checked) | `actual_response_model` must equal upstream |
| 401 / 403 | `UpstreamAuthFailed` | auth / policy |
| 429 | `UpstreamRateLimited` | quota OR capacity — indistinguishable here (no Go-specific busy mapping) |
| 502 / 503 / 504 | `UpstreamServerError` | provider outage |
| transport timeout | `UpstreamTimeout` (504) | first-response 600s / per-chunk idle budget (`b14_timeout_policy.py`) |

No retry loop exists on the Go wire (single POST, failure surfaces once);
any 429/5xx must be recorded with phase, never retried or fallen back.

## Kilo-historical vs Go separation (YES, separated)

- PR #3830 / stacked Draft #3835 report Kilo-route StepFun concurrency caps
  (141/140) and 10/10 HTTP 429 **on the Kilo provider path**. Kilo 429 maps
  to `KiloFreeRateLimited`, Go 429 to generic `UpstreamRateLimited`
  (pinned by test). These observations are NOT Go measurements and were not
  cherry-picked or rebased here.

## Test case matrix (all mock, serial, concurrency 1)

Harness: `apps/korean-ai-platform/tests/test_opencode_go_free_longcat_step5_eval.py`
(source mock/contract tests; current PR CI is the acceptance authority):

- Input under (500 chars) → **no observed view-local reject**, but Go and
  full-path acceptance remain `upstream_unknown`; near (4,001) →
  `local_ui` only in Claw manual, `upstream_unknown` in general chat;
  over (200k, inside 300k synthetic bound) → `upstream_unknown`.
  No 200k body was sent: wire-shape test uses a 2k synthetic slice.
- Step 5 classes: 200 / 401 / 403 / 429 / 502 / 503 / 504 / timeout → closed
  vocabulary above; Kilo-429 vs Go-429 class separation; OFF-route mock proves
  **zero** network dispatch and separately isolated mock authorization with
  `httpx.MockTransport` proves **exactly one** POST on 429, with no retry.
  All test-local monkeypatches restore automatically; registry/provider OFF
  in source and actual production are unchanged; concurrency>1 rejected.
- Verdict mapping: `FREE_CANDIDATE` only with live evidence, else `HOLD`;
  registry OFF re-pinned.

## Recommendation

**Both models: HOLD (Free 후보 유지가 아닌 보류).** Reasons:

1. No live evidence: 0 real Go provider calls (`LIVE_TEST=NOT_RUN`).
2. LongCat usable input is undocumented upstream; owner symptom is
   consistent with an undisclosed free-model input cap, but unmeasured.
3. Step 5 busy/overload reports (owner observation; separately recorded Kilo
   history is NOT OpenCode Go measured evidence) plus
   "limited time / Unlimited" promo wording give no capacity assurance.
4. Usage-policy gate: Go coding-agent traffic only unless provider explicitly
   authorizes general consumer chat; *model registration and Free labeling do
   not grant unrestricted PADIEM Chat access*.
5. Safe user-facing error copy (no secrets, no raw body):
   - 429: "현재 무료 모델 사용량이 많습니다. 잠시 후 다시 시도해 주세요."
   - 5xx/timeout: "모델 서버가 일시적으로 응답하지 않습니다. 잠시 후 다시 시도해 주세요."
   - 403: "이 모델을 사용할 권한이 없습니다. 관리자에게 문의해 주세요."

## Live path (if later authorized, per model, never simultaneous)

Analogous to #4499: exact main SHA + exact active B14 Worker version via
canonical served-version resolver + credential ready + account coding-agent
use authorized + platform-approved environment; max 1 non-retrying POST per
model in its own approved run; models stay source-OFF until then
(`LIVE_BLOCKED`).

CENTRAL CTO owns Ready/merge/deploy decisions.
