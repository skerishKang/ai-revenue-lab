# #4434 — local XLSX workcopy revision and staging (2026-10-25, COM2 LOCAL1)

Scope record for the PC side of the web -> PC -> web Excel round trip. Public
technical evidence only: no credentials, no device identifiers, no customer data.

## What was already there

`kagent.local_xlsx_revision_pdf` already owned the revision *contract* — an
approved source handoff, literal `ReviewedCellRevision` edits, an editor port, an
independent verifier port, and canonical artifact/lineage registration. The
selected-root runtime already performed authorized real reads and writes, the
chunk publisher already staged bounded 48 KiB parts over the pinned HTTPS/443
broker transport, and the Chat side already reassembled and re-verified them.
The two ports had no production implementation, and nothing ordered the steps
so that the original file could not be the write target.

## What this change adds

- `kagent/local_xlsx_python_copy_editor.py`
  - `PythonXlsxValueCopyEditor` — the production editor for the ordinary Python
    path. It rewrites only the worksheet part that holds a target cell and copies
    every other package member byte-for-byte, so styles, theme, merged ranges,
    print settings and every untouched cell are preserved by construction rather
    than by promise. Text replacements are written as `inlineStr` so
    `xl/sharedStrings.xml` is never mutated.
  - `IndependentZipXlsxRevisionVerifier` — proves from the two byte blobs alone
    that the part set is unchanged, exactly the expected parts differ, every
    non-target cell keeps its value, and each target cell holds the reviewed
    replacement.
  - `OfficeFidelityRequired` — a workbook that carries any formula, or a
    calculation chain, is refused before a byte is written and routed to the
    existing Office/Local Runner path (`windows_excel_pdf_renderer`,
    `supervised_windows_excel_pdf`), because replacing an input makes the cached
    results of dependent formulas stale. `classify_xlsx` stays the untrusted-input
    gate; `REJECT` is refused, and a DTD or entity declaration in any part is
    refused before parsing.
- `kagent/local_xlsx_workcopy_roundtrip.py`
  - `revise_and_stage_approved_xlsx_workcopy` — one ordered composition over the
    existing authorities: approved READ (canonical P01) -> source handoff ->
    editor -> independent verifier -> canonical `working.xlsx` record -> approved
    WRITE to a *derived* path -> staging through `LocalOfficeChunkPublisher`.
  - `revised_path_for` derives the only legal result name (`<source>_revised.xlsx`
    beside the source). The caller cannot supply a target, the original can never
    be the write target, and an existing result file is refused instead of
    silently overwritten.
  - The WRITE is approved against the exact result bytes, so the host validates
    the built request against the verified bytes, the derived path, and the
    source's device, root and run before performing it.

No second parser, no second store, no new ceiling, no new approval step: the
result's integrity comes from the runtime's atomic write (temp file, `fsync`,
`os.replace`) rather than from an extra customer-facing approval.

## Verified on COM2 (real files, real disk, real P01 evidence)

`python scripts/kagent_local_test.py -- -p "test_4434_local_xlsx_workcopy_roundtrip.py"`
→ 13 tests OK, `IMPORT_ORIGIN_CHECK=PASS`.

- Revision on disk: `quote\book.xlsx` -> `quote\book_revised.xlsx`; original SHA-256
  unchanged; result SHA-256 equals the canonical record; merged range and untouched
  cells preserved; Korean text kept.
- Only `xl/worksheets/sheet1.xml` differs between original and result;
  `xl/styles.xml` is byte-identical.
- Formula workbook → `OfficeFidelityRequired`, no result file, nothing staged.
- Stale `previous_value`, unapproved WRITE, non-derived target, pre-existing result
  file, cross-run/cross-device request, and a non-OOXML source are each refused with
  no write and no staging call.
- Staged parts reassemble to the verified digest; each `part_sha256` matches; the
  wire carries run/command ids only — no path, no destination, no Drive claim. A
  broker-refused part yields no receipt, and an explicit retry of the same bytes
  produces identical part digests.
- The production editor and verifier satisfy the existing
  `revise_and_render_local_xlsx_pdf` ports and its lineage registration.

## Resident integration (2026-10-26 follow-up)

