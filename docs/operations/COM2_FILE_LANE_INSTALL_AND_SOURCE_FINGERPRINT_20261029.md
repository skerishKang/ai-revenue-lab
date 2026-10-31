# COM2 file lane — install from a worktree, and make the installed source checkable

Memo for handoff. Nothing in this file has been implemented; it records one observed drift
and the two changes that would stop the next one. Related:
[file-lane runbook](FILE_LANE_COM2_RUNBOOK.md),
[queue cutover runbook](COM2_PC_DISPATCH_QUEUE_CUTOVER_20261029.md) (the installer this
follows), [backup rule](COM2_PC_DISPATCH_QUEUE_CUTOVER_20261029.md) (#6180).

## What happened

On 2026-10-29 the file lane's `.hwp` route was missing in production while the repo had
it. The installed package under
`/opt/padiem/file-lane/venv/lib/python3.12/site-packages/padiem_file_lane` held **8**
modules; the checkout at `/opt/padiem/file-lane/repo` (7f0eb42) held **9** — `hwp_text.py`
was never installed and `app.py` differed — and `olefile` was not in the venv at all.

A two-file copy plus one `pip install "olefile>=0.46,<1"` fixed it, with a real-byte
backup of `app.py` first (`/opt/padiem/file-lane/backup-<stamp>/`). That was an approved
emergency measure, and it is also the problem: **nothing on the host records what was
installed or from which commit**, so the next `app.py` change reproduces the same drift
and the same 404.

## Target state

Installed == a pinned commit, provable on the host, with no content read and no per-request
cost.

## Install, modeled on `apps/padiem-mesh-queue/deploy/install.sh`

1. **Own worktree.** `git worktree add --detach /opt/padiem/file-lane/src <main sha>`.
   The shared checkout `/opt/padiem/oracle-mesh/repo` is what other units read; installing
   this lane must not move it (same reason the queue got its own worktree).
2. **Real bytes first.** `cp -a` the installed package directory and a `pip freeze` into
   `/opt/padiem/backups/file-lane/<stamp>/` before touching anything. A link is not a
   backup (#6180): it follows the target that is about to change.
3. **Install from the worktree.** `pip install --no-deps --no-build-isolation
   <worktree>/apps/padiem-file-lane` — the project's `file://${PROJECT_ROOT}` dependency
   template is not PEP 508, so a resolving install cannot succeed and `--no-deps` is the
   honest form; the dependency set is checked in step 4 instead. Where the build backend
   is unavailable, `rsync` the `src/padiem_file_lane/` tree into site-packages is
   equivalent, with `--delete` and an explicit `--exclude /src` so a re-run cannot eat the
   worktree (the queue installer's guard; a nested source outside `src/` is refused).
4. **Check before systemd is asked to start.** `venv/bin/python -c "import
   padiem_file_lane.app as a; a.create_app(root=Path(...))"` plus `pip check`; only then
   restart and read `/health`. A failed check leaves the previous install running.

Idempotent and re-runnable: refreshing to a new main is "re-fetch the worktree, run the
script again".

## Making the installed source checkable

**Option B — host monitor (recommended first).** The host monitor timer (#6141) compares
the installed package against the worktree commit — file names and hashes, or simply
`missng/extra/changed` counts — and logs one line:

```
FILE_LANE_SOURCE=MATCH commit=<short> files=<n>
FILE_LANE_SOURCE=DRIFT commit=<short> missing=<n> extra=<n> changed=<n>
```

`DRIFT` is a warning, never a restart: a monitor that restarts on a source mismatch turns
a stale install into an outage. This costs no service change and reads exactly the two
trees that already exist on this host.

**Option A — build stamp (additive, second).** The installer writes
`SOURCE_COMMIT` and `SOURCE_DIGEST` (sha256 over sorted `relpath:sha256` lines) into the
package when it installs it; the service reports those two values verbatim from that file
on a separate `/build` route (or `/health` with a detail flag). Truthful because the thing
that installed it wrote it, and free because nothing is walked per request.

Not recommended: computing the tree hash inside `/health`. It walks the package on every
probe and puts that I/O in the request path to learn something a build stamp already
knows.

## Acceptance

* Installing the same commit twice yields the same digest; changing one file changes it.
* A hand edit after install shows `DRIFT` within one timer tick, with no file content in
  any log line.
* A failed dependency check leaves the previously working install serving and does not
  restart the unit.
* The shared checkout is unchanged by the install (`git -C /opt/padiem/oracle-mesh/repo
  rev-parse HEAD` identical before and after).

## Handoff

* **File-lane owner lane (아스트라)**: the install script + optional build stamp.
  Either change alone is useful; together they make the drift impossible to hide.
* **Monitor lane (#6141 / #82)**: the `MATCH|DRIFT` check; the timer already runs on the
  host.
* No new network dependency, no change to the shared checkout, and nothing in this memo
  asks the file lane to stop refusing anything it refuses today.
