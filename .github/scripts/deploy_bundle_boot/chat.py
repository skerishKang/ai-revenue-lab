"""Chat (apps/padiem-chat on COM2) deploy-bundle boot test (#6855).

The required files and the symlink pairs are read from
deploy/host-com2/chat/install.sh. The bundle is a dereferenced copy of exactly
those entries, so it no longer depends on the checkout that produced it.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

INSTALL_REL = Path("deploy/host-com2/chat/install.sh")
DEPLOY_DIR_REL = Path("deploy/host-com2/chat")
PORT = 8798
BUNDLE_DIR = Path("/opt/ci-bundles/chat")
MISSING_DIR = Path("/opt/ci-bundles/chat-missing")
DATA_DIR = Path("/opt/padiem/chat-com2/data")


def _block_items(text: str, header: str) -> list[str]:
    match = re.search(header + r" in \\\n(.*?); do", text, re.DOTALL)
    if match is None:
        raise SystemExit(f"CHAT_STAGING_PARSE=FAIL cannot find '{header}' block in install.sh")
    items = []
    for raw in match.group(1).splitlines():
        line = raw.strip()
        if line.endswith("\\"):
            line = line[:-1].strip()
        if line:
            items.append(line)
    return items


def parse_installer(repo: Path) -> dict:
    install = repo / INSTALL_REL
    text = install.read_text(encoding="utf-8")
    required = _block_items(text, "for required")
    pair_lines = _block_items(text, "for pair")
    pairs = []
    for line in pair_lines:
        match = re.fullmatch(r'"([^":]+):\$source_root/([^"]+)"', line)
        if match is None:
            raise SystemExit(f"CHAT_STAGING_PARSE=FAIL unrecognised pair line: {line}")
        pairs.append((match.group(1), match.group(2)))
    if len(required) < 2:
        raise SystemExit("CHAT_STAGING_PARSE=FAIL required list is empty")
    if len(pairs) < 2:
        raise SystemExit("CHAT_STAGING_PARSE=FAIL symlink pair list is empty")
    links = [link for link, _ in pairs]
    if len(links) != len(set(links)):
        raise SystemExit(f"CHAT_STAGING_PARSE=FAIL duplicate links: {links}")
    if 'ln -sfn "$target" "$app/$link"' not in text:
        raise SystemExit("CHAT_STAGING_PARSE=FAIL install.sh no longer links the parsed pairs")
    if "apps/padiem-chat/migrations" not in required:
        raise SystemExit("CHAT_STAGING_PARSE=FAIL migrations no longer in the required list")
    return {"required": required, "pairs": pairs}


def _copy_entry(source: Path, destination: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, destination)
    elif source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    else:
        raise SystemExit(f"CHAT_STAGING=FAIL missing source {source}")


def stage(repo: Path, bundle: Path) -> None:
    parsed = parse_installer(repo)
    for required in parsed["required"]:
        if not (repo / required).exists():
            raise SystemExit(f"CHAT_STAGING=FAIL missing required path {required}")
    bundle.mkdir(parents=True, exist_ok=True)
    staged = []
    for link, target in parsed["pairs"]:
        _copy_entry(repo / target, bundle / link)
        staged.append(link)

    # local_cpython resolves migrations as <app_root>/migrations, which the
    # real install reaches through the checkout directory holding the symlink.
    # A dereferenced bundle has to carry that directory explicitly.
    migrations_source = repo / "apps/padiem-chat/migrations"
    if migrations_source.is_dir() and not (bundle / "migrations").exists():
        shutil.copytree(migrations_source, bundle / "migrations")
        staged.append("migrations")

    # Match the app-relative static trees used through the installed symlink.
    shutil.copytree(repo / "apps/padiem-chat/static", bundle / "static")
    shutil.copytree(repo / "apps/padiem-council-apps/static", bundle / "council_static")
    staged.extend(("static", "council_static"))

    for helper in ("check_config.py", "health.py"):
        shutil.copy2(repo / DEPLOY_DIR_REL / helper, bundle / helper)
        staged.append(helper)

    for path in bundle.rglob("*"):
        if path.is_dir():
            path.chmod(0o755)
        elif path.is_file():
            path.chmod(0o644)
    manifest = {
        "installer": str(INSTALL_REL),
        "required": parsed["required"],
        "pairs": [{"link": link, "target": target} for link, target in parsed["pairs"]],
        "staged": staged,
    }
    (bundle.parent / "chat-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"CHAT_STAGING_LIST={INSTALL_REL}", flush=True)
    print(f"CHAT_STAGING_REQUIRED={len(parsed['required'])}", flush=True)
    print(f"CHAT_STAGING_PAIRS={len(parsed['pairs'])}", flush=True)


def probe_script() -> str:
    return (
        "import pathlib\n"
        "import app.local_cpython\n"
        "import app.local_cron\n"
        "root = pathlib.Path.cwd().resolve()\n"
        "for module in (app.local_cpython, app.local_cron):\n"
        "    path = pathlib.Path(module.__file__).resolve()\n"
        "    assert path.is_relative_to(root), (module.__name__, path, root)\n"
        "print('CHAT_IMPORT=PASS root=' + str(root))\n"
    )


def boot(bundle: Path, python: Path) -> None:
    common.require_root()
    if not python.is_file():
        raise SystemExit(f"CHAT_BOOT=FAIL python_missing={python}")
    common.install_tree(bundle, BUNDLE_DIR)
    common.install_tree(bundle / "council_static", BUNDLE_DIR.parent / "padiem-council-apps" / "static")
    venv = Path("/opt/ci-venvs/chat")
    common.install_tree(python.parent.parent, venv)
    common.strip_local_packages(venv, ("padiem_chat",))
    runtime_python = venv / "bin" / "python"
    if not runtime_python.exists():
        raise SystemExit("CHAT_BOOT=FAIL copied_venv_has_no_python")

    common.ensure_user("chatboot")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.chmod(0o700)
    common.run(["chown", "-R", "chatboot:chatboot", str(DATA_DIR.parent)])
    DATA_DIR.parent.chmod(0o755)

    env = {
        "PYTHONPATH": str(BUNDLE_DIR),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "PADIEM_CHAT_CPYTHON_HOST": "1",
        "PADIEM_CHAT_PUBLIC_BASE_URL": "https://chat.invalid",
        "PADIEM_CHAT_LOCAL_DATA_DIR": str(DATA_DIR),
        "PADIEM_CHAT_AUTH_MODE": "password",
        "PADIEM_CHAT_COOKIE_SECURE": "true",
        "PADIEM_CHAT_SESSION_SECRET": common.fake_hex("chat-session"),
        "PADIEM_CHAT_RUNTIME_MODE": "mock",
        "PADIEM_CHAT_WEB_PROVIDER": "off",
        "PADIEM_CHAT_LIVE_ENABLED": "false",
        "PADIEM_CHAT_WORKERS": "1",
    }
    probe = [runtime_python, "-c", probe_script()]
    positive = common.as_user("chatboot", probe, cwd=BUNDLE_DIR, env=env)
    if positive.returncode != 0:
        sys.stdout.write(positive.stdout or "")
        sys.stderr.write(positive.stderr or "")
        raise SystemExit("CHAT_BUNDLE_IMPORT=FAIL")

    log_path = Path("/tmp/chat-bundle-boot.log")
    server, log_file = common.start_as_user(
        "chatboot",
        [
            runtime_python, "-m", "app.local_server",
            "--host", "127.0.0.1", "--port", str(PORT), "--no-server-header",
        ],
        cwd=BUNDLE_DIR,
        env=env,
        log_path=log_path,
    )
    try:
        common.wait_health(
            f"http://127.0.0.1:{PORT}/health",
            lambda body: body.get("status") == "ok" and body.get("app") == "padiem-chat",
            log_path=log_path,
        )
    finally:
        common.stop_process(server, log_file)
    print(f"CHAT_BUNDLE_ONLY_BOOT=PASS HTTP=200 PORT={PORT}", flush=True)

    common.install_tree(bundle, MISSING_DIR)
    (MISSING_DIR / "app" / "local_cron.py").unlink()
    common.expect_failure(
        "CHAT_MISSING_MODULE_DETECTED", "chatboot", probe, cwd=MISSING_DIR, env=env
    )

    common.run(["chmod", "-R", "go-rwx", str(BUNDLE_DIR)])
    common.expect_failure(
        "CHAT_NARROW_PERMISSION_DENIED", "chatboot", probe, cwd=BUNDLE_DIR, env=env
    )
    common.run(["chmod", "-R", "a+rX", str(BUNDLE_DIR)])
    print("CHAT_BUNDLE_BOOT_TEST=PASS", flush=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    stage_parser = sub.add_parser("stage")
    stage_parser.add_argument("--repo", required=True, type=Path)
    stage_parser.add_argument("--bundle", required=True, type=Path)

    boot_parser = sub.add_parser("boot")
    boot_parser.add_argument("--bundle", required=True, type=Path)
    boot_parser.add_argument("--python", required=True, type=Path)

    args = parser.parse_args(argv)
    if args.command == "stage":
        stage(args.repo.resolve(), args.bundle)
    elif args.command == "boot":
        boot(args.bundle.resolve(), args.python.absolute())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
