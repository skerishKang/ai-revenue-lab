#!/usr/bin/env python3
"""Single authority for how a PADIEM app connects to the existing platform.

An app here means an independently entered product surface (the 의원3종 entry is the
first): it owns its own work logic and screens, and it reaches PADIEM's existing
authentication, AI execution and project-file storage through the routes that
already serve Chat today. It does not get a second login, a second model router or
a second store.

This module is that boundary in one place, so an app, a reviewer and CI read the
same numbers instead of each keeping a copy. It lives under `.github` on purpose:
cross-product operational machinery belongs to the repository operations layer
(docs/architecture/PADIEM_AI_CAPABILITY_OWNERSHIP_REGISTRY_v1.md, IP-CONTROL
section), which also fixes `NEW_PYTHON_PACKAGE_FOR_DEPLOYMENT_RUNTIME = NO`.

`check` reads the real source and refuses on drift; it never mutates anything.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]

CHAT = ROOT / "apps/padiem-chat"
REQUEST_CONTRACT = CHAT / "app/request_contract.py"
CHAT_ROUTES = CHAT / "app/chat_routes.py"
APP_FACTORY = CHAT / "app/app_factory.py"
HISTORY = CHAT / "app/history.py"
ORIGIN_GUARD = CHAT / "app/same_origin_guard.py"
PROJECT_FILE_ROUTES = CHAT / "app/project_file_routes.py"
PROJECT_FILES = CHAT / "app/project_files.py"
B14_PROOF = CHAT / "app/b14_service_proof.py"
WRANGLER = CHAT / "wrangler.toml"
DOCUMENT_NORMALIZATION = ROOT / "packages/padiem-ai-core/padiem_ai_core/document_normalization.py"
IDENTITY_AUTHORITY = ROOT / "packages/padiem-control-plane/identity_authority_worker.py"

#: The only platform routes an app may call. `/api/chat` is the AI lane: B14
#: routing, the model policy and the UsageGate all stay behind it.
PLATFORM_ROUTES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("auth", ("GET",), "/api/auth/status"),
    ("generate", ("POST",), "/api/chat"),
    ("projects", ("GET", "POST"), "/api/projects"),
    ("files", ("GET", "POST"), "/api/projects/{project_id}/files"),
    ("file_detail", ("GET", "DELETE"), "/api/projects/{project_id}/files/{file_id}"),
    ("file_original", ("GET",), "/api/projects/{project_id}/files/{file_id}/original"),
)

#: Work identifiers accepted on the AI lane. Each is a routing label only: it lets
#: a declared request skip the shared native-calendar branch, which classifies a
#: second time inside `try_native_calendar_chat`, and it grants no identity, tier,
#: entitlement or tool scope. A new app adds its identifiers here and to
#: `_UTIL_SCOPES` in the same change; an unknown identifier is refused before any
#: model call, so an app cannot widen the set at runtime.
WORK_SCOPES = frozenset({"speech", "sns", "meeting"})

#: What the existing project-file contract accepts and enforces for an app.
STORED_TEXT_MEDIA = frozenset({"text/plain", "text/markdown", "text/csv", "application/json"})
STORED_IMAGE_MEDIA = frozenset({"image/png", "image/jpeg", "image/webp"})
MAX_STORED_BODY_BYTES = 160_000
MAX_STORED_CONTENT_CHARS = 40_000

#: Canonical identity products the Control Plane admits today. An app that ever
#: needs its own canonical product id must change that allowlist and its
#: Production environment together; recording the current set here is what keeps
#: an app from quietly assuming such an id exists.
IDENTITY_PRODUCTS = frozenset({"b62", "b54-padiem-claw"})

#: Restated in the contract document; kept here so a reader cannot mistake an
#: app-side convenience for a new authority.
FORBIDDEN = (
    "a second session, login or token scheme",
    "forwarding a browser Origin to satisfy the same-origin guard",
    "a direct B14 dispatch without the service proof B14 requires",
    "a new store, table, bucket or Business number",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _quoted_set(text: str) -> frozenset[str]:
    return frozenset(value.strip().strip("\"'") for value in text.split(",") if value.strip())


def _assigned_int(source: str, name: str) -> int | None:
    match = re.search(rf"^{name} = ([0-9_]+)", source, re.M)
    return None if match is None else int(match.group(1).replace("_", ""))


def _registered_methods(path: str) -> Iterable[str]:
    for line in _read(APP_FACTORY).splitlines():
        if f'Route("{path}",' in line:
            return re.findall(r'"([A-Z]+)"', line.split("Route(", 1)[1])
    return ()


def _util_scopes() -> frozenset[str] | None:
    match = re.search(r"_UTIL_SCOPES = frozenset\(\{([^}]*)\}\)", _read(REQUEST_CONTRACT))
    return None if match is None else _quoted_set(match.group(1))


def findings() -> list[str]:
    """Drift codes, empty when the platform still offers what this contract claims."""

    drift: list[str] = []

    for name, methods, path in PLATFORM_ROUTES:
        registered = set(_registered_methods(path))
        if not registered or not set(methods) <= registered:
            drift.append(f"PLATFORM_ROUTE_{name.upper()}_MISSING")

    if _util_scopes() != WORK_SCOPES:
        drift.append("WORK_SCOPE_AUTHORITY_DRIFT")
    if 'raise BrowserRequestError("유틸 업무 식별자가 올바르지 않습니다.")' not in _read(REQUEST_CONTRACT):
        drift.append("WORK_SCOPE_NOT_REFUSED")
    routes = _read(CHAT_ROUTES)
    if "declared_util_scope(raw)" not in routes or "util_scope is None" not in routes:
        drift.append("CALENDAR_BRANCH_NOT_GUARDED")

    guard = _read(ORIGIN_GUARD)
    if "Only ``Settings.public_base_url`` is consulted" not in guard:
        # The expected Origin comes from reviewed server config only. A bridge
        # that forwards a caller's Origin would empty this guard.
        drift.append("ORIGIN_AUTHORITY_DRIFT")
    if "**B — read-only (GET/HEAD):** out of scope" not in guard:
        drift.append("ORIGIN_GUARD_CLASS_B_UNDOCUMENTED")

    history = _read(HISTORY)
    projected = re.search(r"def public_dict\(self\)[^\n]*\n\s+return (\{[^}]*\})", history)
    fields = set() if projected is None else set(re.findall(r'"([a-z_]+)":', projected.group(1)))
    if fields != {"email", "name", "picture"}:
        # The session read keeps not carrying a user id. That is why an app cannot
        # trade this route for identity, and why a separate origin is stopped by
        # the host-only cookie rather than by this endpoint.
        drift.append("AUTH_STATUS_PROJECTION_CHANGED")

    body_limit = _assigned_int(_read(PROJECT_FILE_ROUTES), "MAX_PROJECT_FILE_BODY_BYTES")
    char_limit = _assigned_int(_read(PROJECT_FILES), "PROJECT_FILE_MAX_CONTENT_CHARS")
    if body_limit != MAX_STORED_BODY_BYTES:
        drift.append("STORED_BODY_LIMIT_DRIFT")
    if char_limit != MAX_STORED_CONTENT_CHARS:
        drift.append("STORED_CHARS_LIMIT_DRIFT")
    if set(re.findall(r'"(image/[a-z]+)"', _read(PROJECT_FILES))) != STORED_IMAGE_MEDIA:
        drift.append("STORED_IMAGE_MEDIA_DRIFT")
    normalization = _read(DOCUMENT_NORMALIZATION)
    for media in sorted(STORED_TEXT_MEDIA):
        if f'"{media}"' not in normalization:
            drift.append(f"STORED_TEXT_MEDIA_{media.rsplit('/', 1)[-1].upper()}_UNAVAILABLE")

    proof = _read(B14_PROOF)
    if "X-Padiem-B14-Proof" not in proof or "HMAC-SHA256" not in proof:
        drift.append("B14_SERVICE_PROOF_AUTHORITY_DRIFT")
    wrangler = _read(WRANGLER)
    if 'binding = "B14_SERVICE"' not in wrangler or "PADIEM_B14_SERVICE_PROOF_SECRET" not in wrangler:
        drift.append("B14_LANE_BINDING_DRIFT")

    allowed = re.search(
        r"_ALLOWED_PRODUCTS: frozenset\[str\] = frozenset\(\{([^}]*)\}\)", _read(IDENTITY_AUTHORITY)
    )
    if allowed is None or _quoted_set(allowed.group(1)) != IDENTITY_PRODUCTS:
        drift.append("IDENTITY_PRODUCT_ALLOWLIST_DRIFT")

    return drift


def summary() -> dict[str, object]:
    return {
        "platform_routes": [f"{'|'.join(methods)} {path}" for _name, methods, path in PLATFORM_ROUTES],
        "work_scopes": sorted(WORK_SCOPES),
        "stored_text_media": sorted(STORED_TEXT_MEDIA),
        "stored_image_media": sorted(STORED_IMAGE_MEDIA),
        "max_stored_body_bytes": MAX_STORED_BODY_BYTES,
        "max_stored_content_chars": MAX_STORED_CONTENT_CHARS,
        "identity_products": sorted(IDENTITY_PRODUCTS),
        "forbidden": list(FORBIDDEN),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("check", "describe"), nargs="?", default="check")
    args = parser.parse_args(argv)

    if args.command == "describe":
        print(json.dumps(summary(), ensure_ascii=False, indent=2))
        return 0

    drift = findings()
    if drift:
        print("PADIEM_APPS_CONTRACT=DRIFT:" + ",".join(sorted(drift)))
        return 1
    print("PADIEM_APPS_CONTRACT=EXACT")
    print(f"PADIEM_APPS_CONTRACT_ROUTES={len(PLATFORM_ROUTES)}")
    print("PADIEM_APPS_CONTRACT_WORK_SCOPES=" + ",".join(sorted(WORK_SCOPES)))
    print("PRODUCTION_MUTATION=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
