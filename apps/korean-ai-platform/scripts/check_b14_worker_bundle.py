#!/usr/bin/env python3
"""Check the *emitted* Wrangler package, not merely wrangler.toml or source files.

Only a local dry-run artifact is mutated during the negative control.
No Cloudflare credentials, deployments or external model calls are involved.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def _subprocess_registry_probe(bundle_dir: Path, should_exist: bool) -> None:
    # A fresh Python process and bundle-first PYTHONPATH ensure that no
    # source-tree module already cached in sys.modules can mask a missing file.
    script = r"""
from pathlib import Path
from app.pilot.model_registry_file import ModelRegistryError, REGISTRY_PATH, read_registry
expected = Path.cwd() / "app" / "pilot" / "b14_models.json"
assert REGISTRY_PATH.resolve() == expected.resolve(), (REGISTRY_PATH, expected)
try:
    data = read_registry()
except ModelRegistryError:
    assert not SHOULD_EXIST, "JSON was present but registry could not load"
else:
    assert SHOULD_EXIST, "missing JSON silently loaded from elsewhere"
    assert len(data["models"]) == 11, len(data["models"])
    assert len(data["providers"]) == 7, len(data["providers"])
"""
    script = "SHOULD_EXIST = " + repr(should_exist) + "\n" + script
    env = os.environ.copy()
    env["PYTHONPATH"] = str(bundle_dir)
    env["PYTHONUTF8"] = "1"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=bundle_dir,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=25,
    )
    if completed.returncode:
        raise AssertionError(
            "bundle loader test failed: "
            + (completed.stderr or completed.stdout)[-1800:]
        )


def verify(source: Path, bundle_dir: Path) -> None:
    source = source.resolve()
    bundle_dir = bundle_dir.resolve()
    packaged = bundle_dir / "app" / "pilot" / "b14_models.json"
    assert (bundle_dir / "worker.py").is_file(), "entrypoint not packaged"
    assert (
        bundle_dir / "app" / "pilot" / "model_registry_file.py"
    ).is_file(), "registry loader not packaged"
    assert packaged.is_file(), "canonical JSON missing in Wrangler artifact"
    before = source.read_bytes()
    built = packaged.read_bytes()
    assert built == before, "bundled JSON differs from canonical source"
    registry = json.loads(built)
    assert len(registry["models"]) == 11
    assert len(registry["providers"]) == 7
    assert len({m["id"] for m in registry["models"]}) == 11
    print(f"B14_BUNDLE_JSON=PASS size={len(built)} sha256={hashlib.sha256(built).hexdigest()}")
    _subprocess_registry_probe(bundle_dir, should_exist=True)
    print("B14_BUNDLE_IMPORT=PASS")

    missing = packaged.with_name("b14_models.json.negative-removed")
    assert not missing.exists()
    packaged.rename(missing)
    try:
        _subprocess_registry_probe(bundle_dir, should_exist=False)
        print("B14_BUNDLE_MISSING_FAIL_CLOSED=PASS")
    finally:
        missing.rename(packaged)
    assert packaged.read_bytes() == before, "negative control failed to restore"
    print("B14_BUNDLE_RESTORE=PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--bundle-dir", required=True, type=Path)
    args = parser.parse_args()
    verify(args.source, args.bundle_dir)
