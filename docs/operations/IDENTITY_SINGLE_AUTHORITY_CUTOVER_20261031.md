# Identity single-authority cutover decision — 2026-10-31

Status: proposal, **not an authorization to operate or migrate**. Source-only
inventory at main dd348eeff (#6399); no production account, runtime binding,
data, secrets or COM2 service was inspected. Source presence is not proof of
deployment or use. Runtime caller discovery and reconciliation remain required.

## Invariant

One writable identity authority for every identity record at any moment:
Cloudflare Durable Object (DO) before cutover; stop and drain **all** writers
at the boundary; migrate and validate one consistent snapshot; enable COM2
only after all old writers are technically fenced. Never let old DO and SQLite
accept independent writes, including retries and long-running invocations.
Reads during freeze must either use the frozen old state or fail closed;
never authorize from diverging snapshots. Existing keys and identifiers are
preserved; no email-based merge or new identity generation.

## Source caller inventory

| Source caller / binding | Identity methods evidenced in source | Evidence and qualification |
|---|---|---|
| padiem-auth / IDENTITY_AUTHORITY | resolve_or_create_product_link | apps/padiem-auth/worker.mjs:208-215, wrangler.toml:8. Its separate Google-account registry DO and login/session state also exist; this PR does not migrate those independent auth states. |
| LoveTree auth caller / IDENTITY_AUTHORITY | resolve_or_create_product_link, establish_auth_session, revoke_auth_session | apps/lovetree-auth-caller/worker.mjs:127-159,199-229; wrangler.toml:12. Deployment and traffic unknown. |
| LoveTree authority caller / IDENTITY_AUTHORITY | resolve_auth_session, resolve_product_user_for_subject | apps/lovetree-authority-caller/worker.mjs:89-111; wrangler.toml:11. Read-only client. |
| Chat / IDENTITY_AUTHORITY_SERVICE | links, sessions, connector workspace/context, consent, owner scope, tenant membership and Google connect | apps/padiem-chat/wrangler.toml:95 and app/control_plane_identity_worker.py:239-826 provide typed clients; call sites, feature flags and actual traffic must be verified independently. |
| Connector enrollment through Chat | resolve_connector_enrollment_consent_for_device, bind_connector_enrollment_challenge, authorize_connector_enrollment_redeem; grant/revoke consent, owner scope, schema install through owner routes | apps/padiem-chat/app/canonical_connector_enrollment_async_host.py and connector_enrollment_owner_source_composition.py; the 3 gateway calls exist in COM2's 12, several owner operations do not. A PC is not shown to call the identity DO directly. |
| Engine / CONTROL_PLANE_IDENTITY | resolve_auth_session, resolve_connector_workspace | apps/padiem-ai-engine/wrangler.toml:43, app/auth_session_scope_authority.py:92, app/calendar_read_activation.py:83-91. |
| Voice STT / CONTROL_PLANE_IDENTITY | resolve_auth_session | apps/padiem-voice-stt/wrangler.toml:46-56, voice_stt_caller_auth.py:260-266. Other authorities in that service are separate. |
| Engine admission authority / CONTROL_PLANE_IDENTITY | binding declared; exact transitive method calls require tracing | packages/padiem-control-plane/wrangler.engine-admission-authority.jsonc:16 and engine_admission_authority_worker.py. |
| Other repos, direct callers, alternate deployments | unknown | Not covered by this repository source inventory. Reconcile Cloudflare binding/deployment inventory and traffic in a separately authorized read-only preflight before any cutover. |

The 12 COM2 ingress methods are explicitly defined in
packages/padiem-control-plane/com2_identity_rpc_ingress.py; the 11 DO methods
missing there are listed in docs/operations/COM2_HOST_ENTRYPOINT_PARITY_20261031.md
§2.3. A typed method existing in Chat does not prove a live caller. Compile a
method-by-caller matrix from actual call sites and approved deployment evidence
before selecting either option.

## Snapshot and verification prerequisite

Source inspection of identity_authority_worker.py, identity_authority_durable.py
and apps/padiem-identity found no complete DO SQL export/import RPC or approved
runbook; this is not proof that a Cloudflare platform recovery/export mechanism
does not exist. Verify the actual DO storage type, instance naming and supported
Cloudflare mechanisms before choosing an exporter. If no suitable complete
consistent export exists, a separately reviewed, authenticated, bounded,
versioned, resumable export/import mechanism is needed; never expose sensitive
rows in logs, artifacts, public URLs or PRs.

Inventory actual schema, all tables/indexes, schema versions and optional
connector consent/context and tenant data, including any DO key-value state.
At minimum inspect subject, product links, sessions, tenants, memberships and
identity_authority_schema in identity_authority_durable.py:203-244; these are
not a claim that the list is exhaustive. Stage import into an isolated file,
retain referential integrity and opaque IDs, preserve necessary key material
through approved secure provisioning, and verify schema, row counts, canonical
digests and sampled read outcomes without exposing personal information.
Rehearse freeze, interrupted import, fencing, recovery and fail-closed behavior
with synthetic data. Backups and key handling need a separate reviewed plan.

## CTO decision: choose one of two options

### A — keep Cloudflare DO authoritative

All existing callers remain directed to DO for reads and writes. COM2 Chat and
broker call it through an authenticated, reviewed private adapter; the COM2
SQLite authority remains disabled and is not a second writer. No identity
data migration is needed for this step. This defers identity relocation and
retains network dependence on Cloudflare.

### B — move the complete authority to COM2

Build and test snapshot/migration plus a privileged, strictly allowlisted COM2
RPC surface for **every method actually used**, including necessary members of
the 11 missing methods. Preserve per-caller authorization and schema-install
gates; no blanket public method exposure. Existing Cloudflare service-binding
callers must be migrated or routed through an authenticated proxy preserving
their RPC contracts; Cloudflare DO code must not retain a writable fallback.
A proxy, migration and exposure changes are future reviewed PRs, not this PR.

Cutover sequence: enumerate callers and old writers → stop new identity
mutations and drain in-flight work/retries → prove old DO fenced → consistent
export and secure backup → offline import to isolated COM2 SQLite → verify
schema/counts/digests and representative read/write behavior → atomically change
all callers to COM2 and confirm old writers remain fenced → resume. If any step
fails, keep writes stopped. Rollback before COM2 writes may return to fenced
original after verification; **after COM2 has accepted writes, simply switching
back loses data**. A tested reverse transfer/reconciliation and a fresh fence
are mandatory, otherwise remain stopped. Decide maximum freeze time and recovery
owner before scheduling.

In option B, the extra 11 are not left writing to Cloudflare. Expose only
confirmed needed operations on COM2, with tests and separate authorization;
unused methods remain closed, with documented owner and migration plan.
Option A keeps all identity operations on Cloudflare. The staging COM2 identity
DB must remain isolated and never be treated as a production authority.
