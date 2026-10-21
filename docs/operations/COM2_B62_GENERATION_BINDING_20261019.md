# COM2 B62 generation binding — 2026-10-19

LOCAL B closeout for the B62 runtime side of the COM2 data connection. It replaces
the pinned D1 seed and R2 generation with the published pointer, reuses the
existing store composition, and records the remaining authentication gap. The live
`127.0.0.1:18764` listener was not restarted or reconfigured.

## 1. Pointer is the only generation source

`D:\PADIEM-Servers\b62-chat-api\runtime\generation-store\current_generation.json`
(published by LOCAL A) now selects the active artifacts:

```text
d1_generation=20261019T084722757869Z
d1_seed=chat-20261019T084722757869Z.sqlite3
d1_bytes=2052096
d1_sha256=5a3fa7395d8b9de419e52e3562274c8b45905bfcd78925b48b8e38b1e08b28b7
d1_tables=57
r2_generation=20261019T005000763982Z
production_bound=false
```

The runtime no longer hardcodes either value. `b62_generation_binding.py` reads
the pointer, checks the seed size, SHA-256 and R2 staging pointer, and raises a
stable code instead of starting when anything disagrees:

```text
b62_generation_pointer_missing|invalid
b62_generation_production_bound
b62_generation_seed_missing|integrity_failed
r2_generation_pointer_missing|invalid|mismatch
r2_generation_production_bound
r2_staging_generation_unavailable
r2_generation_mode_required
```

`scripts/ops/com2_b62_generation.py verify` is the independent operator check. It
also counts the seed's tables and confirms the R2 manifest exists:

```text
B62_GENERATION_OK d1_generation=20261019T084722757869Z
d1_seed=chat-20261019T084722757869Z.sqlite3 d1_bytes=2052096
d1_sha256=5a3fa739...b28b7 d1_tables=57 r2_generation=20261019T005000763982Z
```

## 2. Reused composition, no new data path

`local_b62.py` now exposes `build_app(generation_bind=...)`. With the flag off it
composes exactly the previous app. With the flag on it passes the existing
`D1HistoryStore`, `D1ProjectFileStore`, `D1SavedOutputStore`, `D1IdentityShadowStore`,
`LocalSQLiteD1` and R2 overlay into the same `create_app`. `local_b62_generation.py`
is now a thin entry for that composition.

No data copy, backup, Secret structure, Worker, D1 or R2 writer was added. The D1
seed is the COM2 writable Chat database; imported R2 objects remain immutable
behind the existing write overlay.

`start-b62-release.ps1 -GenerationBind` selects the bound path and runs through the
existing `store.py run`, so the DPAPI environment (identity bridge and auth
values) is injected without new credential plumbing. The default invocation is
unchanged.

## 3. Candidate evidence (not the current service)

The generation candidate was served on loopback `127.0.0.1:18765` and then
stopped. Exact responses:

```text
GET /health            200 history_store_bound=true project_file_store_bound=true
                       saved_output_store_bound=true canonical_identity_bound=true
                       identity_shadow_bound=true quota_store_bound=true
                       auth_configured=true
GET /api/auth/status   200 ready=true history_ready=true
                       methods={"google":false,"password":true}
```

The composed stores were also read through the same binding in-process:

```text
HISTORY_READ_OK owner_rows=30          (bounded list; 87 conversation rows exist)
PROJECT_FILES_READ_OK owner_rows=0     (table currently empty; read succeeded)
SAVED_OUTPUTS_READ_OK owner_rows=0     (table currently empty; read succeeded)
R2_GENERATION 20261019T005000763982Z
IDENTITY_BOUND True
```

## 4. Current listener state (unchanged)

The actual service on `127.0.0.1:18764` still runs the previous entry and was
reported separately:

```text
GET /health            200 auth_configured=false history_store_bound=false
                       project_file_store_bound=false saved_output_store_bound=false
                       canonical_identity_bound=false identity_shadow_bound=false
GET /api/auth/status   200 ready=false history_ready=false
```

Candidate results are not evidence for this listener. Switching the live entry to
the bound path is a separate restart decision.

## 5. Authentication status

The DPAPI store already holds a COM2-local session secret, the public Google
client id and `PADIEM_CHAT_AUTH_MODE=password`; that is why the candidate reports
`password` available. Two values are still absent and cannot be read back from
Cloudflare:

```text
PADIEM_CHAT_GOOGLE_CLIENT_SECRET
PADIEM_GITHUB_APP_CLIENT_SECRET
```

`PADIEM_CHAT_AUTH_MODE=hybrid` cannot start without the Google client secret, so
Google login, hybrid login and GitHub connector are `BLOCKED_BY_SECRET`. No
credential login was attempted, and no synthetic secret value was injected. The
local session mechanism itself was exercised separately in §8. Register the
values through the existing hidden-input store:

```text
py -3 D:\PADIEM-Servers\infrastructure\secret-store\store.py put PADIEM_CHAT_GOOGLE_CLIENT_SECRET
py -3 D:\PADIEM-Servers\infrastructure\secret-store\store.py put PADIEM_GITHUB_APP_CLIENT_SECRET
```

After registration, switch the stored mode with the same hidden-input command so
`store.py run` injects it (the DPAPI value overrides the parent environment):

```text
printf '%s' hybrid | py -3 D:\PADIEM-Servers\infrastructure\secret-store\store.py put-stdin PADIEM_CHAT_AUTH_MODE
```

The non-secret values in `com2-env\chat-auth.env` remain the reference for the
public base URL, client id and session age. Then start the same entry, and verify
one real browser login, the session cookie, and one owner-scoped member read.

