# AI Provider Guidance — Living Travel Phase 3A

## Default provider

The default provider is `mock`.  No external configuration is required.

    LT_AI_PROVIDER=mock          # default

The mock provider uses deterministic synthetic fixtures.  It never sends data
over the network and never calls a real AI endpoint.

## Configuration contract

| Variable | Required | Default | Description |
|---|---|---|---|
| `LT_AI_PROVIDER` | No | `mock` | `mock` or `openai_compatible` |
| `LT_AI_BASE_URL` | For `openai_compatible` | — | Provider API base URL (see below) |
| `LT_AI_API_KEY` | For `openai_compatible` | — | Bearer-token credential |
| `LT_AI_MODEL` | For `openai_compatible` | — | Model identifier (e.g. `gpt-4o-mini`) |
| `LT_AI_TIMEOUT_SECONDS` | No | `30` | Per‑request timeout (1–120) |
| `LT_AI_COST_CLASS` | No | `free` | One of: `free`, `paid`, `local`, `unknown` |

Unrecognised provider names, missing required fields for `openai_compatible`,
out‑of‑range timeouts, and invalid cost classes all produce a startup
`ValueError` (fail‑closed).

## openai_compatible setup

    LT_AI_PROVIDER=openai_compatible
    LT_AI_BASE_URL=https://api.openai.com       # or your OpenAI‑compatible endpoint
    LT_AI_API_KEY=...
    LT_AI_MODEL=gpt-4o-mini

The base URL may include the `/v1` prefix.  The final chat‑completions URL is
built automatically (e.g. `https://api.openai.com/v1/chat/completions`).
Double‑slash, query, and fragment injection are prevented.

## Local model loopback policy

| Environment | HTTP localhost allowed? | Example |
|---|---|---|
| `development` | Yes (localhost / 127.0.0.1 / ::1 only) | `http://localhost:11434` |
| `testing` | Yes (any destination) | `http://example.com:8080` |
| `staging` / `production` | No (HTTPS only, no private/loopback) | `https://api.openai.com` |

## Staging/production HTTPS policy

In `staging` and `production` environments the base URL **must** use the
`https://` scheme.  HTTP, localhost, loopback, private (10.x, 172.16–31.x,
192.168.x, 169.254.x) and link‑local addresses are rejected at startup.

## Source boundary

The provider never receives raw source content.  The pipeline sends only
normalised structured input:

- Traveler preferences (destination, duration, context, budget, pace, tone,
  length, interests, exclusions)
- Approved source-bundle summaries
- Prior structured content (second edition only)
- Persisted feedback (second edition only)

Generated `source_ref` values are validated against the approved set of
persisted source IDs **before** content is persisted.  Unknown or fabricated
sources cause generation to fail and prevent `pending_review` storage.

## PII and secret non‑transmission policy

The following are **never** sent to the network provider:

- Firebase UID
- User email
- Password
- Invitation code
- Operator ID
- Database URL
- Service‑account information
- Internal auth tokens
- Raw `Authorization` header value
- Raw traveler `raw_text`
- Other traveler data
- Audit records unrelated to the request

The API key is used only in the `Authorization: Bearer` header of the
outbound request.  It is never included in error messages, log records, or
stored as part of the `ProviderResult`.

## No automatic publication

The pipeline always ends in `pending_review` on success.  Content is not
published until an operator explicitly transitions the edition to `published`.

## Phase 3A scope

Phase 3A implements the **provider contract** only:

- Settings validation (fail‑closed)
- `OpenAICompatibleProvider` implementing `AIProvider` protocol
- Provider factory (`create_ai_provider`)
- Pipeline integration (first‑ and second‑edition paths)
- Source governance and structured‑response validation
- Full network‑free test coverage

Live provider activation (connecting to a real OpenAI‑compatible endpoint
with synthetic staging smoke tests) is **Phase 3B**.
