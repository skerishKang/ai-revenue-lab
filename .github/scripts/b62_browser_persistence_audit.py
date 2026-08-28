from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = ROOT / "apps" / "padiem-chat" / "static"
SCAN_SUFFIXES = {".html", ".js"}

FORBIDDEN = {
    "localStorage": re.compile(r"\blocalStorage\b"),
    "sessionStorage": re.compile(r"\bsessionStorage\b"),
    "indexedDB": re.compile(r"\bindexedDB\b"),
    "document.cookie": re.compile(r"\bdocument\s*\.\s*cookie\b"),
    "cookieStore": re.compile(r"\bcookieStore\b"),
    "serviceWorker": re.compile(r"\bnavigator\s*\.\s*serviceWorker\b|\bServiceWorkerRegistration\b"),
    "CacheStorage": re.compile(
        r"\bCacheStorage\b|\b(?:window\s*\.\s*)?caches\s*\.\s*(?:open|put|match|delete|keys)\s*\("
    ),
}


def _files() -> list[Path]:
    return sorted(
        path
        for path in STATIC_ROOT.rglob("*")
        if path.is_file() and path.suffix.lower() in SCAN_SUFFIXES
    )


def _line_number(text: str, start: int) -> int:
    return text.count("\n", 0, start) + 1


def main() -> None:
    if not STATIC_ROOT.is_dir():
        raise SystemExit(f"missing B62 static root: {STATIC_ROOT.relative_to(ROOT)}")

    files = _files()
    if not files:
        raise SystemExit("no B62 static HTML/JS files found")

    violations: list[str] = []
    counts = {name: 0 for name in FORBIDDEN}

    for path in files:
        relative = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")

        for name, pattern in FORBIDDEN.items():
            for match in pattern.finditer(text):
                counts[name] += 1
                line = _line_number(text, match.start())
                violations.append(f"{relative}:{line}: forbidden browser persistence primitive: {name}")

    if violations:
        raise SystemExit(
            "B62 browser persistence privacy audit FAILED:\n- " + "\n- ".join(violations)
        )

    print("B62 browser persistence privacy audit: PASS")
    print(f"scanned_files={len(files)}")
    for name in sorted(counts):
        print(f"{name}=0")
    print("server_side_D1_persistence=outside_this_gate")
    print("product_source_mutation=0")


if __name__ == "__main__":
    main()
