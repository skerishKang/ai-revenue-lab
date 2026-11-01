"""COM2 Uvicorn launcher; one worker unless the owner's escape hatch is on.

Uses Uvicorn's existing process supervisor and the existing SQLite stores.
No Redis, extra process registry or second background-job authority is created.

11-02: COM2 actually ran two Chat workers, and every serialization contract in
the app assumes one process — the edge-verification semaphore (#6563), the
per-upload tus locks (#6604) and the replay connection (#6610). Two workers
turned healthy requests into spurious 403s, so the launcher refuses any count
above one until those contracts are made cross-process (an owner decision),
and ``PADIEM_CHAT_ALLOW_MULTI_WORKERS=1`` is the only way past the refusal.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import sys

_LOCAL_FILESYSTEMS = frozenset({"ext2", "ext3", "ext4", "xfs", "btrfs", "f2fs",
                              "zfs", "tmpfs", "ramfs", "overlay"})

#: One line, operator-facing, no configuration values in it.
MULTI_WORKER_REASON = (
    "프로세스 1개 전제 잠금: edge·tus·replay — 교차 프로세스화 전에는 1만 허용"
)


def multi_workers_allowed(env=None) -> bool:
    """The owner's explicit escape hatch; off in every deployment today."""
    env = os.environ if env is None else env
    return str(env.get("PADIEM_CHAT_ALLOW_MULTI_WORKERS", "")).strip().lower() in {
        "1", "true", "yes", "on",
    }


def worker_count(env=None) -> int:
    env = os.environ if env is None else env
    raw = str(env.get("PADIEM_CHAT_WORKERS", "1")).strip()
    if not raw.isascii() or not raw.isdecimal() or int(raw) < 1:
        raise RuntimeError("invalid_chat_workers")
    return int(raw)


def _mount_path(value: str) -> Path:
    return Path(re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), value))


def validate_multiworker_storage(data_dir: Path, workers: int, *,
                                 mountinfo_path=Path("/proc/self/mountinfo")) -> None:
    """WAL needs a local filesystem; refuse unknown, 9p and network mounts.

    Resolve symlinks and use the deepest covering mount, including file bind
    mounts. The single-worker deployment keeps its existing storage behavior.
    """
    if workers == 1:
        return
    if not sys.platform.startswith("linux"):
        raise RuntimeError("multiworker_local_filesystem_required")
    try:
        target = Path(data_dir).resolve()
        candidates = []
        for line in Path(mountinfo_path).read_text(encoding="utf-8").splitlines():
            before, after = line.split(" - ", 1)
            mount = _mount_path(before.split()[4])
            if target.is_relative_to(mount):
                candidates.append((len(mount.parts), after.split()[0]))
        filesystem = max(candidates, key=lambda item: item[0])[1]
    except (OSError, ValueError, IndexError, RuntimeError):
        raise RuntimeError("multiworker_local_filesystem_required") from None
    if filesystem not in _LOCAL_FILESYSTEMS:
        raise RuntimeError("multiworker_local_filesystem_required")


def validate_worker_configuration(env=None, *, mountinfo_path=Path("/proc/self/mountinfo")) -> int:
    env = os.environ if env is None else env
    workers = worker_count(env)
    if workers > 1 and not multi_workers_allowed(env):
        raise RuntimeError("multiworker_single_process_contract")
    if workers > 1:
        if len(str(env.get("PADIEM_CHAT_SESSION_SECRET", "")).strip()) < 32:
            raise RuntimeError("multiworker_shared_session_secret_required")
        configured = str(env.get("PADIEM_CHAT_LOCAL_DATA_DIR", "")).strip()
        if not configured:
            raise RuntimeError("multiworker_local_filesystem_required")
        validate_multiworker_storage(Path(configured) / "chat.sqlite3", workers,
                                     mountinfo_path=mountinfo_path)
        replay = str(env.get("PADIEM_COM2_EDGE_REPLAY_DB", "")).strip()
        if replay:
            validate_multiworker_storage(Path(replay), workers, mountinfo_path=mountinfo_path)
    return workers


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the COM2 Chat ASGI host")
    parser.add_argument("--host", choices=("127.0.0.1", "::1", "localhost"), default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8798)
    parser.add_argument("--no-server-header", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("invalid port")
    try:
        workers = validate_worker_configuration()
    except RuntimeError as exc:
        # All launch validation errors above are literal codes; no settings
        # values, secrets, credentials or exception tracebacks are printed.
        code = str(exc)
        if code == "multiworker_single_process_contract":
            print("CHAT_WORKERS=REFUSED code=" + code + " reason=" + MULTI_WORKER_REASON,
                  file=sys.stderr, flush=True)
            return 2
        if code not in {"invalid_chat_workers", "multiworker_local_filesystem_required",
                        "multiworker_shared_session_secret_required"}:
            code = "chat_worker_configuration_unavailable"
        print("CHAT_WORKERS=REFUSED code=" + code, file=sys.stderr, flush=True)
        return 2
    import uvicorn
    from .access_log import uvicorn_log_config
    uvicorn.run("app.local_cpython:build_app", factory=True, host=args.host,
                port=args.port, workers=workers, server_header=False,
                log_config=uvicorn_log_config(uvicorn.config.LOGGING_CONFIG))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
