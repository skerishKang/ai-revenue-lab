# Agnes AI Provider Intake — B14 V1

Status: CANDIDATE / OWNER_TEST_ONLY

## Verified public integration facts

- Provider: Agnes AI
- International OpenAI-compatible base URL: `https://apihub.agnes-ai.com/v1`
- Authentication: Bearer API key
- Key environment name for local/owner setup: `AGNES_API_KEY`
- Primary text model candidate: `agnes-2.5-flash`
- Chat endpoint: `POST /v1/chat/completions`
- Capabilities advertised in current public catalog: chat, streaming, tool calling, coding, reasoning, multi-turn dialogue, image understanding, agent workflows
- Current public free/default text rate reference: 20 executable RPM (30 public-request RPM reference)

## B14 route proposal

```text
provider_id = agnes-ai
model_id = agnes-ai/agnes-2.5-flash
upstream_model = agnes-2.5-flash
credential_source = platform_secret
credential_binding = AGNES_API_KEY
base_url = fixed https://apihub.agnes-ai.com/v1
```

`b14/auto` and explicit model selection must both remain supported.

## Security boundary

- No Agnes key in Git, registry JSON, logs, screenshots, fixtures, issues, PR text, or API responses.
- Actual key installation is owner/local only after code acceptance.
- Fixed upstream origin only; no user-supplied base URL.
- Missing secret fails closed with zero upstream calls.
- Agnes credential cannot be reused for another provider.

## Public/shared-use boundary

Current public Agnes materials clearly support developer API integration and document a Free/default API-key tier. Public materials reviewed for this intake did not provide a sufficiently explicit statement authorizing or prohibiting use of one free/default key as a shared public multi-user inference pool.

Therefore V1 disposition is:

```text
B14_CODE_INTEGRATION = ALLOWED
OWNER/LOCAL_SMOKE = ALLOWED
LIMITED_FIRST_PARTY_TEST = ALLOWED
PUBLIC_SHARED_FREE_POOL = HOLD_PENDING_TERMS_CONFIRMATION
```

Do not mark this provider as generally public/shared-free until terms or account-level guidance is confirmed.

## Source date

Research snapshot: 2026-08-27 Asia/Seoul.
