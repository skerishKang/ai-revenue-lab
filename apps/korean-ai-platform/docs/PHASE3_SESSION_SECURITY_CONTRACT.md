# Phase 3: Session Security Contract

## Ephemeral Key Handling

### Key Lifecycle (Client-Side)

1. User types API key into `<input type="password" id="ws_key">`
2. `onInput` fires: key is captured into `state.apiKey` (JS variable)
3. `input.value` is immediately cleared
4. Key exists only as a JavaScript string in memory
5. On `POST /workspace/api/chat`, key is sent in `X-Business14-Provider-Key` header
6. On page reload, tab close, or explicit "Clear Key", the JS variable is set to `null`

### Prohibited Storage Locations

| Location | Must NOT contain key |
|----------|---------------------|
| `localStorage` | ✅ |
| `sessionStorage` | ✅ |
| `IndexedDB` | ✅ |
| Cookies | ✅ |
| Cache API | ✅ |
| Service Worker | ✅ |
| URL query/fragment | ✅ |
| HTML attribute (`value=`, `data-*`) | ✅ |
| Hidden input | ✅ |
| Server session | ✅ |
| File/DB on server | ✅ |
| Log output | ✅ |
| Response body | ✅ |
| Error response | ✅ |

### Key Display Rules

- Never show any part of the key (no prefix, length, or mask)
- Never display "sk-..." or any portion
- Status display only: "현재 페이지에서만 사용 중" or "API key 없음"

## XSS Boundary

All user prompt and assistant response content is rendered via `textContent`,
never `innerHTML`.

### Attack Vectors Tested

| Input | Expected Behaviour |
|-------|-------------------|
| `<script>alert(1)</script>` | Rendered as literal text |
| `<img src=x onerror=alert(1)>` | Rendered as literal text |
| `{{7*7}}` | Rendered as literal text |
| `</textarea><script>alert(1)</script>` | Rendered as literal text |

## Request Validation

All workspace API requests are validated against `PilotChatRequest` schema:

- `extra="forbid"` — unknown fields rejected
- `role` restricted to `system`, `user`, `assistant`
- `content` non-empty, max 32,000 chars
- `temperature` 0.0–2.0
- `max_tokens` 1–4096
- `messages` 1–100 items

## Error Safety

All user-facing errors contain:
- Fixed Korean message (no internal details)
- `request_id` for traceability

User-facing errors never contain:
- API key
- Authorization header
- Endpoint URL
- Internal registry data
- Stack trace
- File paths

## Key Isolation

Each workspace request uses the model ID to `resolve_route()`, which
determines the correct provider. The API key from the header is forwarded
only to that provider's transport.

Cross-provider key leakage is prevented by:
1. RouteTarget per request (single provider per request)
2. No shared key storage between requests
3. Transport is per-request

## Error Codes

All error codes from Phase 2 are preserved and displayed with Korean messages:

- `registry_invalid`
- `model_not_found`
- `model_disabled`
- `missing_provider_key`
- `placeholder_key_rejected`
- `upstream_auth_failed`
- `upstream_rate_limited`
- `upstream_timeout`
- `upstream_server_error`
- `malformed_upstream_response`
- `internal_error`

## Currently Not Implemented

- DNS rebinding protection
- Content Security Policy (CSP) headers
- Subresource Integrity (SRI) for JS
- End-to-end encryption for API keys in transit
- Key expiration or rotation
- Audit logging of key usage
- Multi-factor authentication
