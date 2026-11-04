"""P01 (deploy/host-com2/p01) deploy-bundle boot test (#6855).

Staging is performed by the real stage_code.sh, not a copy of its list. The
staged release must keep a padiem-ai-core copy byte-identical to
packages/padiem-ai-core (the single source of truth on main), and the Engine
must answer its own /internal/v1/health contract as the non-privileged user.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

STAGE_SCRIPT_REL = Path("deploy/host-com2/p01/stage_code.sh")
HEALTH_SCRIPT_REL = Path("deploy/host-com2/p01/health.py")
CORE_REL = Path("packages/padiem-ai-core/padiem_ai_core")
PORT = 8811
MISSING_DIR = Path("/opt/ci-bundles/p01-missing")
DATA_DIR = Path("/opt/padiem/p01/data")


def _release(root: Path) -> Path:
    link = root / "app"
    if not link.exists():
        raise SystemExit(f"P01_STAGING=FAIL no staged app under {root}")
    release = link.resolve()
    if not (release / "asgi.py").is_file():
        raise SystemExit(f"P01_STAGING=FAIL asgi.py missing from {release}")
    return release


def verify_vendored_core(repo: Path, release: Path) -> dict[str, str]:
    staged = release / "padiem_ai_core"
    canonical = repo / CORE_REL
    if not staged.is_dir():
        raise SystemExit("P01_VENDORED_CORE=FAIL staged padiem_ai_core missing")
    if not canonical.is_dir():
        raise SystemExit("P01_VENDORED_CORE=FAIL canonical padiem_ai_core missing")
    staged_manifest = common.tree_manifest(staged)
    canonical_manifest = common.tree_manifest(canonical)
    if staged_manifest != canonical_manifest:
        missing = sorted(set(canonical_manifest) - set(staged_manifest))
        extra = sorted(set(staged_manifest) - set(canonical_manifest))
        changed = sorted(
            name for name in set(staged_manifest) & set(canonical_manifest)
            if staged_manifest[name] != canonical_manifest[name]
        )
        raise SystemExit(
            "P01_VENDORED_CORE=FAIL "
            f"missing={missing[:5]} extra={extra[:5]} changed={changed[:5]}"
        )
    combined = hashlib.sha256(
        "".join(f"{name}:{digest}\n" for name, digest in sorted(staged_manifest.items())).encode()
    ).hexdigest()
    print(
        f"P01_VENDORED_CORE=MATCH files={len(staged_manifest)} sha256={combined}",
        flush=True,
    )
    return staged_manifest


def stage(repo: Path, root: Path) -> None:
    common.require_root()
    stage_script = repo / STAGE_SCRIPT_REL
    if not stage_script.is_file():
        raise SystemExit(f"P01_STAGING=FAIL missing {stage_script}")
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o755)
    common.run(["bash", stage_script, repo, root])
    release = _release(root)
    verify_vendored_core(repo, release)
    print(f"P01_STAGING_LIST={STAGE_SCRIPT_REL}", flush=True)
    print(f"P01_RELEASE={release}", flush=True)


def probe_script() -> str:
    return (
        "import pathlib\n"
        "import padiem_ai_core, padiem_control_plane, kagent\n"
        "import padiem_ai_core.agent_definition\n"
        "import app\n"
        "import asgi\n"
        "root = pathlib.Path.cwd().resolve()\n"
        "for module in (padiem_ai_core, padiem_control_plane, kagent, app):\n"
        "    path = pathlib.Path(module.__file__).resolve()\n"
        "    assert path.is_relative_to(root), (module.__name__, path, root)\n"
        "print('P01_IMPORT=PASS root=' + str(root))\n"
    )


def boot(repo: Path, root: Path, python: Path) -> None:
    common.require_root()
    if not python.is_file():
        raise SystemExit(f"P01_BOOT=FAIL python_missing={python}")
    release = _release(root)
    verify_vendored_core(repo, release)

    venv = Path("/opt/ci-venvs/p01")
    common.install_tree(python.parent.parent, venv)
    common.strip_local_packages(
        venv,
        ("padiem_ai_core", "korean_ai_code_agent", "padiem_control_plane", "padiem_ai_engine"),
    )
    runtime_python = venv / "bin" / "python"
    if not runtime_python.exists():
        raise SystemExit("P01_BOOT=FAIL copied_venv_has_no_python")

    common.ensure_user("p01boot")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.chmod(0o700)
    common.run(["chown", "-R", "p01boot:p01boot", str(DATA_DIR.parent)])
    DATA_DIR.parent.chmod(0o755)

    env = {
        "PYTHONPATH": str(release),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "PADIEM_ENGINE_CPYTHON_HOST": "1",
        "P01_HOST": "127.0.0.1",
        "P01_PORT": str(PORT),
        "PADIEM_ENGINE_CALLER_ID": "ci-caller",
        "PADIEM_ENGINE_CALLER_SECRET": common.fake_hex("p01-caller"),
        "PADIEM_ENGINE_LOCAL_DB": str(DATA_DIR / "engine.sqlite"),
        "PADIEM_ENGINE_LOCAL_CHAT_ORIGIN": "http://127.0.0.1:8798",
        "PADIEM_ENGINE_LOCAL_B14_ORIGIN": "http://127.0.0.1:8790",
        "PADIEM_B14_SERVICE_PROOF_SECRET": common.fake_hex("p01-b14-proof"),
        "CLAW_ENGINE_DESKTOP_SECRET": common.fake_hex("p01-desktop"),
    }
    probe = [runtime_python, "-c", probe_script()]
    positive = common.as_user("p01boot", probe, cwd=release, env=env)
    if positive.returncode != 0:
        sys.stdout.write(positive.stdout or "")
        sys.stderr.write(positive.stderr or "")
        raise SystemExit("P01_BUNDLE_IMPORT=FAIL")

    log_path = Path("/tmp/p01-bundle-boot.log")
    server, log_file = common.start_as_user(
        "p01boot",
        [
            runtime_python, "-m", "uvicorn", "asgi:app",
            "--host", "127.0.0.1", "--port", str(PORT),
            "--no-server-header", "--no-access-log",
        ],
        cwd=release,
        env=env,
        log_path=log_path,
    )
    try:
        common.wait_health(
            f"http://127.0.0.1:{PORT}/internal/v1/health",
            lambda body: (
                body.get("status") == "ok"
                and body.get("service") == "padiem-ai-engine"
                and body.get("completed_run") is True
                and body.get("streaming_run") is True
                and body.get("service_identity") == "required_for_all_non_health_routes"
            ),
            log_path=log_path,
        )
        # The service account cannot traverse the runner workspace, so the
        # host probe runs from the staged release with a copied health script.
        health_script = Path("/opt/ci-bundles/p01-health.py")
        health_script.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo / HEALTH_SCRIPT_REL, health_script)
        health_script.chmod(0o644)
        host_probe = common.as_user(
            "p01boot",
            [
                "/usr/bin/python3", health_script,
                "--url", f"http://127.0.0.1:{PORT}/internal/v1/health",
            ],
            cwd=release,
            env={},
        )
        if host_probe.returncode != 0:
            sys.stdout.write(host_probe.stdout or "")
            sys.stderr.write(host_probe.stderr or "")
            raise SystemExit("P01_HOST_HEALTH_PROBE=FAIL")
    finally:
        common.stop_process(server, log_file)
    print(f"P01_BUNDLE_ONLY_BOOT=PASS HTTP=200 PORT={PORT}", flush=True)

    common.install_tree(release, MISSING_DIR)
    (MISSING_DIR / "padiem_ai_core" / "agent_definition.py").unlink()
    common.expect_failure(
        "P01_MISSING_MODULE_DETECTED", "p01boot", probe, cwd=MISSING_DIR, env=env
    )

    common.run(["chmod", "-R", "go-rwx", str(release)])
    common.expect_failure(
        "P01_NARROW_PERMISSION_DENIED", "p01boot", probe, cwd=release, env=env
    )
    common.run(["chmod", "-R", "a+rX", str(release)])
    print("P01_BUNDLE_BOOT_TEST=PASS", flush=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    stage_parser = sub.add_parser("stage")
    stage_parser.add_argument("--repo", required=True, type=Path)
    stage_parser.add_argument("--root", required=True, type=Path)

    boot_parser = sub.add_parser("boot")
    boot_parser.add_argument("--repo", required=True, type=Path)
    boot_parser.add_argument("--root", required=True, type=Path)
    boot_parser.add_argument("--python", required=True, type=Path)

    args = parser.parse_args(argv)
    if args.command == "stage":
        stage(args.repo.resolve(), args.root)
    elif args.command == "boot":
        boot(args.repo.resolve(), args.root, args.python.absolute())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
