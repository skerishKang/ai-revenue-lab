# PADIEM Android 1.0.1 — Connector server contract (#5080)

> **Status:** 2026-10-19. Server-side implementation and Mock Android agent verification only.
> No production Worker, D1, Secret, DNS change, no APK build/sign, and no real-phone execution is claimed here.
>
> **Related issues:** #5080 (this contract), #5015 (PC tools / Android tools), #4139 (Broker approval, dispatch and return-leg pipeline).
> **Reference implementation:** the Windows Connector / canonical Local Agent Broker. This document adds only the Android-specific adapter.

## 1. Scope

The Android app is one more device on the **existing** canonical Local Agent Broker:

```text
canonical enrollment / binding / device credential / session
-> owner-selected SAF folder declaration (/android-profile)
-> owner-confirmed TXT read request (Chat API)
-> canonical approval receipt + enqueue_command_with_material
-> phone poll / material / admission / SAF read / acknowledge
-> verified text result (/text-result)
-> existing projection appends the text to the originating conversation
```

Not in this lane:

- no second identity, account, workspace, session or device authority;
- no Android-specific command store, approval store, encryption key or result projection;
- no executable/material sent to the phone: `argv` is `[]` and no process is spawned;
- no `content://` URI, absolute path, drive letter or real filesystem path is stored or returned;
- Android does not build or verify commands; it only verifies and performs the exact read the receipt names.

## 2. Authority reuse

| Concern | Authority reused | Android-specific addition |
| --- | --- | --- |
| Enrollment / binding / credential | Canonical connector enrollment (issue → redeem → handoff) | none |
| Device session | Broker `/session` (device credential + live session) | none |
| Device HTTP surface | One private service-binding envelope, canonical route set | `/android-profile` route |
| Approval object model | `padiem_ai_core.agent_approval` pause/decision | Android receipt discriminator and constants |
| Command material fingerprint | `command_material_fingerprint_for` in the Chat app | none |
| Exactly-once enqueue | `enqueue_command_with_material` (request fingerprint + revision) | none |
| Result transport | `/text-result` (`claw-local-agent-text-result.v1`) | none |
| Result projection | `claw_local_task_result_composition` / projection | none (existing result label is shared with the PC lane) |
| Owner device directory | Broker device directory | additive `platform` / capability / folder-count metadata |

## 3. Enrollment and session (unchanged)

Android uses the existing connector enrollment API, not a new registration route:

```text
POST /api/claw/connector/enrollments/issue
POST /api/claw/connector/enrollments/redeem
POST /api/claw/connector/enrollments/consent/grant
POST /api/claw/connector/enrollments/consent/revoke
```

The redeem response is the public, secret-free receipt: `binding_ref`, `device_id`,
`account_ref`, `workspace_ref`, `consent_id`, `credential_generation`,
`credential_expires_at`, `credential_installed_by_canonical_handoff: true`,
`raw_device_credential: false`, `lifecycle: "paired_offline"`,
`dispatch_authorized: false`, `grants_read: false`, `grants_write: false`.

Server rules:

- a device acts only inside the account/workspace of its authenticated binding;
- the owner consent row must exist for the exact `device_id`, be un-withdrawn, and name the same connector workspace the B54 session resolves;
- a revoked or expired binding, or a rotated credential generation, cannot mint a read;
- the browser never supplies `account_ref`, `workspace_ref`, `binding_ref`, `credential_b64`, `consent_id`, `command_id`, approval refs or a SAF URI.

### 3.1 Private device HTTP envelope (unchanged)

Every device call is the same closed envelope, sent through the private service binding:

```json
{
  "method": "POST",
  "route": "/poll",
  "content_type": "application/json",
  "body_b64": "<base64 of the UTF-8 JSON body>",
  "tls_verified": true
}
```

