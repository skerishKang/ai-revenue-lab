# #3580 WEB-FIRST — Engine-independent B62 XLSX source authority

**Date:** 2026-10-11 KST. Source-code boundary only; not a deployed P01 owner-decision E2E.

## What was implemented

- `D1WebXlsxTrustedScopeResolver` in the **Engine** project reads only a privileged connection to the existing B62 metadata schema (migrations 008,009,014,015,029,030): owner-run, exact source selection, private original XLSX metadata and one-shot P01 request. There is **no request-selected database, SQL, path or hash**. This resolver never reads R2 objects or workbook bytes.
- Exact joined owner, workspace, running Hark run, active conversation, selection ref, D1 document ID and SHA-256, immutable object-key path, XLSX media type, byte size, pending dispatch marker, timestamps, unexpired original are independently revalidated. Foreign owner/workspace, expired/altered original, wrong run, deleted D1 metadata or processed/changed dispatch all return no authority. An unavailable D1 port raises and fails closed.
- `EngineToolBinding.invocation_preflight` is a **server-owned optional callable** executed by `ToolExecutionEngineService.execute_payload` **before Core user-confirmation pauses are issued**. False/mismatch → 403; unknown D1/service failure → 503. Existing Engine connector bindings without this optional hook keep existing behavior. A preflight cannot mint an approval.
- The `web_xlsx_p01_tool_binding` revalidates source metadata **twice** with distinct D1 states: `dispatching` before a real Core P01 pause, and `waiting_p01` when executing the original invocation after Engine-verified approval. This distinction prevents an uncommitted transport attempt from processing data and avoids blocking a legitimately committed owner pause. At both stages the resolver receives only the opaque selection reference and compares all six server-owned identities against the original ToolInvocation.
- `worker_identity.py` composes the Engine XLSX binding only with both `PADIEM_WEB_XLSX_P01_ENGINE_SCOPE_ENABLED=true` and a real private read-only B62 metadata D1 binding named `WEB_XLSX_PRIVATE_B62_D1`. The default code path preserves the prior resolver unchanged; absent/malformed binding fails closed. **Do NOT configure/enable this on a Production deployment without independently proving the binding is in fact the B62 D1 backing these tables and reviewing read-only authority.**

## Tested

Real SQLite D1 migrations and joins, trusted resolver rehydration, cross-owner/run/sha/expiry/format drift, deleted original, pre-dispatch versus committed pause state, post-approval revalidation, Engine preflight 403-before-pause, independent D1 outage 503, actual ToolExecutionEngineService pause on genuine source, and the existing Engine ToolRuntime / production-composition regressions.

## Remaining blockers

1. **Production Engine tool-execution continuation is not functional yet**: current `ToolExecutionEngineService` stores the original invocation in per-isolate `_pending`, and the default Engine tool service does not provide the durable, safely reconstructible invocation authority required for cross-isolate one-shot approval. Current P01 tool registration alone is insufficient for live web owner approval.
2. B62 owner approve/deny needs a **tool-specific** one-shot verified decision and Engine continuation interface, instead of pretending the existing general Claw orchestration decision route is compatible.
3. After proof of Engine-verified approval and correct owner/selection, an independently SHA-verified non-destructive XLSX working copy may be created. Editing, PDF and browser preview are later milestones.
4. B62/Engine production flags, D1 binding provisioning/migrations, Secrets, user customer files, Drive WRITE, and Windows Resident have not been changed or accessed.

**Gates:** `ENGINE_INDEPENDENT_D1_METADATA_AUTHORITY_CODE=YES` / `ENGINE_PRE_PAUSE_OWNER_SHA_GUARD=YES` / `P01_WEB_APPROVE_DENY_E2E=NO` / `PRODUCTION_LIVE=NO`. Keep #3580 OPEN.
