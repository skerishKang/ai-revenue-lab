from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = ROOT / "apps" / "padiem-chat" / "static"
SCAN_SUFFIXES = {".html", ".js", ".css"}

PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("innerHTML assignment", re.compile(r"\.innerHTML\s*=")),
    ("outerHTML assignment", re.compile(r"\.outerHTML\s*=")),
    ("insertAdjacentHTML call", re.compile(r"\.insertAdjacentHTML\s*\(")),
    ("document.write call", re.compile(r"\bdocument\.write(?:ln)?\s*\(")),
    ("eval call", re.compile(r"(?<![\w$])eval\s*\(")),
    ("Function constructor", re.compile(r"(?<![\w$])(?:new\s+)?Function\s*\(")),
    ("srcdoc assignment", re.compile(r"\.srcdoc\s*=")),
    (
        "srcdoc setAttribute",
        re.compile(r"\.setAttribute\s*\(\s*['\"]srcdoc['\"]\s*,", re.IGNORECASE),
    ),
    ("javascript URL literal", re.compile(r"javascript\s*:", re.IGNORECASE)),
)


def _files() -> list[Path]:
    return sorted(
        path
        for path in STATIC_ROOT.rglob("*")
        if path.is_file() and path.suffix.lower() in SCAN_SUFFIXES
    )


def main() -> None:
    if not STATIC_ROOT.is_dir():
        raise SystemExit(f"missing B62 static root: {STATIC_ROOT.relative_to(ROOT)}")

    files = _files()
    if not files:
        raise SystemExit("no B62 static HTML/JS/CSS files found")

    violations: list[str] = []
    for path in files:
        relative = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for label, pattern in PATTERNS:
                match = pattern.search(line)
                if match:
                    snippet = line.strip()
                    if len(snippet) > 180:
                        snippet = snippet[:177] + "..."
                    violations.append(
                        f"{relative}:{lineno}: {label}: {snippet}"
                    )

    if violations:
        raise SystemExit(
            "B62 unsafe DOM sink audit FAILED:\n- " + "\n- ".join(violations)
        )

    print("B62 unsafe DOM sink audit: PASS")
    print(f"scanned_files={len(files)}")
    print("unsafe_html_injection_sinks=0")
    print("dynamic_code_execution_sinks=0")
    print("srcdoc_sinks=0")
    print("javascript_url_literals=0")


if __name__ == "__main__":
    main()
