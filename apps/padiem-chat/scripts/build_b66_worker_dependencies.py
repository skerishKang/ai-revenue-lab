"""Install the committed Worker lock with an explicit Pyodide wheel platform.

The Windows pywrangler installer can reject Pyodide wheels after successfully
resolving them. This adapter uses uv's supported target platform and the same
pylock.toml; it does not resolve or upgrade dependencies, build MuPDF, or fetch
packages during a quote request. Normal pywrangler sync remains the default.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import tomllib


APP_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIRECTORY = ".b66-worker-src"
RUNTIME_MARKER = ".b66-generated.json"

def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def validate_lock(lock: dict) -> dict[str, str]:
    return {
        normalize(package["name"]): package["version"]
        for package in lock.get("packages", [])
        if isinstance(package.get("name"), str) and isinstance(package.get("version"), str)
    }



def require_unlinked_output(output: Path) -> None:
    for ancestor in (output, *output.parents):
        if ancestor.exists() and (
            ancestor.is_symlink()
            or getattr(ancestor.stat(), "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            raise ValueError("Worker dependency output must not traverse a symlink or junction")


def consume_pywrangler_placeholder(output: Path) -> bool:
    """Remove only pywrangler's marker-only handoff, never arbitrary vendor data."""
    require_unlinked_output(output)
    if not output.exists():
        return False
    if not output.is_dir():
        return False
    entries = {item.name: item for item in output.iterdir()}
    if set(entries) != {".synced", "pyvenv.cfg"}:
        return False
    synced = entries[".synced"]
    pyvenv = entries["pyvenv.cfg"]
    if (
        not synced.is_file()
        or not pyvenv.is_file()
        or synced.is_symlink()
        or pyvenv.is_symlink()
        or synced.stat().st_size > 128
        or pyvenv.stat().st_size > 4096
    ):
        raise ValueError("Unsafe pywrangler placeholder")
    version = synced.read_text(encoding="utf-8").strip()
    if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) is None:
        raise ValueError("Unexpected pywrangler placeholder version")
    synced.unlink()
    pyvenv.unlink()
    return True


def require_fresh_output(output: Path) -> None:
    require_unlinked_output(output)
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Worker dependency output must be a new or empty directory")


def installed_versions(output: Path, versions: dict[str, str]) -> dict[str, str]:
    installed = {
        normalize(dist.metadata["Name"]): dist.version
        for dist in importlib.metadata.distributions(path=[str(output)])
        if dist.metadata.get("Name")
    }
    mismatched = [name for name, version in versions.items() if installed.get(name) != version]
    if mismatched:
        raise ValueError("Installed versions differ from Worker lock: " + ", ".join(mismatched))
    return installed


