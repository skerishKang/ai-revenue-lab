#!/usr/bin/env python3
"""Stage and deploy Padiem AI Engine with prebuilt local Core and adapter wheels.

Cloudflare Pywrangler currently cannot reliably install this repository's local
source dependency on ``packages/padiem-ai-core``. This helper keeps canonical
Engine/Core source untouched: it builds Core into a wheel, copies the Engine to
an ephemeral staging directory, rewrites only the staged dependency to point at
that wheel, and invokes Pywrangler from the staging directory.

Since #5151 the Engine also consumes the product adapter package
(``apps/korean-ai-code-agent``) for the PC tool contract, so that package is
staged as a wheel the same way. The sibling app directory does not exist inside
the staging tree, which is why the dependency must be rewritten too.

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
# #5151: the Engine consumes the product adapter package for the PC tool
# contract. The staged tree must carry it the same way it carries Core,
# because the sibling app directory does not exist inside the staging tree.
PRODUCT_ADAPTER_SOURCE_DEPENDENCY = (
    '"korean-ai-code-agent @ file://${PROJECT_ROOT}/../korean-ai-code-agent"'
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


def build_product_adapter_wheel(
    repo_root: Path, out_dir: Path, *, uv_command: str = "uv"
) -> Path:
    """Build the product adapter package the Engine consumes (#5151)."""
    adapter_dir = repo_root / "apps" / "korean-ai-code-agent"
    if not (adapter_dir / "pyproject.toml").is_file():
        raise RuntimeError(f"korean-ai-code-agent source not found: {adapter_dir}")

    out_dir.mkdir(parents=True, exist_ok=True)
    _run(
        [
            uv_command,
            "build",
            str(adapter_dir),
            "--wheel",
            "--out-dir",
            str(out_dir),
        ],
        cwd=repo_root,
    )
    wheels = sorted(out_dir.glob("korean_ai_code_agent-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(
            "Expected exactly one korean-ai-code-agent wheel, found "
            f"{len(wheels)} in {out_dir}"
        )
    return wheels[0]


def rewrite_staged_pyproject(
    path: Path, wheel_name: str, adapter_wheel_name: str | None = None
) -> None:
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
    if PRODUCT_ADAPTER_SOURCE_DEPENDENCY in rewritten:
        if not adapter_wheel_name:
            raise RuntimeError(
                "Staged pyproject needs the product adapter wheel, but none was built"
            )
        adapter_count = rewritten.count(PRODUCT_ADAPTER_SOURCE_DEPENDENCY)
        if adapter_count != 1:
            raise RuntimeError(
                "Expected exactly one canonical product adapter source dependency in "
                f"staged pyproject; found {adapter_count}"
            )
        rewritten = rewritten.replace(
            PRODUCT_ADAPTER_SOURCE_DEPENDENCY,
            f'"korean-ai-code-agent @ file://${{PROJECT_ROOT}}/{STAGED_WHEEL_DIR}/'
            f'{adapter_wheel_name}"',
        )
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(rewritten)


def prepare_staging(
    repo_root: Path,
    stage_dir: Path,
    wheel_path: Path,
    adapter_wheel_path: Path | None = None,
) -> Path:
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

    staged_adapter_wheel: Path | None = None
    if adapter_wheel_path is not None:
        staged_adapter_wheel = staged_wheel_dir / adapter_wheel_path.name
        shutil.copy2(adapter_wheel_path, staged_adapter_wheel)
        if sha256_file(staged_adapter_wheel) != sha256_file(adapter_wheel_path):
            raise RuntimeError("Staged product adapter wheel hash mismatch")

    rewrite_staged_pyproject(
        stage_dir / "pyproject.toml",
        staged_wheel.name,
        staged_adapter_wheel.name if staged_adapter_wheel is not None else None,
    )

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
    # #5151: the Engine consumes the product adapter package, so the staged
    # tree needs its wheel exactly like the Core wheel.
    adapter_wheel = build_product_adapter_wheel(
        repo_root, wheel_dir, uv_command=uv_command
    )
    staged_wheel = prepare_staging(repo_root, stage_dir, wheel, adapter_wheel)

    print(f"CORE_WHEEL_FILE={wheel.name}")
    print(f"CORE_WHEEL_SHA256={sha256_file(wheel)}")
    print(f"PRODUCT_ADAPTER_WHEEL_FILE={adapter_wheel.name}")
    print(f"PRODUCT_ADAPTER_WHEEL_SHA256={sha256_file(adapter_wheel)}")
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
        description=(
            "Build the Core and product adapter wheels and deploy the Engine "
            "from an ephemeral wheel-backed staging tree."
        )
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