- `tls_verified` must be `true`; the outer edge terminates and verifies TLS.
- `method` must be `POST`; every route requires a JSON object body carrying `binding_ref` and `credential_b64`.
- Bodies are bounded; unknown envelope keys, routes or content types fail closed.
- **This envelope is what the private Service Binding carries, not what the phone sends.** The app performs an ordinary `POST https://<ingress>/<route>` with the plain JSON body (§4, §7.1); the broker state worker's private bridge (`local_agent_broker_private_http_bridge.py`) base64s that body into this shape and sets `tls_verified` from the verified HTTPS termination. A client that sends this envelope as its own JSON body is refused.
- Routes: `/session`, `/poll`, `/material`, `/admission`, `/heartbeat`, `/acknowledge`, `/reconcile`, `/office-part`, `/text-result`, `/execution-profile`, `/android-profile`.
- `/admission` is the only route on this surface that mints references. The device identifies the exact queued command and fingerprint; the server owns `admission_ref` and `evidence_ref` and returns them in the response. A request body carrying either key is refused by the closed schema.

## 4. SAF folder declaration — `POST /android-profile`

Sent by the phone **after** the owner selects folders in the Android system picker. This action declares access scope only; it grants no execution.

Request body (inside the envelope, exactly these keys):

```json
{
  "contract_version": "claw-local-android-saf-profile.v1",
  "session_id": "session.android.1",
  "profile_ref": "profile.android.saf-txt.v1",
  "folders": [
    {"root_ref": "safroot-documents", "display_name": "Documents"},
    {"root_ref": "safroot-notes", "display_name": "Notes"}
  ],
  "binding_ref": "binding.android.1",
  "credential_b64": "<base64 device credential>"
}
```

Field rules:

| Field | Rule |
| --- | --- |
| `root_ref` | Opaque phone-minted handle, 1–256 chars, `[A-Za-z0-9][A-Za-z0-9._:@+-]*`. No `/`, `\`, `content:` URI, `.`, `..`. The server never interprets it. |
| `display_name` | Presentation only, 1–80 chars, no control characters, no `/` or `\`, no surrounding whitespace. |
| `folders` | 0–8 unique `root_ref` values. `[]` is the truthful "owner withdrew SAF access" state. |
| Duplicate / extra keys | Refused (closed object). |

Response (HTTP 200 on the private surface):

```json
{
  "ok": true,
  "android_profile": {
    "accepted": true,
    "profile_ref": "profile.android.saf-txt.v1",
    "platform": "android",
    "folder_count": 2,
    "credential_generation": 1,
    "raw_device_credential": false,
    "saf_uri_exposed": false
  }
}
```

Refusals return HTTP 409 with `{"ok": false, "error": {"code": "android_profile_refused", ...}}`. The declaration is replaced atomically: a removed folder stops being requestable immediately. The stored set is revalidated against the **current** active binding generation on every read and every read-request.

Private reads (service binding only, never a public HTTP GET):

```json
{"account_ref": "...", "workspace_ref": "...", "device_id": "...",
 "binding_ref": "...", "profile_ref": "profile.android.saf-txt.v1"}
