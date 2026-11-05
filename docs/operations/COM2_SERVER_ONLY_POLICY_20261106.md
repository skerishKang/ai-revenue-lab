# COM2 is the production host only; lanes work from COM1 and deploy over SSH (Owner decision, 2026-11-06)

## Decision
- COM2 (the WSL host that runs `padiem-chat-com2`, `padiem-p01`, `padiem-oracle-mesh-executor`, `padiem-mesh-queue` and `padiem-meshcentral`) runs **production services only**. No AI lane (Claude Code session) works on COM2 any more.
- Lanes run on the authorized COM1 PC and reach COM2 over SSH with the existing key. Host, user and key path are recorded in the private COM1 governance folder (`운영방침/25_…_20261106.md`), never in this repository.
- The two COM2 lanes that were active on 2026-11-05 finish their open PRs, report, and are closed.

## Why (measured on 2026-11-05)
- One machine shared the production WSL services with lane work (test runs, git, a 323 MB tarball extraction, whole-tree `cp -a` backups). Effects observed the same evening: two WSL `WSAETIMEDOUT` bridge timeouts (23:33–23:36 KST), one Chat deploy rolled back because a cold import took 56 s against a 30 s port wait, and jittery P01 admission / identity timings.
- PC-side command time for the same 17 KB read: 11–24 s on the two developer PCs that were running lanes, 0.6–1.0 s on the idle customer-like PC (CGI-1). Customer PCs behave like CGI-1.
- MeshCentral itself caused no incident. Every slow or broken step was in the layers around it (Chat → P01 → queue → executor).
- A Windows worktree checkout (CRLF) had been copied to the Linux host as a deploy source; the service ran, but the bytes differed from the repository. Deploying from the WSL-side ops checkout (LF) avoids this.

## Remote deploy runbook (from COM1)
1. Commands sent over SSH run in the COM2 Windows shell. Linux work is a script file: `scp` it, then `ssh … "bash <file>.sh"` (bash enters WSL; use relative paths, never `~`). Keep commands short; no heavy I/O on COM2 (no whole-tree backups, no tarball extraction).
2. Deploy source is the WSL-side ops checkout `/opt/padiem/com2-deploy`: `git fetch`, detach at the merged SHA (LF bytes).
   - Chat: stage → stop → `deploy/host-com2/chat/install.sh --apply` → `check_config.py` → start → `/health` 200. Set `PADIEM_COM2_PORT_WAIT_TIMEOUT` to 120 s or more.
   - P01: `deploy/host-com2/p01/stage_code.sh <src> /opt/padiem/p01` → restart → `health.py`; previous release and `rollback/` are kept.
   - Executor (kagent): install the merged blob (`git cat-file blob <sha>:<path>`, LF) into the kagent source directory with the service user as owner, clear `__pycache__`, `py_compile`, restart.
3. Before any file change: single-file backup with a timestamp and the pre-change SHA in its name. After: sha256 equals the repository blob, unit `active`, zero error-level journal lines since restart.
4. Never print secret values (names and last four characters only). No `pkill -f`/`killall`. No direct push to `main`; PR + green CI, squash merge. No full local test runs (related tests only; the full regression is PR CI). No model/provider names in public text — PADIEM tiers only.

## Rules learned (apply to every host)
1. Do not run lane workloads on a machine that hosts production services.
2. Linux hosts are deployed from a Linux (WSL) checkout — LF bytes that match the repository blob.
3. Services on the same host talk over loopback with the edge proof; they never go out through the public hostname (see #6959, which cut result submission from 3–4.5 s to 0.2–0.3 s).
4. End-to-end timing lines in the journal come first; guessing comes after.
5. A wire shape shared by two services is pinned by one contract test that exercises both sides (the receipt and metrics-row defects of 2026-11-05 were one-sided changes).

Related: `docs/operations/PC_READ_LATENCY_REVIEW_20261105.md`, `docs/operations/B14_COM2_RUNBOOK.md`, `docs/operations/COM2_TUNNEL_RUNBOOK.md`.
