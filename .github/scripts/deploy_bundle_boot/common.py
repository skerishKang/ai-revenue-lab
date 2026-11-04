"""Shared helpers for the deploy-bundle boot tests (#6855).

These scripts run only on a disposable CI runner. They never deploy, never
contact Cloudflare, and never read a real credential: every value that looks
like a secret below is generated inside the job.
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def run(cmd, *, cwd=None, env=None, check=True, capture=False):
    printable = " ".join(str(part) for part in cmd)
    print("+ " + printable, flush=True)
    completed = subprocess.run(
        [str(part) for part in cmd],
        cwd=None if cwd is None else str(cwd),
        env=env,
        check=False,
        text=True,
        capture_output=capture,
    )
    if check and completed.returncode != 0:
        if capture:
            sys.stdout.write(completed.stdout or "")
            sys.stderr.write(completed.stderr or "")
        raise SystemExit(f"COMMAND=FAIL exit={completed.returncode} cmd={printable}")
    return completed


def require_root() -> None:
    if os.geteuid() != 0:
        raise SystemExit("BOOT_TEST=FAIL reason=root_required")


def ensure_user(name: str) -> None:
    if subprocess.run(["id", "-u", name], capture_output=True).returncode == 0:
        return
    run([
        "useradd", "--system", "--user-group",
        "--home-dir", "/nonexistent", "--shell", "/usr/sbin/nologin", name,
    ])


def install_tree(src: Path, dst: Path, *, owner: str = "root:root") -> None:
    """Copy a directory so a non-privileged account can read it.

    The real deployments failed when the service account could not read a
    root-owned 0600/0700 tree. The positive control therefore deliberately
    installs the same tree world-readable; the negative control narrows it
    again and asserts that the boot/import fails.
    """
    run(["rm", "-rf", str(dst)])
    run(["install", "-d", "-m", "0755", str(dst)])
    run(["cp", "-a", str(src) + "/.", str(dst)])
    run(["chown", "-R", owner, str(dst)])
    run(["chmod", "-R", "a+rX", str(dst)])


def make_readable(path: Path) -> None:
    run(["chmod", "-R", "a+rX", str(path)])


def strip_local_packages(venv: Path, names: tuple[str, ...]) -> int:
    """Drop repo-local packages from a copied CI venv.

    uv/pip installs the checkout's own packages into site-packages (editable
    finders included). The boot test must import only the bundle, so those
    entries are removed from the copy; the staged tree is the only source left.
    """
    site_roots = list((venv / "lib").glob("python*/site-packages"))
    site_roots += [venv / "Lib" / "site-packages"]
    removed = 0
    for site in site_roots:
        if not site.is_dir():
            continue
        for entry in sorted(site.iterdir()):
            lowered = entry.name.lower()
            if any(name in lowered for name in names) and (
                entry.is_dir() or entry.suffix in {".pth", ".py", ".txt"}
            ):
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
                removed += 1
    print(f"VENV_LOCAL_PACKAGES_STRIPPED={removed} names={list(names)}", flush=True)
    return removed


def _as_user_argv(user: str, cmd, cwd: Path, env: dict[str, str]) -> list[str]:
    env_items = [f"{name}={value}" for name, value in sorted(env.items())]
    script = "cd " + shlex.quote(str(cwd)) + " && exec " + " ".join(
        shlex.quote(str(part)) for part in cmd
    )
    return ["runuser", "-u", user, "--", "env", *env_items, "bash", "-c", script]


def as_user(user: str, cmd, *, cwd: Path, env: dict[str, str], capture: bool = True):
    return run(_as_user_argv(user, cmd, cwd, env), capture=capture, check=False)


def expect_failure(label: str, user: str, cmd, *, cwd: Path, env: dict[str, str]) -> None:
    completed = as_user(user, cmd, cwd=cwd, env=env)
    if completed.returncode == 0:
        raise SystemExit(f"{label}=FAIL expected a non-zero exit")
    detail = ""
    text = (completed.stderr or completed.stdout or "").strip().splitlines()
    if text:
        # One bounded, non-secret line for the journal.
        detail = " detail=" + text[-1][:200]
    print(f"{label}=PASS exit={completed.returncode}{detail}", flush=True)


def start_as_user(user: str, cmd, *, cwd: Path, env: dict[str, str], log_path: Path):
    log_file = open(log_path, "wb")
    process = subprocess.Popen(
        _as_user_argv(user, cmd, cwd, env),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return process, log_file


def stop_process(process, log_file) -> None:
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
    log_file.close()


def log_tail(path: Path, lines: int = 40) -> str:
    try:
        data = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(data[-lines:])


def wait_health(url: str, predicate, *, seconds: int = 120, log_path: Path | None = None) -> dict:
    """Wait for the booting service to answer the health contract.

    This is a startup wait, not an application time/size ceiling: it exists only
    to notice the process finishing its import/migration work.
    """
    deadline = time.monotonic() + seconds
    last = "no_attempt"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                status = int(response.status)
                raw = response.read(262_144)
            try:
                body = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                last = f"body_not_json status={status}"
            else:
                if status == 200 and predicate(body):
                    return body
                last = f"status={status} keys={sorted(body)}"
        except urllib.error.HTTPError as exc:
            last = f"http_{exc.code}"
        except Exception as exc:  # connection refused while booting
            last = type(exc).__name__
        time.sleep(1)
    tail = "" if log_path is None else "\n" + log_tail(log_path)
    raise SystemExit(f"HEALTH=FAIL url={url} detail={last}{tail}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_manifest(root: Path) -> dict[str, str]:
    manifest: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            manifest[str(path.relative_to(root))] = sha256_file(path)
    return manifest


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fake_hex(label: str, length: int = 64) -> str:
    """Deterministic CI-only placeholder; never a real credential."""
    return hashlib.sha256(("ci-only:" + label).encode("utf-8")).hexdigest()[:length]