def generate_runtime(app_root: Path = APP_ROOT) -> dict:
    """Copy canonical runtime sources; keep dependencies outside moduleRoot."""
    output = app_root / RUNTIME_DIRECTORY
    if output.resolve().parent != app_root.resolve() or output.is_symlink():
        raise ValueError("Generated runtime must stay inside the application root")
    if output.exists():
        marker = output / RUNTIME_MARKER
        if not marker.is_file() or json.loads(marker.read_text()).get("owner") != "b66-worker-src-v1":
            raise ValueError("Refusing to replace an unmarked generated runtime directory")
        for path in output.rglob("*"):
            if path.is_symlink() or getattr(path.stat(), "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                raise ValueError("Generated runtime must not contain symlinks or junctions")
        shutil.rmtree(output)
    output.mkdir()
    shutil.copy2(app_root / "worker.py", output / "worker.py")
    shutil.copytree(app_root / "app", output / "app", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # Starlette validates STATIC_DIR while the Python module is imported by the
    # Worker version API. Assets are also uploaded through Cloudflare's Assets
    # binding, but the generated Python moduleRoot must retain this canonical
    # directory so version validation does not fail before the Worker starts.
    shutil.copytree(app_root / "static", output / "static")
    hashes = {}
    for path in output.rglob("*"):
        if path.is_file():
            relative = path.relative_to(output)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != hashlib.sha256((app_root / relative).read_bytes()).hexdigest():
                raise ValueError("Generated runtime differs from canonical source")
            hashes[relative.as_posix()] = digest
    (output / RUNTIME_MARKER).write_text(json.dumps({"owner": "b66-worker-src-v1", "files": hashes}, indent=2))
    return {"runtime": str(output), "byte_identical": True, "source_file_count": len(hashes)}


def stage_local_packages(lock_path: Path, staging: Path) -> Path:
    """Build path dependencies from copies so setuptools cannot alter the repo."""
    text = lock_path.read_text(encoding="utf-8")
    generated = shutil.ignore_patterns(
        ".git", ".venv*", "node_modules", "python_modules", "build", "dist",
        "__pycache__", "*.pyc", "*.egg-info", ".env*", ".dev.vars*",
    )
    for index, package in enumerate(tomllib.loads(text)["packages"]):
        source_path = package.get("directory", {}).get("path")
        if not source_path:
            continue
        source = (lock_path.parent / source_path).resolve(strict=True)
        copied = staging / f"local-{index}"
        shutil.copytree(source, copied, ignore=generated, symlinks=True)
        for path in copied.rglob("*"):
            if path.is_symlink() or (
                getattr(path.stat(), "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            ):
                raise ValueError("Local build source must not contain symlinks or junctions")
        original = f'directory = {{ path = "{source_path}" }}'
        replacement = "directory = { path = " + json.dumps(copied.as_posix()) + " }"
        if text.count(original) != 1:
            raise ValueError("Unexpected local path entry in Worker lock")
        text = text.replace(original, replacement)
    staged_lock = staging / "pylock.toml"
    staged_lock.write_text(text, encoding="utf-8")
    return staged_lock


def build(output: Path, *, lock_path: Path = APP_ROOT / "pylock.toml", uv: str = "uv") -> dict:
    locked_bytes = lock_path.read_bytes()
    versions = validate_lock(tomllib.loads(locked_bytes.decode("utf-8")))
    require_unlinked_output(output)
    consume_pywrangler_placeholder(output)
    try:
        require_fresh_output(output)
    except ValueError:
        # A completed standard pywrangler sync is reusable after lock and ABI
        # verification. No generated vendor files are deleted or stripped.
        installed_versions(output, versions)
        return {"status": "PASS", "reused_locked_vendor": True, "lock_sha256": hashlib.sha256(locked_bytes).hexdigest(), "output": str(output)}
    output.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PROJECT_ROOT"] = str(lock_path.parent)
    staging = Path(tempfile.mkdtemp(prefix=".b66-worker-build-", dir=output.parent))
    try:
        staged_lock = stage_local_packages(lock_path, staging)
        subprocess.run(
            [
                uv, "pip", "install", "--python-platform", "wasm32-pyodide2025",
                "--python-version", "3.13", "--target", str(output),
                "--requirements", str(staged_lock), "--preview-features", "pylock",
                "--link-mode", "copy",
            ],
            cwd=lock_path.parent,
            env=env,
            check=True,
        )
    finally:
        if staging.resolve().parent != output.parent.resolve() or staging.is_symlink():
            raise ValueError("Refusing to remove build staging outside the output parent")
        shutil.rmtree(staging)
    installed = installed_versions(output, versions)
    (output / "pyvenv.cfg").touch()
    return {
        "status": "PASS",
        "platform": "wasm32-pyodide2025",
        "workers_runtime_sdk": installed.get("workers-runtime-sdk"),
        "lock_sha256": hashlib.sha256(locked_bytes).hexdigest(),
        "locked_package_count": len(versions),
        "output": str(output),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=APP_ROOT / "python_modules")
    args = parser.parse_args()
    result = build(args.output.absolute())
    result.update(generate_runtime())
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