```

returns `{"ok": true, "profile": {..., "capabilities": ["local.filesystem.read"], "read_suffix": ".txt", "folders": [...], "server_verified": true}}`.

```json
{"account_ref": "...", "workspace_ref": "..."}
```

returns `{"ok": true, "platform": "android", "profiles": [{"binding_ref": "...", "device_id": "...", "platform": "android", "capabilities": ["local.filesystem.read"], "read_suffix": ".txt", "folder_count": 2}]}`. This projection contains **no folder references** and never claims ONLINE.

## 5. Browser API for the owner confirmation

### 5.1 List the declared folders

```text
GET /api/claw/connector/android-text-reads/folders?device_id=device.android.1
```

Requires the B54 owner session cookie. Any additional query key (for example `account_ref`) is rejected with HTTP 400 before any broker call.

```json
{
  "ok": true,
  "available": true,
  "device": {
    "device_id": "device.android.1",
    "platform": "android",
    "profile_ref": "profile.android.saf-txt.v1",
    "capabilities": ["local.filesystem.read"],
    "read_suffix": ".txt",
    "folders": [
      {"root_ref": "safroot-documents", "display_name": "Documents"},
      {"root_ref": "safroot-notes", "display_name": "Notes"}
    ]
  }
}
```

Only the phone-declared set is returned. No SAF URI, local path, credential or session secret is exposed.

### 5.2 Request one confirmed read

```text
POST /api/claw/connector/android-text-reads/request
Content-Type: application/json
Origin: <exact same origin>
Cookie: <B54 owner session>
```

```json
{
  "device_id": "device.android.1",
  "root_ref": "safroot-documents",
  "path_relative": "notes/report.txt",
  "run_id": "run.android.1",
  "confirmed": true
}
```

Exactly these five keys. `confirmed` must be `true`; `path_relative` must be a relative `.txt` display path (NFC, no URI scheme, no drive letter, no `.`/`..`/empty segment, at most 1024 characters).

Success:

```json
{
  "ok": true,
  "command": {
    "command_id": "andcmd-...",
    "run_id": "run.android.1",
    "tool_request_ref": "andtool-..."
  },
  "conversation_id": "chat_..."
}
```

`root_ref` must be one of the phone's declared folders (`403 android_read_folder_not_allowed` otherwise). If the phone has withdrawn every folder, the answer is `409 android_read_folder_selection_required` so the UI sends the owner back to the system picker.

## 6. Dispatch material and approval receipt

The Chat server mints one closed receipt and enqueues it atomically through the existing Broker call. Android receives the material from `/material`; the canonical command reference comes from `/poll`.

Material (inside the `/material` response, `material` object):

```json
{
  "request_id": "andreq-...",
  "run_id": "run.android.1",
  "device_id": "device.android.1",
  "root_ref": "safroot-documents",
  "argv": [],
  "cwd_relative": ".",
  "requested_at": "2026-10-19T06:00:00Z",
  "timeout_seconds": 30,
  "shell_authority": false,
  "admin_elevation": false,
  "environment_payload": null,
  "provider_authority": null,
  "p01_approval_payload": { "...": "receipt below" }
}
```

Receipt:

```json
{
  "format": "claw-android-saf-txt-read-approval.v1",
  "evidence_ref": "andevidence-...",
  "command_id": "andcmd-...",
  "request_id": "andreq-...",
  "approval_pause": {
    "pause_id": "andpause-...",
    "run_id": "run.android.1",
    "agent_runtime_id": "claw_android_saf_txt_v1",
    "tool_id": "local.filesystem.read",
    "invocation_sha256": "<SAF read fingerprint>",
    "requirement": "user_confirmation",
    "step_index": 1,
    "created_at": "2026-10-19T06:00:00Z",
    "expires_at": "2026-10-19T06:05:00Z",
    "approval_scope": ["filesystem.read"]
  },
  "approval_decision": {
    "decision_id": "anddecision-...",
    "pause_id": "andpause-...",
    "outcome": "approved",
    "authority_ref": "claw_connector_android_txt_request_v1",
    "evidence_ref": "andevidence-...",
    "decided_at": "2026-10-19T06:00:00Z"
  },
  "exact_tool_arguments": {
    "action_id": "andact-...",
    "run_id": "run.android.1",
    "device_id": "device.android.1",
    "root_ref": "safroot-documents",
    "operation": "read",
    "path_relative": "notes/report.txt",
    "requested_at": "2026-10-19T06:00:00Z",
    "request_fingerprint": "<SAF read fingerprint>",
    "content_bytes": 0,
    "content_sha256": null,
    "directory_enumeration": false,
    "recursive_delete": false,
    "admin_elevation": false
  },
  "local_policy_ref": "padiem_android_saf_selected_root_read_policy_v1",
  "expires_at": "2026-10-19T06:05:00Z"
}
```

`argv` is always empty for this lane. The phone must not interpret it and must not execute any process.

### 6.1 SAF read fingerprint

The phone verifies `approval_pause.invocation_sha256 == exact_tool_arguments.request_fingerprint`, then recomputes it over the canonical intent before touching a document.

```text
SHA-256( UTF-8( JSON(
  {"v": 1,
   "action_id": <action_id>,
   "run_id": <run_id>,
   "device_id": <device_id>,
   "root_ref": <root_ref>,
   "operation": "read",
   "path_relative": <NFC-normalized relative path>,
   "requested_at": <ISO-8601 Z text>},
  keys sorted, separators "," and ":", ensure_ascii=false, no NaN
) ) )
```

Pinned vector (must be reproduced by the Android implementation):

```text
action_id      = "andact-vector-1"
run_id         = "run.android.vector.1"
device_id      = "device.android.vector.1"
root_ref       = "safroot-documents"
path_relative  = "notes/report.txt"
requested_at   = "2026-10-19T06:00:00Z"

