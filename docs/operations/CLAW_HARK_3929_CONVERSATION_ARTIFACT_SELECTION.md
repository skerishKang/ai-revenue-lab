# Hark #3929 — same-conversation artifact reference boundary

**Source checkpoint: 2026-10-10 KST** · component `kagent.conversation_artifact_followup` · Parent #3928

## User-intent → trusted source lookup

The Hark-style instructions “방금 만든 XLSX” / “이전 PDF” /
“수정본으로 다시 만들어줘” MUST NOT trigger a filename-wide Drive search or
a model-selected filesystem path. They require:

1. Current **server-authenticated** owner from the canonical B54/P01 session;
   canonical conversation id and workspace granted by the existing owner store.
2. A trusted server-side `OwnedConversationArtifactIndex` that rechecks
   **current** owner+conversation+workspace access before listing (e.g. revoked
   session/login, deleted/foreign chat, switched workspace must fail closed).
3. Existing **durable**, canonical `CanonicalArtifactRecord` objects from the
   selected conversation; exact owner, workspace, source run and digest checked
   even if a supposedly trusted adapter accidentally returns a foreign row.
   Bounded to 30 candidates, no local raw paths or provider references.
4. A typed `FollowupSelection` with output kind XLSX/PDF and selector:
   - `latest`: newest stored chronology ordinal only when unambiguous;
     duplicate filenames even across versions require confirmation.
   - `filename`: exact in-scope filename; duplicate matches require confirmation.
   - `exact`: UI-confirmed canonical artifact id **AND** matching SHA-256;
     fake/stale/renamed identity returns NOT_AVAILABLE, never silent fallback.
5. The result is only a `LineageArtifactRef` (existing #3599 identity +
   digest) with its original `source_run_ref`. This permits a *later* P01
   operation in a new run to request that source **after** its own independent
   READ grant and immutable SHA-256 revalidation. `#3933` continues to own
   reviewed edits and source→working-XLSX→PDF lineage; this module never
   generates a new copy or rewrites the previous artifact.

**Critical distinction:** no model, stored chat text or UI file name is an
authorization authority. If the current owner, conversation or index cannot be
revalidated, no document is selected. A candidate without a verifiable DURABLE
record is not a cross-browser durable source (and is excluded).

## Verified tests

`test_conversation_artifact_followup_3929.py` (standard KAgent `unittest`):

- two separate runs in one authorized conversation → newest XLSX ref,
  exact digest, original source run id (not the new run)
- kind separation (XLSX vs PDF), renamed file, duplicate-name confirmation,
  exact id+digest user confirmation, newest chronology ties
- no wrong owner / conversation / workspace / stale login / injected row /
  malformed index / local path / malformed token IDs / non-durable records
- no provider location tokens, bytes, new read grants, or fake cross-session
  memory-restoration claims in public output.

## Gate remaining — do not close #3929

This is **pure source**. `PRODUCTION_CONVERSATION_INDEX_COMPOSED=False` and
`PRODUCTION_DURABLE_FOLLOWUP_ENABLED=False`. Owner-granted durable
`#3580` artifact index / material-read adapter and exact conversation binding
need to be composed in the authenticated Claw/Broker host, then tested across
logout/login/restart, foreign project, ambiguous file and same-thread followup
using real Web UI and a new distinct run. The current generic run-history
projection may persist `conversation_id=None` and no artifact id; it is NOT
a file index and must not be treated as one.

Actual Office PDF fidelity and Google Drive/Sheets WRITE / Telegram SEND stay
subject to #3933 / #3580 / #2010 approvals. No Production mutation, live
provider/model call or data migration is authorized by this source change.

```
SAME_CONVERSATION_AUTHORIZED_REF=PASS_OFFLINE
CROSS_RUN_SOURCE_IDENTITY=PASS_OFFLINE
DUPLICATE_FILENAME_CONFIRMATION=PASS_OFFLINE
ORIGINAL_REFERENCE_UNCHANGED=YES_BY_CONTRACT
CROSS_OWNER_SCOPE=FAIL_CLOSED_OFFLINE
OWNER_DB_INDEX_PRODUCTION_WIRED=NO
SAME_THREAD_REAL_WEB_E2E=NOT_VERIFIED
DRIVE_WRITE_APPROVED=NO
PRODUCTION_MUTATION=0
```
