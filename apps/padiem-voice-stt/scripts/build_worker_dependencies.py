"""Assemble the Cloudflare Python Worker source tree for padiem-voice-stt.

This Worker has no third-party runtime dependencies: it uses only the Python
standard library, the Cloudflare ``workers`` runtime module, and the local
``voice_stt_contract`` module. The build therefore only needs to copy the
reviewed runtime files into ``.worker-src`` (wrangler's ``base_dir``) and prove
the copy is byte-identical and dependency-free.

Run with: ``uv run python scripts/build_worker_dependencies.py``
"""

from __future__ import annotations

import ast
import hashlib
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".worker-src"
RUNTIME_FILES = ("worker.py", "voice_stt_contract.py")

#: The only non-stdlib imports the runtime files may use.
ALLOWED_THIRD_PARTY = frozenset({"workers", "voice_stt_contract"})

STDLIB = frozenset(getattr(__import__("sys"), "stdlib_module_names", ()))


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names


def main() -> None:
    for name in RUNTIME_FILES:
        source = ROOT / name
        if not source.is_file():
            raise SystemExit(f"missing runtime file: {name}")

    for name in RUNTIME_FILES:
        imported = _imports(ROOT / name)
        unexpected = imported - STDLIB - ALLOWED_THIRD_PARTY
        if unexpected:
            raise SystemExit(f"unreviewed import in {name}: {sorted(unexpected)}")

    if RUNTIME.exists():
        shutil.rmtree(RUNTIME)
    RUNTIME.mkdir()
    for name in RUNTIME_FILES:
        source = ROOT / name
        target = RUNTIME / name
        shutil.copy2(source, target)
        if hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(target.read_bytes()).digest():
            raise SystemExit("runtime source copy mismatch")

    print("VOICE_STT_RUNTIME_FILES=" + ",".join(RUNTIME_FILES))
    print("VOICE_STT_EXTERNAL_DEPS=0")
    print("VOICE_STT_RUNTIME_COPY=PASS")


if __name__ == "__main__":
    main()
