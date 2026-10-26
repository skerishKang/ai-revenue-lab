# Chat -> COM2 file references (PR-2, #5881)

PR-1 is `apps/padiem-file-lane/`. This change adds the Chat-facing contract;
it does not deploy Chat, install COM2, pick a Tunnel hostname, or package an OS
service. PR-3 uses `COM2_HOST_FACTS` when the operator supplies it.

## Deployment-owned configuration (no live values here)

- `PADIEM_CHAT_FILE_LANE_ORIGIN`: exact HTTPS root origin from the approved
  COM2/Tunnel configuration; no userinfo, URL path, query or fragment.
- `PADIEM_CHAT_FILE_LANE_TICKET_SECRET`: dedicated secret, same value as the
  COM2 service's `FILE_LANE_TICKET_SECRET`; never a user/provider/session key.
  Native Chat reads process configuration. The Worker resolves its own trusted
  secret binding/Secrets Store with the existing `resolve_secret_binding` path.
  The secret has `repr=False` and never goes to a browser or log.

No wrangler vars/secrets, bindings, Tunnel/Access policies or service units are
changed by this PR. Cloudflare authentication remains in place. Browser upload
uses credentials for the configured file origin; COM2 uses the signed user
capability. Any required edge policy for trusted server reads must be composed
by the operator in PR-3; this PR never forwards arbitrary browser cookies or
invents Access credentials.

## Browser/API

`GET /api/files/capabilities` returns readiness for the current authenticated
owner, the 10,000,000-byte automatic routing threshold and phase-1 formats.
Readiness is false when configuration or a verified owner is absent. This keeps
the existing inline attachment path intact in deployments without the new lane.

`POST /api/files/ticket` accepts **only** `{size_bytes: <positive integer>}`.
It uses the verified session/store user, never a user_id or URL from the body.
The existing same-origin cookie guard applies. It returns a ten-minute upload
capability (`upload_url`, signed headers, expires, max_bytes), not the secret.
The HMAC construction reuses `b14_service_proof.service_proof_headers` and maps
its timestamp/body proof into the file service's dedicated header namespace.

When configured, TXT/MD/CSV/PDF >= 10 MB (decimal) use the raw File as the native
fetch body directly to COM2. Neither FileReader, arrayBuffer, base64 nor file
bytes reach the Chat POST. When the old binary parser is unavailable, the prepared COM2 lane also supplies
PDF selection/parsing for smaller PDFs. Otherwise smaller files and phase-1-unsupported types (including
OOXML/images) keep their existing inline path; OOXML service parsing belongs to
the next file-service phase. An activated upload failure is shown to the user,
never silently retried through the Worker with the same large bytes.

Chat/Claw turn wire:

```json
{"attachments": [{"type": "file", "file_id": "file_<32 lowercase hex>"}]}
```

No client-supplied metadata, URL, path or user field is accepted for a reference.
Every turn mints a new read capability for the current verified owner and reads
`/files/{id}/meta` and `/files/{id}/text` at the fixed configured origin, with
redirects and environment-proxy discovery disabled. Original document bytes are
never fetched into the Worker. Metadata and extracted text are validated and
become the same existing `DocumentAttachment`/untrusted context used by inline
documents. Public attachment metadata retains file_id, SHA-256, original size
and name; it excludes extracted text and ticket headers.

Parsing belongs to COM2. Extracted text still traverses the existing model
context path; this does not claim that an arbitrary-size model request can fit
a Worker or the selected model. No new truncation or file/text size ceiling is
introduced. The small metadata contract has a separate 16 KiB transport guard.

The ticket is a per-user bearer capability until expiry, as in PR-1. Expiry is
checked at request start; it is not an upload timeout. No retention/deletion,
OOXML/OCR, Util, B66, PC-result ingestion or model route change is added here.

## Offline evidence

`tests/test_5881_file_lane.py` runs real Chat and COM2 ASGI apps through the
whole ticket/upload/reference/completion seam, verifies HMAC wire parity and
owner isolation, checks same-origin and client-selected-owner refusals, and
runs the shipped browser module in Node. Existing inline and Claw document,
image, binary, streaming and Worker regressions remain part of verification.
