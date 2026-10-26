# COM2 file lane — phase 1 (#5881)

Local CPython ASGI service for the Chat/Claw file lane, following
`docs/architecture/FILE_LANE_COM2_MIGRATION_20261026.md`. No Worker receives the
upload bytes. Authentication/session authority remains at Cloudflare; the
service validates a short-lived Chat-signed file capability, never a user's
password or Cloudflare credential.

This PR contains code and offline tests. It does **not** install a service,
create a Tunnel, change production bindings, deploy, or enable the Chat path.
OOXML, OCR, previews, PC-result ingestion and Util/B66 are outside phase 1.

## HTTP contract

All file endpoints require the same signed ticket headers. `/health` returns
only `{ "ok": true }` for local supervision. No filesystem paths or secrets
are returned.

- `POST /files?filename=<URL-encoded name>`: raw bytes (not multipart/base64).
  The signed `max_bytes`, advertised Content-Length when present, actual streamed
  byte count and current disk free space are checked. Returns HTTP 201 with
  `{ok,file_id,name,kind,size_bytes,sha256}` after durable original data and
  metadata publication. No whole-request buffer or file-size constant is used.
- `GET /files/{file_id}/meta`: same metadata, scoped to the ticket's user.
- `GET /files/{file_id}/text`: disk-streamed UTF-8 plain text. txt/md/csv use
  incremental UTF-8/BOM decoding; PDF uses pypdf page text extraction. No OCR.
  The first GET writes an atomic text cache; later GETs reuse it. A PDF without
  a text layer returns empty text, not invented OCR. Unsupported encoding,
  encrypted/unreadable PDF or parser failure returns a fixed 422 error code.

JSON failures use `{ok:false,error:{code}}`. Missing/bad/expired ticket: 401;
foreign/unknown file: 404; ticket size: 413; unsupported type: 415;
disk exhausted: 507; storage failure: 503. Partial uploads are removed on size,
disk, disconnect or cancellation failure. Raw parser exceptions are not echoed.
Access logging is disabled; ticket headers must not be printed by a proxy.

## Ticket wire (Chat issuer in PR-2)

Dedicated deployment secret: `FILE_LANE_TICKET_SECRET` (at least 32 characters).
It is shared with the Chat ticket signer only; **do not reuse a provider key or
user secret**. The HMAC construction is identical to existing Chat
`app/b14_service_proof.py`; an executable fixture verifies parity.

1. `raw_claims` is the exact UTF-8 JSON bytes for
   `{ "user_id": "<canonical user id>", "max_bytes": <positive integer>, "expires": <Unix seconds> }`.
2. `X-Padiem-File-Ticket` = unpadded base64url(raw_claims).
3. `X-Padiem-File-Time` = issued Unix seconds as ASCII decimal.
4. `X-Padiem-File-Proof` = lowercase hex
   `HMAC-SHA256(secret, time_ascii + b'.' + raw_claims)`.

The signature is verified with constant-time comparison **before** claims are
trusted. `expires` must be in the future and issued time must be no later than
now and before expiry. A ticket authorizes only its own user namespace until
expiry; possession is a bearer capability, including for GETs. It is not a
one-use ticket. Expiry is checked when a request starts, so an authorized long
upload can finish. PR-2 must issue read/renewal tickets after Cloudflare verifies
the current user; do not extend an expired ticket in this service.

The signed byte budget is per request, not a new product upload ceiling. Chat
can sign the requested file size; this service's physical ceiling is free disk
space and the signed authorization. Concurrent writes can still exhaust disk;
ENOSPC becomes a fixed failure and removes the incomplete upload. No fixed free
space reserve or artificial 1 GiB ceiling is introduced.

Storage is `FILE_LANE_ROOT/<user_id namespace>/file_<uuid>/`. The namespace is
SHA-256 of the **exact** user_id UTF-8 bytes: Windows folds case/trailing dots,
so using raw IDs as path components could alias two owners. Original filenames
are metadata only and never become disk paths. Files are named `data`,
`meta.json`, `text.txt`; metadata is published last. No global in-memory file
index is required across restarts. Keep this root writable only by the service
account; it is outside the checkout and must be on the chosen COM2 disk.

## Running later, after operator approval

Required process/machine environment:

- `FILE_LANE_ROOT`: absolute persistent disk directory (for example a chosen
  directory on the large data disk, never the repository).
- `FILE_LANE_TICKET_SECRET`: deployment-owned HMAC secret, provisioned without
  printing it or putting its value in command history or repository files.
- `FILE_LANE_HOST`: defaults to `127.0.0.1`.
- `FILE_LANE_PORT`: defaults to `8788`.
- `FILE_LANE_ALLOWED_ORIGINS`: optional comma-separated exact Chat HTTPS origins.
  No wildcard. Explicit origins permit credentialed CORS for Cloudflare Access;
  this setting does not validate a Cloudflare cookie or replace edge auth.

From this directory, install the locked environment with
`uv sync --frozen --group dev --extra windows`, then run
`uv run --frozen python -m padiem_file_lane` in the foreground. The process entry
also fits the existing COM2 executor's WSL/systemd supervisor pattern; choose
one host mode when deployment is authorized, never run both against one root.
The uv lock contains the Windows-only pywin32 optional extra.

Native Windows 10 service support is provided by
`padiem_file_lane.windows_service` using pywin32/SCM. In a persistent installed
environment, with machine environment set for the service account, the
operator-only commands are:

```powershell
.venv\Scripts\python.exe -m padiem_file_lane.windows_service --startup auto install
.venv\Scripts\python.exe -m padiem_file_lane.windows_service start
.venv\Scripts\python.exe -m padiem_file_lane.windows_service stop
.venv\Scripts\python.exe -m padiem_file_lane.windows_service remove
```

These commands require the operator's service-install permissions. Merely
importing/running tests never registers, starts or stops an OS service. The CI
checks module import on Windows and actual foreground startup/shutdown on both
OSes, not a live Windows 10 SCM installation. Tunnel must target the local HTTP
port and preserve the existing Cloudflare authentication boundary; Tunnel/edge
configuration is deliberately not created here.

## Tests

`uv run --frozen pytest -q` runs network-free fixtures plus one temporary
loopback startup check. Ubuntu and Windows CI use the same committed lock.