SAF read fingerprint =
fb438c4de05d28b5c840a7af23b3eab9dbd223139ba92f2c88cfdf050a994e79
```

The Broker command fingerprint is the existing PC/Android-shared algorithm over the same material (`request_id`, `run_id`, `device_id`, `root_ref`, empty `argv`, `cwd_relative`, `requested_at`, `timeout_seconds`). The phone echoes the server value from `/poll`; it does not mint it.

## 7. Android execution flow

```text
POST /session       -> live device session (canonical credential)
POST /poll          -> queued command correlation {command_id, run_id, tool_request_ref, sequence, request_fingerprint, revision_ref}
POST /material      -> exact material + receipt for that queued command
verify receipt      -> format/policy/authority constants, command_id, request_id, revision, fingerprint, expires_at, declared root_ref
POST /admission     -> server-owned admission transition; returns admission_ref, evidence_ref, revision_ref, request_id, sequence
POST /text-result   -> {"state": "pending"} intent (before the actual read)
SAF read            -> exact .txt document under root_ref/path_relative, at most 768 UTF-8 bytes
POST /acknowledge   -> termination "exited", exit_code 0, exact admission/evidence/revision/request refs
POST /text-result   -> {"state": "content", content_utf8, content_sha256, content_bytes}
```

### 7.1 `POST /admission` — where the acknowledgement references come from

`/acknowledge` refuses an acknowledgement that does not echo the `admission_ref` and
`evidence_ref` the Broker stored, and `/poll` never carries them: a queued command has
no admission yet. The phone reads both values exclusively from this response.

Request body (inside the envelope, exactly these keys):

```json
{
  "session_id": "session.android.1",
  "binding_ref": "binding.android.1",
  "credential_b64": "<base64 device credential>",
  "command_id": "andcmd-...",
  "request_fingerprint": "<Broker command fingerprint>",
  "request_id": "andreq-...",
  "now": "2026-10-19T06:00:00Z"
}
```

`command_id`, `request_fingerprint` and `sequence` come from `/poll`; `request_id` comes
from `/material`. `now` is client evidence only — the server clock owns the acceptance
time. The canonical Broker remains the sole owner of the queued → admitted transition,
so an already admitted or acknowledged command is refused with `broker_command_replay`
and an expired one with `broker_command_expired`.

Response:

```json
{
  "ok": true,
  "admission": {
    "admission_ref": "admission.<server-minted>",
    "evidence_ref": "evidence.<server-minted>",
    "authority_ref": "control-plane.local-agent-broker.production.v1",
    "command_id": "andcmd-...",
    "session_id": "session.android.1",
    "binding_ref": "binding.android.1",
    "run_id": "run.android.1",
    "tool_request_ref": "andtool-...",
    "sequence": 1,
    "request_fingerprint": "<Broker command fingerprint>",
    "request_id": "andreq-...",
    "revision_ref": "rev.<server-owned>",
    "accepted_at": "2026-10-19T06:00:00Z",
    "expires_at": "2026-10-19T06:05:00Z",
    "raw_argv": false,
    "raw_device_credential": false
  }
}
```

The phone stores `admission_ref`, `evidence_ref`, `revision_ref` and `request_id`
durably and echoes them unchanged to `/acknowledge` (and to `/reconcile` if the process
dies before the acknowledgement). Admission is a new-work transition, so it is refused
with `owner_pc_paused` while the owner has paused device work, exactly like `/poll` and
`/material`.

Rules the server enforces:

- the session must be current and belong to the authenticated binding/account/workspace;
- `/material` returns only the command at the exact queued sequence and matching request fingerprint;
- the pending intent is accepted only while the command is canonically admitted or acknowledged; the content body additionally requires the successful acknowledgement (`exited`, exit code 0, matching refs, active binding generation);
- the device never supplies account, workspace, binding, command, run or approval refs for the result; ownership and correlation are read back from the persisted canonical command;
- a result is refused if the command did not finish successfully or if the fingerprint/correlation does not match.

`/text-result` request keys (plus `binding_ref` and `credential_b64`):

```json
{
  "contract_version": "claw-local-agent-text-result.v1",
  "command_id": "andcmd-...",
  "run_id": "run.android.1",
  "request_fingerprint": "<Broker command fingerprint>",
  "state": "pending"
}
```

```json
{
  "contract_version": "claw-local-agent-text-result.v1",
  "command_id": "andcmd-...",
  "run_id": "run.android.1",
  "request_fingerprint": "<Broker command fingerprint>",
  "state": "content",
  "content_utf8": "<text>",
  "content_sha256": "<lowercase SHA-256 of the UTF-8 bytes>",
  "content_bytes": 42
}
```

Bounds: `content_bytes <= 768`. No stdout, binary, directory listing or multiple files.

## 8. Return to the original conversation

The existing projection (`LocalRunnerResultSource` / `project_local_runner_terminal_result`) appends one deterministic message (`msg_ltr_<...>`) to the run's stored `conversation_id`:

1. before any terminal fact: nothing is appended;
2. pending intent: terminal-only projection is suppressed so the text is not lost to the stable message id;
3. terminal acknowledged without content: existing terminal-only behaviour;
4. verified content: exactly one message containing the verified text.

A re-delivered result or a re-poll after the append adds nothing; `evidence_ref`, `command_id` and `revision_ref` are correlated on the run row.

Current shared projection limitation: the message label is the existing PC file-read label. An Android-specific label is a follow-up presentation change, not part of this server contract.

## 9. Offline, withdrawal, timeout, duplicate and retry

| Situation | Behaviour |
| --- | --- |
| Phone offline at request time | Command stays queued; the browser gets the command correlation immediately. The conversation stays unchanged until a terminal fact exists. |
| SAF permission withdrawn | An empty `/android-profile` replaces the set. A later read request for any previously declared folder is refused (`403`, or `409 android_read_folder_selection_required` when the set is empty). A previously enqueued command cannot be re-minted with the withdrawn folder. |
| Command expires (TTL) | Admission/acknowledgement after `expires_at` is refused with `broker_command_expired`; the projection reports expiry; no content can be staged as success. |
| Retried enqueue (lost response) | Same command id, fingerprint and revision; one command, one material, one sequence. |
| Retried acknowledgement | Same terminal facts; not a second execution. |
| Duplicate read request for the same run | The pre-written run correlation refuses a second command (`409 android_read_run_already_bound`). |
| Re-delivered `/text-result` content | Idempotent for the same command/fingerprint; the conversation is not appended twice. |
| Credential rotation / binding revocation | Private profile read and read-request resolution fail; stale folder grants stop working. |

## 10. Refusal codes (browser-facing)

| HTTP | `error.code` | Meaning |
| --- | --- | --- |
| 400 | `android_read_device_query_invalid` | Folders query is not exactly `device_id`. |
| 400 | `android_read_invalid_body` / `android_read_refused` | Body shape or path/root value refused. |
| 401 | `android_read_auth_required` | No verified B54 owner session. |
| 403 | `android_read_consent_required` | No un-withdrawn consent for this device or workspace mismatch. |
| 403 | `android_read_device_not_usable` | Canonical binding is not usable. |
| 403 | `android_read_folder_not_allowed` | `root_ref` is not in the declared set. |
| 404 | `android_read_device_unbound` | Device is not bound for this owner/workspace. |
| 404 | `android_read_run_unavailable` | Run does not exist for this owner/workspace. |
| 409 | `android_read_profile_required` | Phone has not declared a SAF folder set. |
| 409 | `android_read_folder_selection_required` | Declared set is empty; ask the owner to select folders. |
| 409 | `android_read_run_already_bound` | This run already has a command correlation. |
| 409 | `android_read_enqueue_refused` | Broker refused the enqueue. |
| 413 | `android_read_request_too_large` | Body exceeds 4096 bytes. |
| 415 | `android_read_unsupported_media_type` | Not `application/json`. |
| 503 | `android_read_unconfigured` / `android_read_broker_unavailable` | Server dependency unavailable; fail closed. |

## 11. Android implementation checklist

1. Enroll through the existing connector enrollment and store the device credential with the platform secure store.
2. Open a Broker session and keep it current; send the canonical envelope with `tls_verified: true`.
3. After the owner picks SAF trees, call `/android-profile` with opaque `root_ref` values minted by the app. Never send `content://` URIs or filesystem paths.
4. Read `GET .../android-text-reads/folders` state in the UI; if empty, show the folder-selection action.
5. On `/poll`, admit only a command whose receipt format is `claw-android-saf-txt-read-approval.v1`; reject any other format for this lane.
6. Fetch `/material`, verify the receipt constants, command/request/revision correlation, expiry and the SAF fingerprint vector implementation.
7. Post `/admission` for that exact command and persist the returned `admission_ref`, `evidence_ref`, `revision_ref` and `request_id` before touching a document; the app never mints or guesses either reference.
8. Resolve `root_ref` through the persisted SAF tree and read only the exact `.txt` document; never enumerate directories and never leave the selected root.
9. Send the `pending` intent, perform the bounded read, acknowledge with `exited`/`0`, then send the `content` body with SHA-256 and byte count.
10. Retry by resending the exact byte-identical acknowledgement or enqueue; do not mint a new command for a retry. After a process death, recover with `/reconcile` using the durably stored admission references.
11. On withdrawal, send `/android-profile` with `folders: []` and stop dispatching reads.

