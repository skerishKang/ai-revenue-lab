# Hark #3929 — D1 owner conversation file index + real Claw read-only route

**2026-10-10 KST · source milestone, not Production activation**
Parent: #3928 · References: #3580, #3933, #4072, #3566

## Actual wiring (not an unconnected model helper)

- `apps/padiem-chat/migrations/026_claw_conversation_artifact_index.sql`:
  additive D1 index for immutable canonical XLSX/PDF artifact ID, SHA-256,
  filename/MIME/size, owner ID, conversation ID, workspace, originating
  completed run, server chronology and **private** provider durable location.
  Existing users, conversations, Claw history and project tables remain
  unchanged. **DO NOT apply to Production without a separate schema approval
  and preflight/readback gate.**
- `D1HistoryStore.register_owner_conversation_artifact` is the trusted
  *post-approved durable output* write port: only a real canonical
  `DURABLE` record of a run already marked `completed`, whose stored owner,
  conversation and workspace all agree, may be registered. The insert itself
  uses owner/run/conversation SQL joins. Artifact IDs cannot be reassigned;
  exact repeat is idempotent. It is NOT exposed as an HTTP write endpoint.
  **Actual Office/Drive producer has NOT been hooked into this port yet.**
- `D1HistoryStore.list_owner_conversation_artifacts` + D1 owner
  revalidation filter candidates by server owner, conversation and workspace;
  only completed runs with matching server linkage appear. 31-row bounded
  read detects overflow instead of quietly choosing an ambiguous older file.
- Registered `GET /api/claw/conversations/{conversation_id}/artifact-followup`
  in the existing `app_factory`. It uses the **current signed auth cookie**
  and CP-refreshed canonical tenant, never a caller-submitted owner/workspace.
  Optional query: `kind=xlsx|pdf`, `selector=latest|filename|exact`,
  `filename=`, `artifact_id=` and `integrity_ref=` as defined by the
  merged `kagent.conversation_artifact_followup` #4120 module.
  A successful response is a **metadata/reference-only selection**, not
  permission to read local/Drive bytes. Duplicate filename → confirmation
  (ID + hash), wrong user / workspace → deny, stale/missing schema → 503.
  No provider raw location, file contents, token or path is projected.
- `POST /api/claw/general` now optionally accepts existing canonical
  `conversation_id`, validates owner via the *existing*
  `_resolve_intake_session_reference` BEFORE quota/P01 dispatch,
  validates CP canonical session, then records a successful generic P01 run
  under that conversation and CP-verified workspace. If absent, old generic
  no-conversation behavior stays unchanged. Forged malformed/non-owner
  conversation IDs are denied before Engine/model invocation.

## Proof (synthetic, provider-free)

`apps/padiem-chat/tests/test_3929_claw_conversation_artifact_d1.py`:
- SQLite executes actual 001/009/014/015/026 migration SQL through a
  prepared-statement async D1 protocol shim.
- Real owner registration and read after write; exact digest selection;
  duplicate-name confirmation; cross-owner, foreign conversation, foreign
  workspace and revoked login denial; incomplete run not registered;
  already-claimed artifact ID cannot move; no Production migration: 503,
  schema stays unchanged.
- **Real TestClient cookie-protected Starlette route** with the actual D1
  adapter confirms 401 without login, 200 for owner, 404 for foreign
  conversation; private provider location never leaves the GET response.
- Existing #4072 generic Claw fake-Engine test confirms optional owned
  conversation+CP tenant is saved and bogus request-supplied workspace/owner
  is ignored; foreign/malformed conversation is rejected before dispatch.
  No real model, Office, Dropbox, Drive or Telegram calls are made.

## Outstanding gates — #3929 must stay OPEN

1. **Production migration 026 is NOT applied.** Requires owner scope approval,
   schema preflight/readback proof and operator-authorized Cloudflare D1 action.
2. The real P01/Office/Drive approved durable file producer still must call
   `register_owner_conversation_artifact` exactly after successful immutable
   artifact generation. Current generic P01 text run has NO file material.
3. Actual Claw browser composer must wire a real selected canonical conversation
   ID and expose safe confirmation choices, then after a fresh independently
   authorized P01 READ, apply #3933 workbook edits and PDF export.
4. Cross-device reopen, authorization renewal, original SHA read proof and
   8-scene #3936 Hark browser E2E are NOT proven. No silent auto-remember claim.
5. Separate Drive WRITE/Telegram SEND consent remains required (#3580/#2010).
   No unreviewed operator production WRITE, Secrets or provider calls here.

```text
AUTHENTICATED_D1_INDEX_SOURCE=CONNECTED
OWNER_CONVERSATION_CP_SCOPE=SERVER_VERIFIED
D1_SQLITE_MIGRATION_AND_READ_WRITE=PASS_SYNTHETIC
STARLETTE_REAL_COOKIE_GET=PASS_LOCAL
GENERAL_POST_OPTIONAL_CONVERSATION_LINK=PASS_PROVIDER_FAKE
PRODUCTION_D1_026=NOT_APPLIED
PRODUCTION_FILE_PRODUCER=NOT_COMPOSED
PRODUCTION_ARTIFACT_READ_GRANT=NOT_ISSUED
PRODUCTION_WEB_UI_E2E=NOT_VERIFIED
PRODUCTION_MUTATION=0
```