- `kagent/local_resident_xlsx_revision_delivery.py`
  - `TrustedP01XlsxRevisionPlan` — the P01 material for one revision of one
    acknowledged command: approved READ, literal reviewed edits, and an approved
    WRITE whose fingerprint binds the *expected result bytes*. It creates no
    approval; the pause, decision and local permission evidence are the existing
    canonical ones.
  - `TrustedP01XlsxRevisionBridge` — hands out that evidence once per file
    request and consumes one `(binding, command)` pair once, so a reconnect or a
    duplicate delivery cannot revise the workbook a second time.
  - `ResidentXlsxRevisionStager` / `compose_resident_xlsx_revision_stager` —
    post-ACK execution through the existing P01 file authority plus the canonical
    `LocalOfficeChunkPublisher`. It refuses an authorization port that is not
    `P01LocalPermissionWindowsFileAuthorizationPort`, so the deterministic test
    grant cannot enter this path.
- `local_agent_resident_process.build_resident_host` gained
  `xlsx_revision_plan_source`; the environment may only name an importable
  trusted factory (`PADIEM_AGENT_XLSX_REVISION_PLAN_SOURCE=module:attribute`),
  never a path or an approval, and `main()` resolves it with the same fail-closed
  convention as the text and Office lanes.
- `LocalAgentResidentRuntimeHost` invokes the lane after the acknowledgement,
  with the same discipline as its siblings: an acknowledged command keeps its
  truth, a staging refusal records `REVISION_REFUSED`, and nothing re-executes.
- Capability boundary confirmed by `test_4434_xlsx_capability_scope.py`: the
  Python path handles later-sheet edits, Korean text with leading and trailing
  spaces, negative and large integers, merges and styles (only the target
  worksheet part changes); anything with a formula, a calculation chain (matched
  case-insensitively, as Excel writes `xl/calcChain.xml`), or an
  `xlsx_fidelity_route.BLOCKED_PARTS` member (VBA, external links, pivots,
  charts, comments, custom XML) is routed to the Office path with no write. The
  literal-only `ReviewedCellRevision` contract still refuses floats, booleans and
  formula-like strings.
- Broker coupling: `apps/padiem-chat/tests/test_4434_office_chunk_broker_web_coupling.py`
  runs the real publisher over the real editor output and serves those recorded
  payloads to the real `BrokerOfficeBinaryReader` (the Durable Object rows are the
  only stand-in, and the store has its own SQLite contract test). It pins the
  shared wire schema against `local_agent_broker_office_chunks._WIRE` after the
  device route strips `binding_ref`/`credential_b64`, checks per-part and
  whole-file digests, two-command isolation, foreign owner/run/command/kind
  refusal, tamper refusal, and recovery after a missing part.

## Connector configuration path (2026-10-26, #5835 작업 B)

`apps/claw-connect/claw_connect/resident_launch.py` can now carry the revision
lane the way it already carries the TXT lane:

- `RESIDENT_ENV_XLSX_REVISION_PLAN_SOURCE = "PADIEM_AGENT_XLSX_REVISION_PLAN_SOURCE"`
  is the exact key `local_agent_resident_process` reads, pinned as text and
  cross-checked against that file's own source in
  `test_4434_resident_xlsx_revision_launch.py` — a rename on either side fails a
  test instead of silently leaving the lane off.
- A configured value is forwarded; an absent value emits no key; a malformed one
  refuses the launch with `xlsx_revision_plan_source_invalid` rather than
  spawning a child that has to fail closed by itself. A value the plan never
  authorized is dropped from the emitted environment.
- The shared `module:attribute` shape check now requires every dotted segment to
  be a real identifier. `kagent.:factory`, `.pkg:factory` and `pkg..mod:factory`
  could never import, and the old pattern accepted them for all three keys
  (request port, TXT, revision). Nothing that actually imports got stricter.
- `installed_runtime.py` pins **no** revision source and clears an ambient one,
  so a customer machine cannot arm the lane by exporting a name: no fake grant
  and no test-only plan source reaches an installed Resident. `XLSX_REVISION_-
  PLAN_SOURCE = None` is where CENTRAL records a reviewed factory when one
  exists; until then `RESIDENT_XLSX_REVISION_LANE_PRODUCTION_CONFIGURED` stays
  `False`.