## 6. Rollback

Start the release without `-GenerationBind` (or unset `PADIEM_B62_GENERATION_BIND`)
to return to the previous data composition. The pointer and the imported
generations are read-only; reverting the runtime touches no artifact.

## 7. Unchanged scope

- No restart, reconfigure or traffic change for the live `18764` service.
- No Cloudflare Worker, DNS, Tunnel, secret, D1 or R2 change.
- No data copy, migration, restore or deletion.
- No secret value was read, printed, committed or uploaded.

## 8. Transition preflight — 2026-10-19T10:41Z

After PR #5124 and #5126 merged, the actual release path was exercised on a spare
loopback port while the live service stayed up:

```text
D:\PADIEM-Servers\b62-chat-api\start-b62-release.ps1 -Port 18765 -GenerationBind
  -> local_b62:app via store.py run, PADIEM_B62_GENERATION_BIND=1
```

The bound listener reported:

```text
/health            200 auth_configured=true history_store_bound=true
                   project_file_store_bound=true saved_output_store_bound=true
                   canonical_identity_bound=true identity_shadow_bound=true
/api/auth/status   200 ready=true history_ready=true
                   methods={"google":false,"password":true}
```

Session behavior was checked without an external identity provider:

```text
foreign/expired cookie      -> authenticated=false session_state=expired
locally signed session      -> authenticated=true  session_state=signed_in
                               member profile returned (email/name/picture fields;
                               values not printed)
```

The locally signed session is a technical check of session decode plus the D1
member lookup using the COM2-local session secret. It is not a Google/password
login and is not evidence of an OAuth flow.

The live listener was re-read afterwards and was unchanged:

```text
18764 /health 200 all data/identity bounds=false auth_configured=false
18764 /api/auth/status 200 ready=false history_ready=false
```

The spare listener was stopped and `18765` no longer accepts connections. The
transition can be repeated with the same command on `18764` only after the two
secrets in §5 are registered and the restart is explicitly authorized.

## 9. #5484 pointer publication and live binding (2026-10-21)

Two gaps were closed on 2026-10-21. The COM2 B62 runtime had served the
generation published on 2026-10-19 while the D1/R2 sync published a new one
every day, and the live `18764` listener ran the unbound entry, so it served no
history, no outputs and no canonical identity at all.

### 9.1 The pointer is now published with the sync

Nothing published `generation-store/current_generation.json` after a successful
sync, so the pointer went stale as soon as the next generation was published.
`scripts/ops/com2_b62_generation_publish.py` publishes it:

- the writable Chat seed is prepared from the **immutable published snapshot**
  (temporary name, SHA-256 comparison, integrity check, atomic move), so the
  published generation is never modified and an existing seed is verified
  instead of overwritten;
- the pointer is written atomically only after the seed is in place, and the
  previous pointer is kept as `current_generation.json.previous` for a
  rollback;
- `production_bound` stays `false`. The tool only selects which local
  generation the COM2 runtime opens; it never binds production;
- the published pointer is re-checked with the same rules the runtime and the
  read-only operator verifier (`com2_b62_generation.py verify`) use.

The sync runner publishes the pointer right after a successful D1 step, so the
pointer cannot go stale again. The step is skipped, and recorded as skipped, on
a host without a B62 runtime store. A real publish failure fails the sync: a
runtime that keeps serving an old generation is not a successful sync.

### 9.2 The live listener now runs the bound composition

`start-b62-release.ps1` composes the published generation and the canonical
identity read path **by default**. It runs through the existing `store.py`, so
the DPAPI environment supplies the identity bridge and auth values, and it
adds the storage-migration path that holds the generation binding modules. The
supervisor starts the script without arguments, so this is the only lever that
reaches the live entry.

`-Unbound` is the explicit rollback to the previous entry. The pointer and the
imported generations stay read-only, so reverting the runtime touches no
artifact.

Verified on the COM2 host on 2026-10-21:

```text
pointer            d1_generation=20261021T074313336936Z r2_generation=20261021T074335749153Z
                   d1_seed=chat-20261021T074313336936Z.sqlite3 d1_tables=66 production_bound=false
operator verify    B62_GENERATION_OK d1_generation=20261021T074313336936Z ... d1_tables=66
live 18764/health auth_configured=true history_store_bound=true project_file_store_bound=true
                   saved_output_store_bound=true canonical_identity_bound=true
                   identity_shadow_bound=true quota_store_bound=true
live 18764/auth    ready=true history_ready=true methods={"google":false,"password":true}
supervisor         healthy=true issues=[] chat/claw/engine ready, b62 managed
live data          seed=chat-20261021T074313336936Z.sqlite3 tables=66 users=37
                   conversations=134 messages=429
```

The canonical identity read path was exercised against the real bridge with a
non-existent session id: the bridge answered with a well-formed
`canonical_auth_session_not_found`, and the authority refused it. The read
path is reachable and authenticated from COM2.

Two things are still open and are not part of this change:

- Google login and the GitHub connector stay blocked because
  `PADIEM_CHAT_GOOGLE_CLIENT_SECRET` and `PADIEM_GITHUB_APP_CLIENT_SECRET` are
  not in the DPAPI store (§5). Password login and the identity binding work.
- The runtime supervisor's own `restart` cannot act on this component while its
  recorded pid is stale, so the live entry was moved by stopping the listener
  and letting the existing `ensure` start it again.

Cloudflare production was not touched by this change: `chat.padiem.net` kept
serving the same revision, stayed authenticated, and answered a real model
call over the same orchestration path.

