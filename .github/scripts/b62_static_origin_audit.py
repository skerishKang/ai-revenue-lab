from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = ROOT / "apps" / "padiem-chat" / "static"
SCAN_SUFFIXES = {".html", ".css", ".js"}
ALLOWED_LITERAL_HTTP_HOSTS = frozenset({
    "cdn.jsdelivr.net",
    "fonts.googleapis.com",
    "padiem.net",
})
# XML namespace text inside the existing inline data:image SVG. It is an
# identifier, not a network dependency and must not widen the host allowlist.
NON_NETWORK_LITERAL_URLS = frozenset({"http://www.w3.org/2000/svg"})

URL_RE = re.compile(r"https?://[^\s\"'<>)}]+", re.IGNORECASE)


def _files() -> list[Path]:
    return sorted(
        path
        for path in STATIC_ROOT.rglob("*")
        if path.is_file() and path.suffix.lower() in SCAN_SUFFIXES
    )


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def main() -> None:
    if not STATIC_ROOT.is_dir():
        raise SystemExit(f"missing B62 static root: {STATIC_ROOT.relative_to(ROOT)}")

    files = _files()
    if not files:
        raise SystemExit("no B62 static HTML/CSS/JS files found")

    violations: list[str] = []
    seen_hosts: set[str] = set()

    for path in files:
        relative = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")

        for match in URL_RE.finditer(text):
            url = match.group(0).rstrip(".,;]")
            if url in NON_NETWORK_LITERAL_URLS:
                continue
            host = _host(url)
            if not host:
                violations.append(f"{relative}: malformed absolute URL: {url}")
                continue
            seen_hosts.add(host)
            if host not in ALLOWED_LITERAL_HTTP_HOSTS:
                violations.append(f"{relative}: unapproved external host {host}: {url}")

    if violations:
        raise SystemExit(
            "B62 static origin/privacy audit FAILED:\n- " + "\n- ".join(violations)
        )

    expected_hosts = {"cdn.jsdelivr.net", "fonts.googleapis.com", "padiem.net"}
    missing_expected = expected_hosts - seen_hosts
    if missing_expected:
        raise SystemExit(
            "B62 static origin/privacy audit baseline drift: expected reviewed font origins are missing: "
            + ", ".join(sorted(missing_expected))
            + ". If fonts were intentionally self-hosted/removed, update this audit in the same reviewed change."
        )

    print("B62 static origin/privacy audit: PASS")
    print(f"scanned_files={len(files)}")
    print("literal_http_hosts=" + ",".join(sorted(seen_hosts)))
    print("non_network_literal_urls=" + ",".join(sorted(NON_NETWORK_LITERAL_URLS)))
    print("runtime_font_child_host=fonts.gstatic.com (documented downstream only; not literal static source)")
    print("tracker_analytics_provider_origins=0")


if __name__ == "__main__":
    main()
