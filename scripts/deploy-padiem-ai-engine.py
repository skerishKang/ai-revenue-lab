#!/usr/bin/env python3
"""Stage and deploy Padiem AI Engine with a prebuilt local Core wheel.

Cloudflare Pywrangler currently cannot reliably install this repository's local
source dependency on ``packages/padiem-ai-core``. This helper keeps canonical
Engine/Core source untouched: it builds Core into a wheel, copies the Engine to
an ephemeral staging directory, rewrites only the staged dependency to point at
that wheel, and invokes Pywrangler from the staging directory.

No generated wheel is written into the repository and no runtime source/config
is modified in place.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Sequence

CORE_SOURCE_DEPENDENCY = (
    '"padiem-ai-core @ file://${PROJECT_ROOT}/../../packages/padiem-ai-core"'
)
STAGED_WHEEL_DIR = ".deploy-wheels"
WRANGLER_REQUIRED_SNIPPETS = (
    'name = "padiem-ai-engine"',
    'main = "worker_identity.py"',
    "workers_dev = false",
    'binding = "B14_SERVICE"',
    'service = "ai-revenue-korean-ai-platform"',
)
COPY_IGNORE = shutil.ignore_patterns(
    ".venv",
    ".venv-*",
    ".venv-workers",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "python_modules",
    "pylock.toml",
    "uv.lock",
)


def _run(command: Sequence[str], *, cwd: Path) -> None:
    subprocess.run(list(command), cwd=str(cwd), check=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_wrangler_contract(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    missing = [snippet for snippet in WRANGLER_REQUIRED_SNIPPETS if snippet not in text]
    if missing:
        raise RuntimeError(
            "Engine wrangler contract drifted; refusing staged deploy. Missing: "
            + ", ".join(missing)
        )


def build_core_wheel(repo_root: Path, out_dir: Path, *, uv_command: str = "uv") -> Path:
    core_dir = repo_root / "packages" / "padiem-ai-core"
    if not (core_dir / "pyproject.toml").is_file():
        raise RuntimeError(f"padiem-ai-core source not found: {core_dir}")

    out_dir.mkdir(parents=True, exist_ok=True)
    _run(
        [
            uv_command,
            "build",
            str(core_dir),
            "--wheel",
            "--out-dir",
            str(out_dir),
        ],
        cwd=repo_root,
    )
    wheels = sorted(out_dir.glob("padiem_ai_core-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(
            f"Expected exactly one padiem-ai-core wheel, found {len(wheels)} in {out_dir}"
        )
    return wheels[0]


def rewrite_staged_pyproject(path: Path, wheel_name: str) -> None:
    source = path.read_text(encoding="utf-8")
    count = source.count(CORE_SOURCE_DEPENDENCY)
    if count != 1:
        raise RuntimeError(
            "Expected exactly one canonical padiem-ai-core source dependency in staged pyproject; "
            f"found {count}"
        )
    staged_dependency = (
        f'"padiem-ai-core @ file://${{PROJECT_ROOT}}/{STAGED_WHEEL_DIR}/{wheel_name}"'
    )
    rewritten = source.replace(CORE_SOURCE_DEPENDENCY, staged_dependency)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(rewritten)


def prepare_staging(repo_root: Path, stage_dir: Path, wheel_path: Path) -> Path:
    engine_dir = repo_root / "apps" / "padiem-ai-engine"
    canonical_pyproject = engine_dir / "pyproject.toml"
    canonical_wrangler = engine_dir / "wrangler.toml"
    if not canonical_pyproject.is_file() or not canonical_wrangler.is_file():
        raise RuntimeError(f"Padiem AI Engine source/config not found: {engine_dir}")
    validate_wrangler_contract(canonical_wrangler)

    canonical_pyproject_sha = sha256_file(canonical_pyproject)
    canonical_wrangler_bytes = canonical_wrangler.read_bytes()

    if stage_dir.exists():
        raise RuntimeError(f"Staging directory must not already exist: {stage_dir}")
    shutil.copytree(engine_dir, stage_dir, ignore=COPY_IGNORE)

    staged_wrangler = stage_dir / "wrangler.toml"
    if staged_wrangler.read_bytes() != canonical_wrangler_bytes:
        raise RuntimeError("Staged wrangler.toml differs from canonical config before deploy")

    staged_wheel_dir = stage_dir / STAGED_WHEEL_DIR
    staged_wheel_dir.mkdir(parents=True, exist_ok=False)
    staged_wheel = staged_wheel_dir / wheel_path.name
    shutil.copy2(wheel_path, staged_wheel)
    if sha256_file(staged_wheel) != sha256_file(wheel_path):
        raise RuntimeError("Staged Core wheel hash mismatch")

    rewrite_staged_pyproject(stage_dir / "pyproject.toml", staged_wheel.name)

    if sha256_file(canonical_pyproject) != canonical_pyproject_sha:
        raise RuntimeError("Canonical Engine pyproject.toml changed during staging")
    if canonical_wrangler.read_bytes() != canonical_wrangler_bytes:
        raise RuntimeError("Canonical Engine wrangler.toml changed during staging")

    return staged_wheel


def deploy_staged_engine(
    stage_dir: Path,
    *,
    uvx_command: str = "uvx",
    pywrangler_package: str = "workers-py",
) -> None:
    if not os.environ.get("CLOUDFLARE_ACCOUNT_ID"):
        raise RuntimeError("CLOUDFLARE_ACCOUNT_ID must be set in the process environment")
    validate_wrangler_contract(stage_dir / "wrangler.toml")
    _run(
        [
            uvx_command,
            "--from",
            pywrangler_package,
            "pywrangler",
            "deploy",
            "--config",
            "wrangler.toml",
        ],
        cwd=stage_dir,
    )


def _prepare_and_maybe_deploy(
    *,
    repo_root: Path,
    work_root: Path,
    prepare_only: bool,
    uv_command: str,
    uvx_command: str,
) -> None:
    wheel_dir = work_root / "wheel"
    stage_dir = work_root / "engine"
    wheel = build_core_wheel(repo_root, wheel_dir, uv_command=uv_command)
    staged_wheel = prepare_staging(repo_root, stage_dir, wheel)

    print(f"CORE_WHEEL_FILE={wheel.name}")
    print(f"CORE_WHEEL_SHA256={sha256_file(wheel)}")
    print(f"STAGED_WHEEL_SHA256={sha256_file(staged_wheel)}")
    print(f"STAGED_ENGINE_DIR={stage_dir}")
    print("CANONICAL_ENGINE_RUNTIME_MUTATION=NO")
    print("CANONICAL_CORE_MUTATION=NO")

    if prepare_only:
        print("PYWRANGLER_DEPLOY=SKIPPED_PREPARE_ONLY")
        return

    deploy_staged_engine(stage_dir, uvx_command=uvx_command)
    print("PYWRANGLER_DEPLOY=PASS")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build Core wheel and deploy Engine from an ephemeral wheel-backed staging tree."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root; defaults to the parent of scripts/.",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        help="Optional empty/nonexistent work directory to preserve staging for diagnostics.",
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Build and validate staging but do not invoke Pywrangler deploy.",
    )
    parser.add_argument("--uv-command", default="uv")
    parser.add_argument("--uvx-command", default="uvx")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()

    if args.work_dir is not None:
        work_root = args.work_dir.resolve()
        if work_root.exists() and any(work_root.iterdir()):
            raise RuntimeError(f"Work directory must be empty: {work_root}")
        work_root.mkdir(parents=True, exist_ok=True)
        _prepare_and_maybe_deploy(
            repo_root=repo_root,
            work_root=work_root,
            prepare_only=args.prepare_only,
            uv_command=args.uv_command,
            uvx_command=args.uvx_command,
        )
    else:
        with tempfile.TemporaryDirectory(prefix="padiem-ai-engine-deploy-") as temp_dir:
            _prepare_and_maybe_deploy(
                repo_root=repo_root,
                work_root=Path(temp_dir),
                prepare_only=args.prepare_only,
                uv_command=args.uv_command,
                uvx_command=args.uvx_command,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
