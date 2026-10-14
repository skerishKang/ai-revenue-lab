# #4139 — Broker verified TXT result + Windows production Request Port contract (2026-10-15)

Scope of this change set: the two P0 pieces of the "read one real Windows TXT in
Claw" goal that belong to the **canonical Broker / Windows client contract**
lanes. It adds no second transport, broker, account system or auth system.

| # | Deliverable | Where |
|---|---|---|
| 1 | Importable production **Request Port factory** + operation→endpoint map + authority/URL/config contract | `apps/korean-ai-code-agent/src/kagent/local_agent_production_request_port.py` |
| 2 | Canonical Broker **verified TXT result** route (`/file-result`), durable store, and the `read_verified_file_text` private RPC | `packages/padiem-control-plane/` |

Nothing in `#3936` was touched: its three unmerged commits and its worktree are
left exactly as they were found, and no change here refers to them.

---

## 1. Windows production Request Port factory (LOCAL2 hand-off)

**Module:** `kagent.local_agent_production_request_port` (importable, no side
effects on import).

It **reuses** the existing client stack and adds only wiring facts:

* transport = `StdlibPinnedHttpsJsonRequestPort` (TLS default context, redirects
  refused, JSON only, bounded request/response, no caller endpoint override)
  via `RuntimeStdlibPinnedHttpsJsonRequestPort` (adds `/heartbeat`);
* broker = the existing canonical device HTTP surface
  (`packages/padiem-control-plane/local_agent_broker_device_http.py`,
  `DEVICE_HTTP_ROUTES`);
* authority = the existing PADIEM public origin `chat.padiem.net`.

### Exact facts LOCAL2 needs

```
authority        chat.padiem.net
broker_url       https://chat.padiem.net/api/claw/connector/gateway
scheme/port      https / 443
method           POST
content-type     application/json
mount_path       /api/claw/connector/gateway    (declared contract value)
```

Operation → **existing** endpoint (mount + route):

