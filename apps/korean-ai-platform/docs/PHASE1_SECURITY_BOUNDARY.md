# Phase 1: BYOK Gateway Pilot — Security Boundary

## Key Forwarding Path

```
Client (Browser)
  │  POST /api/pilot/v1/chat/completions
  │  Header: X-Business14-Provider-Key
  ▼
Business 14 Pilot Gateway
  │  Extracts key from header (runtime only)
  │  Builds Authorization: Bearer <key>
  │  Forwards to configured upstream
  ▼
Upstream Provider (config-only, https://)
```

## What Is NOT Stored

- API key is **never written to disk**
- API key is **never stored in database**
- API key is **never stored in session**
- API key is **never stored in browser storage**
- API key is **never cached in memory beyond request lifecycle**

## Logging Policy

**Default log includes:**
- Request ID (b14req_*)
- Business 14 model ID
- Provider ID
- HTTP status code
- Latency (ms)
- Token count (when available)
- Normalized error code

**Default log excludes:**
- API key (entire X-Business14-Provider-Key header)
- Authorization header value
- Full user prompt content
- Full upstream response body
- Personally identifiable information
- Internal configuration values

Logging uses `redaction.redact_headers()` for safe header logging.

## SSRF Prevention

1. **Base URL is server-configured only** — set via `BUSINESS14_PILOT_BASE_URL`
2. **No user-supplied URL** — request schema has no `base_url` field
3. **Validation at startup**: rejects non-https:// URLs
4. **Blocked destinations**:
   - `localhost`, `127.0.0.1`, `::1`, `0.0.0.0`
   - Private IP ranges: `10.*`, `192.168.*`, `172.16-31.*`
   - Link-local: `169.254.*`
5. **HTTPS enforced** — http:// is rejected by `_validate_base_url()`

## Redirect Policy

- `follow_redirects=False` in all upstream HTTP calls
- 302/3xx responses from upstream cause an error (502)

## Timeout Policy

- Default: 30 seconds (configurable via `BUSINESS14_PILOT_TIMEOUT_SECONDS`)
- Timeout results in `504 Gateway Timeout` with error code `upstream_timeout`
- No separate connect/read timeout in Phase 1 (single timeout)

## Error Handling

**Never included in error responses:**
- API key or any part of it
- Authorization header value
- Full upstream response body
- Internal file paths
- Stack traces
- Full configuration values
- Private endpoint URLs

**Always included in error responses:**
- Stable error code (e.g., `upstream_auth_failed`)
- Korean-language user message
- Request ID for traceability

## Not Yet Implemented (Phase 1)

- Rate limiting at gateway level
- Request body encryption at rest
- Upstream TLS certificate pinning
- Audit log for key usage
- Multi-tenant key isolation
- Encrypted key storage (future phase feature)