## 12. Verification status

- **Mock Android agent over ASGI + real SQLite D1/Broker storage:** PASS (see the focused tests listed in the PR).
- **Server-owned admission over the real private device edge:** PASS — `session → poll → material → admission → acknowledge` is driven from `handle_private_device_fetch` in `packages/padiem-control-plane/tests/test_local_agent_broker_device_admission_reachability.py`, which is the test that fails with `404 local_agent_http_route_not_found` when `/admission` is not in `DEVICE_HTTP_ROUTES`.
- **Real Android phone / APK:** NOT VERIFIED. No APK build or signing was performed.
- **Production Worker / D1 / Secret / DNS:** NOT CHANGED, and not re-read live in this change. The served `padiem-local-agent-broker-state` / `-edge` versions were built from source where `/admission` was absent from `DEVICE_HTTP_ROUTES`, and both edges derive their allowlist from that list, so the mounted route is not live until CENTRAL deploys this source. `B54_LOCAL_AGENT_ACTIVATION_RUNBOOK.md` is the activation procedure and records the pin the gate checks.
- **Production routing/live flag:** this change does not enable or deploy the private device route.

Focused evidence lives in:

- `packages/padiem-control-plane/tests/test_local_agent_broker_android_profile_5080.py`
- `packages/padiem-control-plane/tests/test_local_agent_broker_device_admission_reachability.py`
- `apps/padiem-chat/tests/test_5080_connector_android_read.py`
- `apps/padiem-chat/tests/test_5080_android_connector_e2e.py`