| operation | endpoint |
|---|---|
| session | `/session` |
| poll | `/poll` |
| material | `/material` |
| heartbeat | `/heartbeat` |
| acknowledge | `/acknowledge` |
| reconcile | `/reconcile` |
| **file-result** (new, #4139) | `/file-result` |

`/office-part` is the only canonical route with no resident operation (it is the
#3580 opt-in byte-staging route).

Factory API:

```python
from kagent.local_agent_production_request_port import (
    build_production_request_port,          # -> ProductionRequestPort (reused pinned port)
    build_production_transport_config,      # -> OutboundTransportConfig (pinned authority)
    verify_operation_path_mapping,          # -> proves every operation resolves to its route
    production_broker_configuration_contract,  # -> the safe dict above, for review/reporting
    verified_file_result_payload,           # -> the exact closed /file-result upload payload
    parse_file_result_submission_response,  # -> closed parse of the broker receipt
)
```

Config bounds (unchanged canonical values): heartbeat 5–300 s, poll timeout
1–60 s, response bound 1 KiB–1 MiB, TLS required, no public inbound port. The
device credential stays in the existing DPAPI store and is resolved at request
time exactly as the transport already does; the factory never reads or logs it.

**Not claimed by this module:** `PRODUCTION_BROKER_MOUNT_DEPLOYED = False`,
`PRODUCTION_BROKER_CONNECTION_VERIFIED = False`. The canonical broker source
still reports `PRODUCTION_ROUTE_CONFIGURED = False`, and no live Windows round
trip was performed here. Attaching the public route and running the real
connection is CENTRAL's deployment step; a 404 on the path above is expected
until then (the same observation CENTRAL recorded on 2026-10-14).

---

## 2. Verified Windows TXT result (Broker side)

### 2.1 Why a separate route

The acknowledgement keeps carrying only the bounded terminal outcome and
correlation — it cannot carry a body, and it must not. Device stdout is never
trusted, and no fixture may stand in for a read. So the real content travels on
its own canonical device route, `/file-result`, is stored durably, and is served
to Claw through a private read-only RPC.

### 2.2 `/file-result` (device → broker, authenticated, POST, JSON)

Request keys — exactly these:

```
session_id, binding_ref, credential_b64,          # existing device session auth
command_id, revision_ref, request_id, evidence_ref,  # exact correlation the device holds
kind,            "file_read_text" | "other"
content_utf8,    real content, or null for a pending declaration
content_sha256,  sha256(content_utf8) hex, or null with null content
now
```

Server rules (all fail closed):

* the device session must be current and inside the authenticated
  account/workspace scope (existing `_load_scoped_session`);
* `command_id` must resolve to exactly one canonical persisted command whose
  `binding_ref` is the authenticated device's — another device's command is 403;
* `revision_ref`, `request_id`, `evidence_ref` must equal the canonical record's
  values (server-owned; the caller can only confirm them);
* the canonical state must be `admitted` (upload before the ack) or
  `acknowledged`; when already acknowledged, the outcome must be
  `termination="exited"` and `exit_code=0` — a failed, cancelled or timed-out
  command can never carry text;
* content bounds: UTF-8, ≤ **768 bytes**, no control characters except
  `\n\r\t`, digest must match;
* idempotent retry: an identical resubmission is reused; a pending declaration
  may be upgraded once to content; a downgrade or a changed body is refused;
* retention: the table is pruned oldest-first at 512 rows.

Response: `{"ok": true, "file_result": {command_id, binding_ref, kind,
content_bytes, content_sha256, stored_at, raw_device_credential: false}}`, or
the usual `{"ok": false, "error": {code, message}}`.

Reachability: `DEVICE_HTTP_ROUTES` is the single canonical list; the public edge
worker (`local_agent_broker_edge_worker.py`) and the private bridge
(`local_agent_broker_private_http_bridge.py`) both derive their route sets from
it, so `/file-result` is reachable end to end by construction. A deployment
without the store composed answers `503 local_agent_file_result_not_configured`.

### 2.3 `read_verified_file_text` (broker → Claw, private Service Binding RPC)

Request: `{account_ref, workspace_ref, run_id, command_id}` (exactly what
`claw_local_task_result_composition.BrokerAuthorityLocalRunnerResultPort`
sends). Read-only: no transaction, no CAS, no state write.

Three answers, matching the #4687 / #4690 / #4693 consumer contract:

| answer | meaning |
|---|---|
| full receipt (14 keys) | verified text, correlated and hash-checked |
| `{ok:true, available:false, kind:"file_read_text"}` | text-file read declared, content not stored yet → Claw keeps the message slot open |
| `{ok:true, available:false, kind:"other"}` | no verified text for this command → Claw appends its normal terminal message |

Full receipt keys (exactly the consumer's accepted set):
`ok, available, kind, account_ref, workspace_ref, run_id, command_id,
tool_request_ref, request_id, revision_ref, evidence_ref, request_fingerprint,
content_utf8, content_sha256`.

Refusals (`ok:false` → the consumer fails closed and never consumes the message
slot): not scoped/found, canonical outcome not a successful execution, or a
stored correlation/integrity disagreement.

### 2.4 Ordering requirement for LOCAL2's Windows wiring

The Claw's read is gated on the canonical **successful acknowledgement**
(`acknowledged` + `exited` + `exit_code 0`). Therefore the resident must:

1. execute the command;
2. for a text-file read: `POST /file-result` (content, or a content-less
   declaration first if the body needs another step) — **before** the
   acknowledgement whenever possible;
3. `POST /acknowledge`;
4. for a non-file command: either post `kind:"other"` or post nothing at all
   (both yield the legacy terminal-only answer).

Failing the execution purges any stored receipt in the same transaction, so the
file text can never be served for a failed command even if the ordering above is
violated.

---

## 3. Verification performed

| check | result |
|---|---|
| `packages/padiem-control-plane/tests` (full package) | **1269 passed** (1252 before + 17 new) |
| `tests/test_local_agent_broker_verified_file_result_4139.py` | 17 passed — real SQLite DO storage, real private bridge → device service → handler → store → RPC |
| kagent local-agent suites incl. the new factory test | **68 passed** (incl. cross-contract read of the canonical route set) |
| `apps/padiem-chat/tests/test_4139_broker_txt_receipt_cross_contract.py` | 4 passed — the **real** broker store receipt drives the **real** #4687 consumer into the conversation append |
| mutation checks | success gate, failed-ack purge and read scope were each broken on purpose; the matching tests failed, then were restored and re-passed |
| pre-existing failures | `test_claw_local_task_result_projection.py` 3 failures = `padiem_ai_core.dispatch_preinstruction` missing in this local env, reproduced identically on the pristine baseline worktree |

## 4. Not verified (no success claim)

* No real Windows device produced any content in this change set; the receipt
  path was proven with the real broker and the real Claw consumer, not with a
  live machine.
* The public production mount `https://chat.padiem.net/api/claw/connector/gateway`
  is a declared contract value; the route is not attached in main and no live
  connection was attempted.
* No production deployment, no merge, no operational activation — those remain
  CENTRAL's gates.
