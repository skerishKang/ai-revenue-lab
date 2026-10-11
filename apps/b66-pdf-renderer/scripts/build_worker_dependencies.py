from __future__ import annotations
import hashlib, importlib.metadata, os, re, shutil, subprocess, tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "pylock.toml"
OUTPUT = ROOT / "python_modules"
RUNTIME = ROOT / ".worker-src"
RUNTIME_FILES = ("worker.py", "bundle.py", "renderer.py")
VERSION = "1.26.3"
WHEEL = "https://cdn.jsdelivr.net/pyodide/v0.28.3/full/pymupdf-1.26.3-cp313-none-pyodide_2025_0_wasm32.whl"
SHA = "8b343b6584098287e02c5131369341267f54461b0f2a233deec1a31dfe47693c"

def main() -> None:
    lock = tomllib.loads(LOCK.read_text(encoding="utf-8"))
    pkgs = lock.get("packages", [])
    if len(pkgs) != 1 or pkgs[0].get("name") != "pymupdf" or pkgs[0].get("version") != VERSION:
        raise SystemExit("unexpected PDF worker lock")
    wheels = pkgs[0].get("wheels", [])
    if not any(w.get("url") == WHEEL and w.get("hashes", {}).get("sha256") == SHA for w in wheels):
        raise SystemExit("reviewed PyMuPDF WASM wheel missing")
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    subprocess.run([
        "uv", "pip", "install",
        "--python-platform", "wasm32-pyodide2025",
        "--python-version", "3.13",
        "--target", str(OUTPUT),
        "--requirements", str(LOCK),
        "--preview-features", "pylock",
        "--only-binary", "pymupdf",
        "--link-mode", "copy",
    ], cwd=ROOT, check=True)
    wheel_meta = OUTPUT / f"pymupdf-{VERSION}.dist-info" / "WHEEL"
    if "Tag: cp313-none-pyodide_2025_0_wasm32" not in wheel_meta.read_text(encoding="utf-8"):
        raise SystemExit("native wheel rejected")
    with (OUTPUT / "pymupdf" / "_mupdf.so").open("rb") as fh:
        if fh.read(4) != b"\x00asm":
            raise SystemExit("WASM binary missing")
    if RUNTIME.exists():
        shutil.rmtree(RUNTIME)
    RUNTIME.mkdir()
    for name in RUNTIME_FILES:
        source = ROOT / name
        target = RUNTIME / name
        shutil.copy2(source, target)
        if hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(target.read_bytes()).digest():
            raise SystemExit("runtime source copy mismatch")
    total = sum(p.stat().st_size for p in OUTPUT.rglob("*") if p.is_file())
    print(f"PDF_WORKER_VENDOR_BYTES={total}")
    print("PDF_WORKER_VENDOR=PASS")
    print("PDF_WORKER_RUNTIME_COPY=PASS")

if __name__ == "__main__":
    main()