- What a real factory would have to be: the existing command material carries one
  closed-validated `p01_approval_payload` shaped as a TXT *read* receipt
  (`local_agent_command_material.validate_txt_approval_receipt`). A production
  revision source needs the matching WRITE approval to ride an acknowledged
  command, which means a Chat-side receipt format plus its validator. Inventing a
  PC-side-only source would mean trusting approval material no server minted, so
  it is deliberately not done here.
- Composition proof on the Resident side
  (`test_4434_resident_xlsx_revision_lane.py`): the composed stager holds a real
  `LocalOfficeChunkPublisher`, a `WindowsSelectedRootFileRuntime` whose
  authorization port type is exactly
  `P01LocalPermissionWindowsFileAuthorizationPort`, and the roundtrip module's
  omitted editor/verifier resolve to `PythonXlsxValueCopyEditor` and
  `IndependentZipXlsxRevisionVerifier`. The original path is never the write
  target; the result digest is the one that was verified before the write.

## Web entry path: why the chooser route stays 503 (2026-10-26, 작업 A)

Composition state, read at the two places that decide it:

- `apps/padiem-chat/app/app_factory.py:1362` assigns
  `app.state.claw_office_chooser_source = claw_office_chooser_source`, and the
  parameter default at `app_factory.py:462` is `None` with the comment that the
  chooser "is fail-closed until the real trusted Engine/Resident operator
  supplies an owner-bound, pre-approved candidate/approval source".
- The production composition root is `apps/padiem-chat/worker.py:1141`
  (`create_app(...)`), which passes the named ports for the surfaces that are
  live — `oracle_mesh_return_source`, `b66_pc_access_policy`,
  `claw_drive_artifact_uploader`, and the rest — and does **not** pass
  `claw_office_chooser_source`. Sibling trusted sources are built worker-side
  from a Cloudflare Service Binding and assigned onto `app.state` after
  `create_app`; there is no `module:attribute` environment pattern in the Chat
  app. So the route answers `503 office_chooser_unconfigured` in production
  because nothing constructs a source, not because a flag is off.

No production implementation of the protocol exists: the only object with
`configured` + `candidates()` + `select()` is the test double in
`tests/test_3580_claw_office_chooser_routes.py`. PR #5817 (parser authority,
33 files) contains no Office or chooser code, so the conflict resolved on that
PR was never an Office conflict, and it cannot supply the missing source.

Why the missing half is not a worker-side wire:

- `select()` is refused unless the source returns a *genuinely started* Engine
  pause (`status == "awaiting_approval"`, `engine_run_id`) **and** the route
  independently re-reads the durable `claw_approval_handoff` row and requires
  `p01_run_id`, `continuation_ref`, `pause_id` and `trusted_request` to match
  (`claw_office_chooser_routes.py:143-178`). A Chat-local source that read the
  same D1 row it is checked against would be self-attesting, which is exactly
  what the route was written to prevent.
- The only writer of that row is `_record_claw_approval_handoff`
  (`app/claw_routes.py:992`, called at `:766` and `:1238`) — the ordinary Claw
  run path, reached when an Engine run pauses. Nothing today pauses an Engine
  run from an office-candidate selection.
- The one working "web request → P01 → PC command" precedent is TXT, and it is
  **read-only by construction**: `apps/padiem-chat/app/connector_txt_approval_material.py:249-288`
  builds the receipt from the authenticated owner's confirmed request
  (`POST /api/claw/connector/text-reads/request`, body exactly
  `{device_id, root_ref, path_relative, run_id, confirmed: true}`), and the
  `approval_pause` / `approval_decision` blocks are written there server-side —
  no Engine call and no on-PC prompt — over a
  `tool_invocation_digest` of the canonical Windows READ. The Chat side puts it
  on the command as `p01_approval_payload` (`:302`; Android twin
  `connector_android_saf_approval_material.py`), the control plane admits only
  those two formats under `claw-local-command-material.v2`
  (`packages/padiem-control-plane/local_agent_broker_material_store.py:252-295`),
  and the PC accepts the format only for `operation == "read"` on a `.txt` path
  under the selected root with `content_bytes == 0` and `content_sha256 is None`
  (`kagent/local_agent_command_material.py:137`, `:198`, `:203-206`).
  `grep` across `apps/padiem-chat` and `apps/korean-ai-platform` finds **no**
  write or revision approval format anywhere.

