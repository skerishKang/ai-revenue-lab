"""Assemble the Cloudflare Python Worker tree for padiem-document-parser.

The parser Worker reuses the existing Core package and its reviewed
``documents`` extra (pypdf + openpyxl). The committed ``pylock.toml`` is the
only dependency authority: this script never resolves, upgrades, builds or
fetches an unreviewed package during a request or a deploy. It installs the lock
for the Pyodide target, proves every installed distribution is pure Python (the
Pyodide runtime cannot load CPython native extensions), and copies the reviewed
runtime source into wrangler's ``base_dir`` with a byte-identical check.

Run with: ``uv run python scripts/build_worker_dependencies.py``
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
RUNTIME_DIRECTORY = ".worker-src"
RUNTIME_MARKER = ".document-parser-generated.json"
RUNTIME_FILES = ("worker.py",)
#: Native extension suffixes no Pyodide bundle may contain.
_NATIVE_SUFFIXES = {".so", ".pyd", ".dll", ".dylib", ".wasm"}


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def validate_lock(lock: dict) -> dict[str, str]:
    versions: dict[str, str] = {}
    for package in lock.get("packages", []):
        name = package.get("name")
        if not isinstance(name, str):
            raise ValueError("Worker lock entry without a package name")
        if "directory" not in package:
            version = package.get("version")
            if not isinstance(version, str):
                raise ValueError(f"Worker lock entry without a version: {name}")
            versions[normalize(name)] = version
            wheels = package.get("wheels") or []
            if not wheels:
                raise ValueError(f"Worker lock entry without a wheel: {name}")
            for wheel in wheels:
                url = wheel.get("url") if isinstance(wheel, dict) else None
                if not isinstance(url, str) or not url.endswith("-none-any.whl"):
                    raise ValueError(
                        f"Worker lock wheel is not platform-independent: {name}"
                    )
    if not versions:
        raise ValueError("Worker lock contains no versioned packages")
    return versions


def require_unlinked_output(output: Path) -> None:
    for ancestor in (output, *output.parents):
        if ancestor.exists() and (
            ancestor.is_symlink()
            or getattr(ancestor.stat(), "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            raise ValueError("Worker dependency output must not traverse a symlink or junction")


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
        raise ValueError(
            "Installed versions differ from Worker lock: " + ", ".join(mismatched)
        )
    return installed


def reject_native_extensions(output: Path) -> None:
    for path in output.rglob("*"):
        if path.is_file() and path.suffix.lower() in _NATIVE_SUFFIXES:
            raise ValueError(
                "Pyodide Worker dependency contains a native extension: "
                + path.relative_to(output).as_posix()
            )


def generate_runtime(app_root: Path = APP_ROOT) -> dict:
    output = app_root / RUNTIME_DIRECTORY
    if output.resolve().parent != app_root.resolve() or output.is_symlink():
        raise ValueError("Generated runtime must stay inside the application root")
    if output.exists():
        marker = output / RUNTIME_MARKER
        if not marker.is_file() or json.loads(marker.read_text()).get("owner") != (
            "document-parser-worker-src-v1"
        ):
            raise ValueError("Refusing to replace an unmarked generated runtime directory")
        for path in output.rglob("*"):
            if path.is_symlink() or getattr(
                path.stat(), "st_file_attributes", 0
            ) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                raise ValueError("Generated runtime must not contain symlinks or junctions")
        shutil.rmtree(output)
    output.mkdir()
    hashes = {}
    for name in RUNTIME_FILES:
        source = app_root / name
        target = output / name
        shutil.copy2(source, target)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if digest != hashlib.sha256(target.read_bytes()).hexdigest():
            raise ValueError("Generated runtime differs from canonical source")
        hashes[name] = digest
    (output / RUNTIME_MARKER).write_text(
        json.dumps({"owner": "document-parser-worker-src-v1", "files": hashes}, indent=2)
    )
    return {
        "runtime": str(output),
        "byte_identical": True,
        "source_file_count": len(hashes),
    }


def stage_local_packages(lock_path: Path, staging: Path) -> Path:
    """Build path dependencies from copies so a local build cannot alter the repo."""

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
    require_fresh_output(output)
    output.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PROJECT_ROOT"] = str(lock_path.parent)
    staging = Path(tempfile.mkdtemp(prefix=".document-parser-build-", dir=output.parent))
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
    reject_native_extensions(output)
    (output / "pyvenv.cfg").touch()
    return {
        "status": "PASS",
        "platform": "wasm32-pyodide2025",
        "pure_python": True,
        "lock_sha256": hashlib.sha256(locked_bytes).hexdigest(),
        "locked_package_count": len(versions),
        "installed_packages": installed,
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
