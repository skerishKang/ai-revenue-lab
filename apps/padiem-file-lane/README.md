# COM2 file lane — parser phase 2 (#5881)

Local CPython ASGI service for the Chat/Claw file lane, following
`docs/architecture/FILE_LANE_COM2_MIGRATION_20261026.md`. No Worker receives the
upload bytes. Authentication/session authority remains at Cloudflare; the
service validates a short-lived Chat-signed file capability, never a user's
password or Cloudflare credential.

This PR contains code and offline tests. It does **not** install a service,
create a Tunnel, change production bindings, deploy, or enable the Chat path.
OCR, previews, PC-result ingestion and Util/B66 remain outside this slice.

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
- `GET /files/{file_id}/text`: UTF-8 text/Markdown from Core's canonical
  `document_normalization` / `pdf_markdown` authorities. Supports txt/md/csv,
  PDF native text to Markdown (including page markers), DOCX, PPTX and XLSX.
  UTF-8/BOM and line endings use Core normalization. No OCR is invented: PDF
  pages without native text carry Core's unreadable-page notice.
  The first GET writes an atomic `text-v2.txt` cache; later GETs reuse it.
  Old phase-1 `text.txt` caches are ignored and preserved for rollback.
  Unsupported encoding, encrypted/unreadable PDF or parser failure returns a
  fixed 422 error code; parser exceptions and content are never echoed.
- `GET /files/{file_id}/text?offset=0&max_chars=64000`: read a window of the
  cached result. Offset is a non-negative Unicode code-point index; max_chars
  is positive, defaults to 64000 when either query parameter is present, and
  is a requested window rather than a document-size ceiling. Response remains
  plain UTF-8, with `X-File-Lane-Next-Offset`, `X-File-Lane-EOF` and
  `X-File-Lane-Total-Chars` for traversal. The total is counted once when the
  text is saved and kept in `text-v2.chars`, so a mid-document window still
  states the document's real length; a cache written before that file existed
  is counted once on read and stored.
  EOF/past-EOF returns an empty window. Invalid parameters return 400 before
  parsing. Omitting both parameters preserves the full disk-streamed response.

PDF input stays a seekable disk handle through Core's Markdown converter.
OOXML uses Core's existing in-memory parser on CPython, with the explicit
request-local `ooxml_member_max_bytes=None`; the Worker default stays 32MiB and
archive path/encryption/DTD/inflation checks stay enabled. OOXML payloads and
extracted strings still need host RAM: this is not an external-memory OOXML
parser. Large results persist on disk; window reads skip in bounded blocks and
never load the preceding result in full. No Worker transport-byte limit is
applied by this service. Existing Chat attachment integration remains unchanged
in this PR; its capability list/consumer has not been expanded to OOXML.

JSON failures use `{ok:false,error:{code}}`. Missing/bad/expired ticket: 401;
foreign/unknown file: 404; ticket size: 413; unsupported type: 415;
disk exhausted: 507; storage failure: 503. Partial uploads are removed on size,
disk, disconnect or cancellation failure. Raw parser exceptions are not echoed.
Access logging is disabled; ticket headers must not be printed by a proxy.

## Request journal (#6338 observation gap follow-up)

Every HTTP request appends exactly one JSONL line to
`<FILE_LANE_ROOT>/journal/requests-<UTC date>.jsonl`. A row carries only:
`ts` (UTC, millisecond ISO-8601), `method`, `path` (no query — the upload
filename never enters the journal), `status`, `error_code` (the constant
`FileError` code, `null` on success), `duration_ms`, and `file_size` (bytes of
the committed file, the attempted Content-Length of a failed upload, or
`null`). Filenames, file content, ticket or secret values, exception message
text and raw owner identifiers are never journaled. A journal write failure is
swallowed — the request it observes is unaffected. The journal exists for
incident reconstruction; it does not replace the disabled access log and adds
no request-path restriction.

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
`meta.json`, `text-v2.txt`, `text-v2.chars`; metadata is published last. The
`.chars` counter is the saved code-point total of the cached text, written with
it and re-derived once if an older cache lacks it. No global in-memory file
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


Phase-2 offline fixtures cover all seven formats, UTF-8/emoji window traversal,
cached reads, owner isolation, invalid windows, unsafe archives, and a real
>100MiB PDF uploaded in 1MiB ASGI chunks then parsed through Core. That PDF has
one native-text page and a 100MiB embedded synthetic file: it proves byte-scale
storage/seekable parsing, not many-page performance or a Cloudflare edge limit.
A stored DOCX member above 32MiB proves CPython acceptance and Worker/default
rejection before and after that call. No production upload or deployment runs.