So the TXT lane reaches a customer PC on consent the *web* transcribed, and the
reason that is defensible there is that the transcript can only ever describe a
read. Carrying the same shape over to a WRITE would let a server transcript stand
in for on-PC consent to modifying a file. The #5835 lane therefore takes the
opposite position: `ResidentXlsxRevisionStager` accepts only
`P01LocalPermissionWindowsFileAuthorizationPort`, the deployment names a trusted
factory, and no server-supplied transcript is honored. Choosing between "the PC
prompts for the write" and "the web approval is trusted for the write" is an
owner/CENTRAL security decision, not something to settle by wiring a
placeholder source into a customer-facing route.

## Device connection facts on COM2 (2026-10-26, 작업 C)

- `padiem-oracle-mesh-executor.service` and `padiem-meshcentral.service` are
  `active`/`running`; the executor's main process started Sun 2026-10-25
  14:50:13 KST with `Result=success`.
- The same lane completed real dispatches: `phase=submit_ok ... status=200` and
  `oracle-mesh-executor result ok=True retryable=False quarantined=False` at
  19:34:57 and 19:39:27 on 2026-10-25.
- Exactly one failure appears in the journal: `23:16:57 oracle-mesh-executor
  channel refusal: chat channel transport refused`, emitted at
  `local_agent_oracle_mesh_executor.py:1432` from the transport branch at
  `:259-260` (a non-HTTP failure — DNS/TLS/connect), during repeated WSL
  `systemd-resolved: Clock change detected. Flushing caches.` entries. Nothing
  like it recurred on 2026-10-26 (`--since 2026-10-26` shows no entries, no
  refusals), so this was transient, not a persistent outage.
- The poll channel is deployed: an unauthenticated `POST
  https://chat.padiem.net/api/claw/connector/mesh-reads/poll` answers
  `403 {"ok":false,"error":{"code":"oracle_mesh_channel_rejected"}` — the
  bounded refusal for a request with no device channel token. No grant was
  created and no authentication was bypassed to obtain this.
- The `ACTION_REQUIRED` / `usable=false` device row is **the designed shape** for
  a PC whose authority comes from a Mesh grant, not from a Broker heartbeat:
  `apps/padiem-chat/app/claw_device_directory_routes.py:333-351` appends
  `{"state": "ACTION_REQUIRED", "usable": False, "executable": True,
  "selectable": True}` under the comment "A Mesh grant proves execution
  authority, not a Broker heartbeat." Only canonical `online`, which the server
  derives from binding + broker session + heartbeat evidence, projects as
  `usable` (`app/claw_local_projection.py:107-116`, `:202-207`). So the
  selection-vs-execution difference is intended, the PC remains selectable and
  executable, and what is missing is Broker-session liveness for that device —
  an operational item, not a code change.
- `wrangler whoami` on COM2 reports "You are not authenticated", so Worker logs,
  config reads, secret changes and any deployment are unavailable from this
  machine; the B54 workflow's own `wrangler whoami || exit 1` preflight shows
  what CENTRAL uses.

## Chunk transfer gate: support and the approved way to turn it on (작업 D)

- Code support is present and asserted by the protected workflow: the device
  route allowlist contains exactly one Office staging route
  (`/office-part`), authentication happens before any byte is written, and the
  state worker composes the store
  (`.github/workflows/b54-local-agent-public-ingress-activation.yml:129-160`).
- The gate is a plain text var read as
  `str(getattr(env, "LOCAL_AGENT_OFFICE_CHUNK_TRANSFER_ENABLED", "")).lower() !=
  "true"` → `None` store
  (`packages/padiem-control-plane/local_agent_broker_office_chunks.py:327`).
- It is unset in the deployed configuration: the var appears in no
  `wrangler.*.jsonc` in this repository (`grep -l` over all worker configs
  returns nothing), while `wrangler.local-agent-broker.jsonc` does carry other
  `LOCAL_AGENT_BROKER_*` vars in its `vars` block. That is the proof the flag is
  off in production, and it is why the authenticated route answers
  `503 office_transfer_not_configured`.
