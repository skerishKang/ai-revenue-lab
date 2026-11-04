"""B14 (apps/korean-ai-platform) deploy-bundle boot test (#6855).

The staging list is read from deploy.sh, not copied here. If deploy.sh starts
staging a different module set, this job stages exactly that set. A missing
module therefore fails at import/boot instead of only after the Cloudflare
deploy; the CI negative control removes one staged module and asserts failure.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

APP_REL = Path("apps/korean-ai-platform")
PORT = 8790
BUNDLE_DIR = Path("/opt/ci-bundles/b14")
MISSING_DIR = Path("/opt/ci-bundles/b14-missing")


def parse_deploy_script(repo: Path) -> dict:
    deploy_sh = repo / APP_REL / "deploy.sh"
    text = deploy_sh.read_text(encoding="utf-8")
    variables = {
        match.group(1): match.group(2)
        for match in re.finditer(r'^([A-Z][A-Z0-9_]*)="([^"]*)"\s*$', text, re.MULTILINE)
    }
    required_vars = (
        "B66_EXTRACTION_SOURCE", "B66_EXTRACTION_STAGED",
        "B66_INTAKE_SOURCE", "B66_INTAKE_STAGED",
        "CORE_SOURCE", "CORE_STAGED",
    )
    missing = [name for name in required_vars if name not in variables]
    if missing:
        raise SystemExit(f"B14_STAGING_PARSE=FAIL missing_variables={missing}")

    loops = [
        match.group(1).strip()
        for match in re.finditer(r"for module in ([^;]+); do", text)
    ]
    if len(loops) != 2:
        raise SystemExit(
            "B14_STAGING_PARSE=FAIL expected two 'for module in ...; do' loops "
            f"in deploy.sh, found {len(loops)}; update this job with the deploy script"
        )
    module_lists = [tuple(shlex.split(body)) for body in loops]
    if module_lists[0] != module_lists[1]:
        raise SystemExit(
            "B14_STAGING_PARSE=FAIL deploy.sh tests one module list and copies another: "
            f"{module_lists[0]} != {module_lists[1]}"
        )
    modules = list(module_lists[0])
    if not modules:
        raise SystemExit("B14_STAGING_PARSE=FAIL empty core module list")

    if 'test -f "${CORE_SOURCE}/${module}"' not in text:
        raise SystemExit("B14_STAGING_PARSE=FAIL the first module loop is not a CORE_SOURCE existence check")
    if 'cp "${CORE_SOURCE}/${module}" "${CORE_STAGED}/${module}"' not in text:
        raise SystemExit("B14_STAGING_PARSE=FAIL the second module loop is not a CORE_SOURCE copy")

    init_match = re.search(
        r"printf '%s\\n' '([^']+)' > \"\$\{CORE_STAGED\}/__init__\.py\"", text
    )
    if init_match is None:
        raise SystemExit("B14_STAGING_PARSE=FAIL cannot find the staged package __init__ printf")
    if not modules:
        raise SystemExit("B14_STAGING_PARSE=FAIL no core modules")

    return {
        "deploy_sh": str(deploy_sh.relative_to(repo)),
        "variables": variables,
        "modules": modules,
        "init_line": init_match.group(1),
    }


def stage(repo: Path, manifest_path: Path) -> None:
    parsed = parse_deploy_script(repo)
    app_dir = repo / APP_REL
    variables = parsed["variables"]
    staged: dict[str, str] = {}

    for source_key, staged_key in (
        ("B66_EXTRACTION_SOURCE", "B66_EXTRACTION_STAGED"),
        ("B66_INTAKE_SOURCE", "B66_INTAKE_STAGED"),
    ):
        source = (app_dir / variables[source_key]).resolve()
        destination = app_dir / variables[staged_key]
        if not source.is_file():
            raise SystemExit(f"B14_STAGING=FAIL missing source {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        staged[str(destination.relative_to(app_dir))] = common.sha256_file(destination)

    core_source = (app_dir / variables["CORE_SOURCE"]).resolve()
    core_staged = app_dir / variables["CORE_STAGED"]
    core_staged.mkdir(parents=True, exist_ok=True)
    for module in parsed["modules"]:
        source = core_source / module
        if not source.is_file():
            raise SystemExit(f"B14_STAGING=FAIL missing core module {source}")
        destination = core_staged / module
        shutil.copy2(source, destination)
        staged[str(destination.relative_to(app_dir))] = common.sha256_file(destination)

    init_path = core_staged / "__init__.py"
    init_path.write_text(parsed["init_line"] + "\n", encoding="utf-8")
    staged[str(init_path.relative_to(app_dir))] = common.sha256_file(init_path)

    manifest = {
        "app": str(APP_REL),
        "deploy_sh": parsed["deploy_sh"],
        "modules": parsed["modules"],
        "core_staged": variables["CORE_STAGED"],
        "files": staged,
    }
    common.write_json(manifest_path, manifest)
    print(f"B14_STAGING_LIST={parsed['deploy_sh']}", flush=True)
    print(f"B14_STAGING_MODULES={len(parsed['modules'])}", flush=True)
    print(f"B14_STAGING_FILES={len(staged)}", flush=True)


def verify_bundle(bundle: Path, manifest: dict) -> None:
    required = [
        "worker.py",
        "asgi.py",
        "app/main.py",
        f"{manifest['core_staged']}/__init__.py",
    ] + [f"{manifest['core_staged']}/{name}" for name in manifest["modules"]]
    missing = [name for name in required if not (bundle / name).is_file()]
    if missing:
        raise SystemExit(f"B14_BUNDLE=FAIL missing_from_wrangler_outdir={missing}")
    leaked = [name for name in required if (bundle / name).is_symlink()]
    if leaked:
        raise SystemExit(f"B14_BUNDLE=FAIL bundle entry is a symlink={leaked}")
    print(
        f"B14_WRANGLER_BUNDLE=PASS files={sum(1 for p in bundle.rglob('*') if p.is_file())}",
        flush=True,
    )


def probe_script(modules: list[str]) -> str:
    names = [
        "padiem_ai_core",
        "app.main",
        "app.b66_extraction_routing",
        "app.b66_file_intake",
    ] + [f"padiem_ai_core.{name[:-3]}" for name in modules]
    return (
        "import importlib, pathlib\n"
        f"names = {names!r}\n"
        "for name in names:\n"
        "    importlib.import_module(name)\n"
        "import app, padiem_ai_core\n"
        "root = pathlib.Path.cwd().resolve()\n"
        "for module in (app, padiem_ai_core):\n"
        "    path = pathlib.Path(module.__file__).resolve()\n"
        "    assert path.is_relative_to(root), (module.__name__, path, root)\n"
        "print('B14_IMPORT=PASS root=' + str(root))\n"
    )


def boot(bundle: Path, manifest_path: Path, python: Path) -> None:
    common.require_root()
    if not python.is_file():
        raise SystemExit(f"B14_BOOT=FAIL python_missing={python}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    modules = manifest["modules"]

    # Bundle-only folder: no checkout path is on PYTHONPATH.
    common.install_tree(bundle, BUNDLE_DIR)
    venv = Path("/opt/ci-venvs/b14")
    common.install_tree(python.parent.parent, venv)
    runtime_python = venv / "bin" / "python"
    if not runtime_python.exists():
        runtime_python = venv / "Scripts" / "python.exe"
    if not runtime_python.exists():
        raise SystemExit("B14_BOOT=FAIL copied_venv_has_no_python")

    common.ensure_user("b14boot")
    env = {"PYTHONPATH": str(BUNDLE_DIR), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}
    probe = [runtime_python, "-c", probe_script(modules)]

    positive = common.as_user("b14boot", probe, cwd=BUNDLE_DIR, env=env)
    if positive.returncode != 0:
        sys.stdout.write(positive.stdout or "")
        sys.stderr.write(positive.stderr or "")
        raise SystemExit("B14_BUNDLE_IMPORT=FAIL")

    log_path = Path("/tmp/b14-bundle-boot.log")
    server, log_file = common.start_as_user(
        "b14boot",
        [
            runtime_python, "-m", "uvicorn", "asgi:app",
            "--host", "127.0.0.1", "--port", str(PORT),
            "--no-server-header", "--no-access-log",
        ],
        cwd=BUNDLE_DIR,
        env=env,
        log_path=log_path,
    )
    try:
        common.wait_health(
            f"http://127.0.0.1:{PORT}/health",
            lambda body: body.get("status") == "ok" and body.get("app") == "korean-ai-platform",
            log_path=log_path,
        )
    finally:
        common.stop_process(server, log_file)
    print(f"B14_BUNDLE_ONLY_BOOT=PASS HTTP=200 PORT={PORT}", flush=True)

    # Negative control 1: one staged module removed must break the import.
    common.install_tree(bundle, MISSING_DIR)
    removed = MISSING_DIR / manifest["core_staged"] / modules[-1]
    removed.unlink()
    common.expect_failure(
        "B14_MISSING_MODULE_DETECTED", "b14boot", probe, cwd=MISSING_DIR, env=env
    )

    # Negative control 2: root-only 0600/0700 permissions must block the service user.
    common.run(["chmod", "-R", "go-rwx", str(BUNDLE_DIR)])
    common.expect_failure(
        "B14_NARROW_PERMISSION_DENIED", "b14boot", probe, cwd=BUNDLE_DIR, env=env
    )
    common.run(["chmod", "-R", "a+rX", str(BUNDLE_DIR)])
    print("B14_BUNDLE_BOOT_TEST=PASS", flush=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    stage_parser = sub.add_parser("stage")
    stage_parser.add_argument("--repo", required=True, type=Path)
    stage_parser.add_argument("--manifest", required=True, type=Path)

    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--bundle", required=True, type=Path)
    verify_parser.add_argument("--manifest", required=True, type=Path)

    boot_parser = sub.add_parser("boot")
    boot_parser.add_argument("--bundle", required=True, type=Path)
    boot_parser.add_argument("--manifest", required=True, type=Path)
    boot_parser.add_argument("--python", required=True, type=Path)

    args = parser.parse_args(argv)
    if args.command == "stage":
        stage(args.repo.resolve(), args.manifest)
    elif args.command == "verify":
        verify_bundle(args.bundle, json.loads(args.manifest.read_text(encoding="utf-8")))
    elif args.command == "boot":
        boot(args.bundle.resolve(), args.manifest, args.python.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
