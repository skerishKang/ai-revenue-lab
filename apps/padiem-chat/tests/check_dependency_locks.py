from __future__ import annotations

import argparse
import importlib.metadata
import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UV_LOCK = ROOT / "uv.lock"
PY_LOCK = ROOT / "pylock.toml"
VENDOR = ROOT / "python_modules"

MACHINE_PATH_PATTERNS = (
    re.compile(r"/home/[^/]+/"),
    re.compile(r"/Users/[^/]+/"),
    re.compile(r"[A-Za-z]:\\"),
)


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _read_uv_versions() -> dict[str, str]:
    data = tomllib.loads(UV_LOCK.read_text(encoding="utf-8"))
    versions: dict[str, str] = {}
    for package in data.get("package", []):
        name = package.get("name")
        version = package.get("version")
        if isinstance(name, str) and isinstance(version, str):
            versions[_normalize(name)] = version
    return versions


def _read_pylock_versions() -> dict[str, str]:
    data = tomllib.loads(PY_LOCK.read_text(encoding="utf-8"))
    versions: dict[str, str] = {}
    for package in data.get("packages", []):
        name = package.get("name")
        version = package.get("version")
        if isinstance(name, str) and isinstance(version, str):
            versions[_normalize(name)] = version
    return versions


def _assert_machine_independent() -> None:
    for path in (UV_LOCK, PY_LOCK):
        text = path.read_text(encoding="utf-8")
        for pattern in MACHINE_PATH_PATTERNS:
            if pattern.search(text):
                raise AssertionError(
                    f"{path.name} contains a machine-specific absolute path matching {pattern.pattern!r}"
                )


def _installed_host_versions() -> dict[str, str]:
    result: dict[str, str] = {}
    for dist in importlib.metadata.distributions():
        name = dist.metadata.get("Name")
        if name:
            result[_normalize(name)] = dist.version
    return result


def _installed_vendor_versions() -> dict[str, str]:
    result: dict[str, str] = {}
    for dist in importlib.metadata.distributions(path=[str(VENDOR)]):
        name = dist.metadata.get("Name")
        if name:
            result[_normalize(name)] = dist.version
    return result


def _assert_versions(
    *,
    authority: dict[str, str],
    installed: dict[str, str],
    packages: tuple[str, ...],
    label: str,
) -> None:
    failures: list[str] = []
    for package in packages:
        key = _normalize(package)
        locked = authority.get(key)
        actual = installed.get(key)
        if locked is None:
            failures.append(f"{package}: missing from lock")
        elif actual is None:
            failures.append(f"{package}: missing from {label}")
        elif actual != locked:
            failures.append(f"{package}: lock={locked} {label}={actual}")
    if failures:
        raise AssertionError("; ".join(failures))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("host", "vendor", "all"), default="all")
    args = parser.parse_args()

    if not UV_LOCK.is_file():
        raise AssertionError("uv.lock is required")
    if not PY_LOCK.is_file():
        raise AssertionError("pylock.toml is required")

    _assert_machine_independent()
    uv_versions = _read_uv_versions()
    py_versions = _read_pylock_versions()

    if args.phase in {"host", "all"}:
        _assert_versions(
            authority=uv_versions,
            installed=_installed_host_versions(),
            packages=("httpx", "httpcore", "workers-py", "workers-runtime-sdk"),
            label="host environment",
        )
        print("HOST_LOCK_CONSISTENCY=PASS")

    if args.phase in {"vendor", "all"}:
        if not VENDOR.is_dir():
            raise AssertionError("python_modules is required after pywrangler sync")
        vendor_versions = _installed_vendor_versions()
        _assert_versions(
            authority=py_versions,
            installed=vendor_versions,
            packages=("httpx", "workers-runtime-sdk"),
            label="python_modules",
        )

        pylock_httpcore = py_versions.get("httpcore")
        vendor_httpcore = vendor_versions.get("httpcore")
        if pylock_httpcore is None:
            if vendor_httpcore is not None:
                raise AssertionError(
                    "httpcore is absent from pylock.toml but present in python_modules "
                    f"as {vendor_httpcore}"
                )
            print("WORKER_HTTPCORE=NOT_REQUIRED_BY_PYODIDE_LOCK")
        elif vendor_httpcore != pylock_httpcore:
            raise AssertionError(
                f"httpcore: pylock={pylock_httpcore} python_modules={vendor_httpcore}"
            )

        print("WORKER_LOCK_CONSISTENCY=PASS")


if __name__ == "__main__":
    main()