- Enabling it is a committed config change to that `vars` block, shipped through
  the existing B54 activation workflow — preflight asserts, `environment:
  production` approval, served-version resolution through
  `cloudflare_served_version_cli.py resolve-active`, and its rollback job. That
  workflow deploys; it neither rewrites existing Secrets nor removes Worker
  bindings, which is what "preserve the Cloudflare Secrets and existing
  bindings" requires in practice. Doing it from COM2 is impossible (no
  Cloudflare authentication), and doing it by hand outside that workflow would
  bypass the reviewed gate.

## The write-consent precedent is web-side, and it is not the TXT transcript (2026-10-26)

Refinement to the section above, found while checking whether a write approval
shape exists at all. It does — just not as a PC command-material format:

- `docs/operations/CLAW_HARK_3933_EXPLICIT_WEB_WRITE_ENGINE_P01_20261011.md`
  records an implemented, default-OFF milestone: `POST /quote-edit/request`
  reserves a WRITE pause in migration 034
  `claw_web_xlsx_quote_write_pauses`, calls the private Engine ToolRuntime, and
  returns `waiting_p01`; `POST /quote-edit/decision` accepts only
  `{"decision":"approve"}` or `{"decision":"deny"}`, reserves a separately
  scoped owner WRITE consent row (033) *before* dispatch, submits the first-party
  Core decision with server-held pause/continuation, and consumes once. A denied
  or unverifiable result never writes a workbook, and the browser gets a second,
  distinct "save the revised XLSX" click.
- The flag chain that turns it on is explicit and stacked
  (`apps/padiem-chat/worker.py:1410-1444`):
  `PADIEM_WEB_XLSX_P01_TOOL_DISPATCH_ENABLED` →
  `PADIEM_WEB_XLSX_P01_OWNER_DECISION_ENABLED=true` →
  `PADIEM_WEB_XLSX_WORKCOPY_AFTER_P01_ENABLED=true` (plus `runtime_mode == "b14"`
  and a workspace document store) → `PADIEM_WEB_XLSX_QUOTE_WRITE_ENABLED`, each
  with its own operator-managed caller. None of these appears in
  `apps/padiem-chat/wrangler.toml`, so the whole web write lane is off in the
  committed production configuration.

So the shape the PC revision lane wants — a real owner decision on a XLSX write,
recorded durably, verified before any byte is written — already exists on the
web side. What it is bound to is a **private R2 workcopy**, not a file on a
customer PC, and it reaches the Engine rather than a device command. The
integration question is therefore narrower than "invent write consent": make the
PC workcopy the object of that same pause/decision flow, so the #5835 lane's
trusted plan source can be satisfied by a decision the owner actually gave,
instead of the TXT lane's server-transcribed read.

## The revision approval envelope the PC admits (2026-10-26, 작업 A + #5573 integration contract)

`kagent/local_agent_command_material.py` now admits a second closed format on the
existing `p01_approval_payload` slot, beside the two read-only TXT ones:

```
claw-xlsx-revision-approval.v1
  format / evidence_ref / command_id / request_id / local_policy_ref / expires_at
  source_approval  = {approval_pause, approval_decision, exact_tool_arguments}   # READ,  content_bytes 0
  result_approval  = {approval_pause, approval_decision, exact_tool_arguments}   # WRITE, content_sha256 names the result
  revision         = {sheet_name, edits[1..64], result_path_relative}
```

Rules the validator enforces, and why each one is load-bearing:

- The write half names its own tool (`local.filesystem.write`), requirement and
  scope (`filesystem.write`), authority
  (`claw_connector_xlsx_revision_request_v1`) and policy
  (`padiem_xlsx_selected_root_revision_policy_v1`). The read constants are not
  reused: a read approval cannot describe a write.
- **Two distinct decisions are required.** `P01LocalPermissionWindowsFileAuthorizationPort.authorize`
  consumes one `decision_id` per file access
  (`windows_local_filesystem.py:493-497`), so one pause covering both halves is
  refused at the shape layer rather than half-executing later.
- The approved result is bound by digest *before* it exists:
  `result_approval.exact_tool_arguments.content_sha256` must equal what the
  editor produces from the declared edits, and `revision.result_path_relative`
  must equal the approved WRITE path. A mismatch is caught by the existing
  stager guard (`"revision result bytes differ from the approved WRITE"`), so the
  PC never writes bytes the owner did not approve.
