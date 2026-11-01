# StoryMemory / BookAI AI on COM2

Code-only handoff. Source base: `6ee6bf81bc70e0668112f038b0840972234af3af`; branch: `feat/apps-ai-com2-261101`. Deployment and secret configuration belong to CTO.

## Route

Pages `POST /api/storymemory-ai` → `https://chat.padiem.net/api/apps/ai` → existing COM2 P01 `/internal/v1/execute` → existing B14 model execution and call ledger.

The Chat endpoint is installed only by the CPython host composition. It never authenticates an app using a browser session. The front remains a proxy. Its app-AI response-header deadline is `APPS_AI_TIMEOUT_MS` (default 65000); other routes keep their current deadline. The app-only P01 transport waits up to 55 seconds, inside the Pages request budget of 60 seconds.

## Credentials and authorization

| App | Signed subject | Secret name on both Pages and COM2 Chat |
|---|---|---|
| StoryMemory 1.0 | `sub_app_storymemory` | `STORYMEMORY_COM2_AI_SECRET` |
| BookAI | `sub_app_bookai` | `BOOKAI_COM2_AI_SECRET` |

Reuse the BookAI records v1 signature: HMAC-SHA256 hex over `METHOD\nPATH\nTIMESTAMP_SECONDS\nSUBJECT\nSHA256(BODY)`. Headers are `X-Bookai-Subject`, `X-Bookai-Timestamp`, `X-Bookai-Signature`. The timestamp must be within 300 seconds. Each subject is bound to its own secret and policy; callers cannot select a destination or another app's policy.

Chat reuses `PADIEM_CHAT_LOCAL_P01_ENGINE_ORIGIN`, `PADIEM_CHAT_LOCAL_P01_CALLER_ID`, and `PADIEM_CHAT_LOCAL_P01_ENGINE_CREDENTIAL`. The existing P01 caller must authorize engine app ID `b61`: add it to that caller's `allowed_app_ids` in `PADIEM_ENGINE_CALLER_REGISTRY_V1`, or preserve existing entries and add `b61` to `PADIEM_ENGINE_ALLOWED_APPS` when using the single-caller configuration. Do not substitute another product ID or disable the existing Engine authorization.

No credentials are generated, copied or printed by this change.

## Per-app policy

`PADIEM_APPS_AI_POLICY_JSON` optionally overrides each app's `allowed_models`, `max_tokens`, and `max_body_bytes`. Defaults preserve the app's explicit `google/gemini-3.1-flash-lite`, 900 output tokens and the existing host transport's 262144-byte request envelope. Example without secrets:

```json
{"storymemory":{"allowed_models":["google/gemini-3.1-flash-lite"],"max_tokens":900,"max_body_bytes":262144},"bookai":{"allowed_models":["google/gemini-3.1-flash-lite"],"max_tokens":900,"max_body_bytes":262144}}
```

The request must use `model_policy: {model, max_retries: 0}`; automatic model selection and policy expansion from request content are rejected. Context permission remains required and is validated by the existing Engine. The Python client now forwards those execute-only fields, matching the JavaScript client.

P01 forwards request-scoped `client_app=storymemory|bookai` to the existing B14 ledger. That same ledger already records model and result. No second usage store or provider call is introduced.

## Continuity and verification

StoryMemory retains the existing authenticated Cloudflare ingress as a fallback for unavailable COM2 transport/configuration. Its existing `PADIEM_INGRESS_CLIENT_SECRET` remains necessary for that fallback. Model/policy/limit rejections do not trigger it. BookAI uses COM2 only.

Both apps continue removing complete and unfinished `<thought>` blocks and validating the returned context-permission diagnostics.

Focused tests cover app signatures, five-minute expiry, model/token limits, real local P01 request/response with a synthetic B14 provider, ledger attribution, 1.0 fallback, thought removal and proxy deadlines. These tests do not claim that production configuration or deployment has been applied.
