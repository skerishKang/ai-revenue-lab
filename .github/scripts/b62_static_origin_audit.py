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
# Limited to reviewed #4647 media upload code, not a global provider allowlist.
MEETING_DIRECT_DRIVE_HOSTS = {
    "apps/padiem-chat/static/meeting-drive-upload.js": frozenset({"www.googleapis.com"}),
    "apps/padiem-chat/static/meeting-capture.js": frozenset({"drive.google.com"}),
}
# #5108 admin navigation only: the existing B66 Pages admin origin is reached
# from the total-admin hub. One reviewed config file, never a global allowlist.
ADMIN_HUB_NAVIGATION_HOSTS = {
    "apps/padiem-chat/static/admin-config.js": frozenset({"quick-quote-kr.pages.dev"}),
}

# C10 owner decision: the Drive OFF message links to Google Account security so the
# user can revoke the grant where revocation actually lives. Navigation only, one file.
DRIVE_REVOKE_NAVIGATION_HOSTS = {
    "apps/padiem-chat/static/claw-connection-chips.js": frozenset({"myaccount.google.com"}),
}


# Explicit user-initiated source/license navigation only on the OSS notice.
# The full URLs, not their hosts, are permitted: no new network dependencies.
LICENSE_NOTICE_PATH = "apps/padiem-chat/static/third-party-licenses.html"
LICENSE_NOTICE_URLS = frozenset({
    "https://github.com/NousResearch/hermes-agent/blob/9a76ac8e4f612c081e12008923893077f10f2ec7/tools/tool_output_truncate.py",
    "https://github.com/pymupdf/PyMuPDF",
    "https://github.com/skerishKang/ai-revenue-lab/tree/main/apps/b66-pdf-renderer",
    "https://www.gnu.org/licenses/agpl-3.0.html",
    "https://github.com/anomalyco/opencode",
})


def license_notice_url_allowed(relative: str, url: str) -> bool:
    return relative == LICENSE_NOTICE_PATH and url in LICENSE_NOTICE_URLS


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
            feature_hosts = MEETING_DIRECT_DRIVE_HOSTS.get(relative.as_posix(), frozenset())
            feature_hosts |= ADMIN_HUB_NAVIGATION_HOSTS.get(relative.as_posix(), frozenset())
            feature_hosts |= DRIVE_REVOKE_NAVIGATION_HOSTS.get(relative.as_posix(), frozenset())
            if (host not in ALLOWED_LITERAL_HTTP_HOSTS and host not in feature_hosts
                    and not license_notice_url_allowed(relative.as_posix(), url)):
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
