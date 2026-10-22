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

# #5015 Android sign-in return: the WebView completes Google in a Custom Tab
# whose cookies never reach it, so the WebView holds the one-time claim secret
# across a page recreation. That is the only persistence this gate may accept,
# in one file, under one reviewed key, through one exact call shape.
HANDOFF_FILE = "apps/padiem-chat/static/app.js"
HANDOFF_DECLARATION = 'const ANDROID_HANDOFF_STORAGE_KEY = "padiem.androidHandoff.v1";'
HANDOFF_USAGE = re.compile(
    r"window\.sessionStorage\.(?:getItem|setItem|removeItem)\(\s*ANDROID_HANDOFF_STORAGE_KEY\b"
)

# #5034 Web Push: the owner decision of 2026-10-23 allows the service worker
# that Web Push requires. Web Push has no alternative -- PushManager.subscribe()
# needs a registered service worker to receive a push -- so the gate keeps every
# other browser-persistence primitive forbidden and accepts exactly ONE reviewed
# client file, under ONE reviewed service-worker path, through a closed set of
# exact call shapes. The service worker itself stores nothing: it holds no
# cache, no storage and no user state, and it is scanned like every other file.
PUSH_CLIENT_FILE = "apps/padiem-chat/static/claw-push.js"
PUSH_CLIENT_DECLARATION = 'const PADIEM_PUSH_SW_PATH = "/push-sw.js";'
PUSH_CLIENT_USAGE = re.compile(
    r"navigator\.serviceWorker\.(?:register\(\s*PADIEM_PUSH_SW_PATH\s*\)|ready\b|getRegistration\(\))"
)
PUSH_SW_FILE = "apps/padiem-chat/static/push-sw.js"


def _line_slice(text: str, start: int) -> tuple[int, str]:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", start)
    if line_end == -1:
        line_end = len(text)
    return text.count("\n", 0, start) + 1, text[line_start:line_end]


def _is_reviewed_handoff(relative: str, text: str, start: int, declaration_count: int) -> bool:
    if relative != HANDOFF_FILE or declaration_count != 1 or HANDOFF_DECLARATION not in text:
        return False
    _line_number, line = _line_slice(text, start)
    return bool(HANDOFF_USAGE.search(line))


def _is_reviewed_push_client(relative: str, text: str, start: int, declaration_count: int) -> bool:
    """#5034: the one reviewed Web Push client, one path, closed call shapes."""

    if relative != PUSH_CLIENT_FILE or declaration_count != 1:
        return False
    if PUSH_CLIENT_DECLARATION not in text:
        return False
    _line_number, line = _line_slice(text, start)
    return bool(PUSH_CLIENT_USAGE.search(line))



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
    handoff_allowances = 0
    push_client_allowances = 0

    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        declarations = text.count(HANDOFF_DECLARATION)
        push_declarations = text.count(PUSH_CLIENT_DECLARATION)

        for name, pattern in FORBIDDEN.items():
            for match in pattern.finditer(text):
                if name == "sessionStorage" and _is_reviewed_handoff(
                    relative, text, match.start(), declarations
                ):
                    handoff_allowances += 1
                    continue
                if name == "serviceWorker" and _is_reviewed_push_client(
                    relative, text, match.start(), push_declarations
                ):
                    push_client_allowances += 1
                    continue
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
    print(f"android_handoff_storage_lines={handoff_allowances}")
    print(f"android_handoff_scope={HANDOFF_FILE}:padiem.androidHandoff.v1")
    print(f"web_push_service_worker_lines={push_client_allowances}")
    print(f"web_push_client_scope={PUSH_CLIENT_FILE}:{PUSH_CLIENT_DECLARATION}")
    print(f"web_push_service_worker={PUSH_SW_FILE}")
    print("server_side_D1_persistence=outside_this_gate")
    print("product_source_mutation=0")


if __name__ == "__main__":
    main()