- Edits stay literal: `^[A-Z]{1,3}[1-9][0-9]{0,6}$` cells, no duplicates, values
  limited to bounded strings or integers, a leading `=` refused, floats and
  booleans refused. Paths stay relative to the selected root — no drive letter,
  no leading backslash, no `..`, `.xlsx` only.
- The envelope carries no credential, no absolute path, no capability grant. It
  is *attested input* for the existing authority, exactly like the TXT receipt.
- Unrecognized approval material is now refused outright instead of being
  silently ignored (`"unsupported command approval receipt format"`), matching
  what the control-plane validator already does, so a command cannot execute with
  a receipt no validator admits.

What this contract still needs before the lane can run in production, stated as
the exact remaining seam rather than a general TODO:

1. **Producer.** Nothing mints this format yet. The mint belongs on the Chat side
   beside `connector_txt_approval_material.py`, and the control plane must admit
   the new format in `local_agent_broker_material_store.py:252-295` (currently
   two formats only). Consent must come from the *existing* owner WRITE approval
   flow (`/quote-edit/request` → `/quote-edit/decision`, migration 034
   `claw_web_xlsx_quote_write_pauses`), not from a server-invented pause: the
   TXT lane's transcript model is defensible for reads only because it cannot
   describe a write.
2. **Consumer.** `verified_p01_xlsx_revision_plan_source.py` — build both
   `LocalFileRequest`s from the envelope, recompute
   `file_request_fingerprint` and `tool_invocation_digest`, bind
   `command_id`/`request_id`/`run_id`/`device_id`/`root_ref` to the admitted
   command, check expiry against the lane clock, and hand
   `TrustedP01XlsxRevisionPlan` to the bridge that already exists. Its
   `module:attribute` factory is then the value of
   `PADIEM_AGENT_XLSX_REVISION_PLAN_SOURCE`, and `installed_runtime.py` gains a
   reviewed pin.
3. **Delivery of the payload.** The plan source signature receives
   `(binding, command, receipt)`; the approval payload lives in resolved command
   material (`local_agent_control_plane_channel.py:110` →
   `ResolvedLocalCommandMaterial.approval_receipt`). The lane needs that resolved
   material handed to it — either the host passes it at execution time, or the
   source re-reads it through the existing authenticated `/material` device
   route (`ControlPlaneHttpsOperation.MATERIAL`, already in the closed allowlist).
   Both keep one authority; neither adds a route.

Tests: `tests/test_4434_xlsx_revision_receipt_contract.py` (16) pins admitted and
refused shapes with real workbook bytes and the real fingerprint function,
including the shared-decision refusal, the under-declared edit refusal
(`IndependentZipXlsxRevisionVerifier` returns `False`), and the fact that the
shape layer admits bounded refs while correlation stays the plan source's job.
Existing TXT material tests are unchanged (69 passed across the five suites).

## Still not enabled, and who owns it

| Item | State | Owner |
|---|---|---|
| Resident revision lane composition | implemented and fail-closed, and the Connector can now carry the key (`resident_launch.py`, installed release clears it); `RESIDENT_XLSX_REVISION_LANE_PRODUCTION_CONFIGURED` stays `False` because no reviewed `module:factory` exists to pin | CENTRAL with the #5573 executor/connector lane |
| Broker staging gate `LOCAL_AGENT_OFFICE_CHUNK_TRANSFER_ENABLED` | unset in every environment; route answers `503 office_transfer_not_configured` | operator configuration, CENTRAL |
| Web `claw_office_chooser_source` composition | no production implementation exists and `worker.py:1141` never passes it, so `/api/claw/office/candidates` answers 503 `office_chooser_unconfigured`; the blocker is a write-capable approval format plus the "who consents to the write" decision, not a missing wire | owner/CENTRAL decision, then Engine + Chat (#5817 holds no Office code) |
| Device row `ACTION_REQUIRED` / executor poll refusal | observed live on COM2 on 2026-10-25 | CENTRAL operational recovery (#5573) |
| Full web -> PC -> web E2E with an approved write | not run; blocked by the rows above. The web routes were probed locally through the ASGI app and answer their bounded refusals without an authenticated device/owner session (`401 unauthorized`, `local_runner_result_forbidden`) | after the above clear, with the Owner performing the approval |