## 13. Device integration point (what the Android app calls)

The approved device endpoint is the existing Local Agent broker ingress; Android adds no
host, no second credential and no manual device-ID entry step:

```text
public HTTPS ingress   https://local-agent.padiem.net            (worker padiem-local-agent-broker-edge)
                       -> private Service Binding LOCAL_AGENT_BROKER_SERVICE
                       -> padiem-local-agent-broker-state / LocalAgentBrokerDurableObject
                       -> the canonical broker authority named by LOCAL_AGENT_BROKER_AUTHORITY_REF
```

```text
POST https://local-agent.padiem.net/session
POST https://local-agent.padiem.net/poll
POST https://local-agent.padiem.net/material
POST https://local-agent.padiem.net/admission
POST https://local-agent.padiem.net/acknowledge
POST https://local-agent.padiem.net/text-result
POST https://local-agent.padiem.net/android-profile
```

Each call is `POST` with `Content-Type: application/json` and the §3.1 envelope-equivalent
body carrying the `binding_ref` plus the `credential_b64` that the existing enrollment
redeem installed through the canonical handoff. TLS is terminated and verified at the
edge; the app never sends an account, workspace, consent, command or approval reference
and never receives a raw credential from the server.

Owner-side registration stays on the existing Chat API
(`POST /api/claw/connector/enrollments/issue` → `…/redeem` → `…/consent/grant`), which is
mounted whenever the Chat Worker composes the canonical Identity + Broker ports.
