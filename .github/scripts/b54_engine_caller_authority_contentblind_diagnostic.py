#!/usr/bin/env python3
"""Content-blind diagnostic CLI for the Engine caller-authority composition.

The #2439 investigation proved the served Engine code is overlay-capable, the
custom domain reaches the Engine worker directly, and the overlay wiring and
credential source are consistent. The only surviving 401 explanations fail
inside ``identity_enforcement._build_registry_authority_from_env`` before any
caller selection: a malformed V1 base, or a base that already contains the
overlay caller id (``duplicate_service_caller``). Both map to the same
``service_authentication_failed`` response and are invisible to NAME/TYPE
read-only evidence.

The Cloudflare control plane never returns ``secret_text`` plaintext, so the
authoritative home of this classification is the Engine runtime itself:
``apps/padiem-ai-engine/app/authority_diagnostic.py`` answers the six closed
facts behind a token-gated internal route where the registry payloads
legitimately exist as environment bindings. This CLI delegates to that exact
production module (imported under its production names, parsers and all) so an
operator who already lawfully holds the two payloads locally can reproduce the
same classification offline. It emits exactly the approved closed facts:

    BASE_PARSE=OK|INVALID
    OVERLAY_PARSE=OK|INVALID
    BASE_CONTAINS_B54_KAGENT=YES|NO
    DUPLICATE_CALLER_ID=YES|NO
    BASE_CALLER_COUNT=<bounded integer>
    OVERLAY_CALLER_ID_MATCH=YES|NO

The scan never surfaces any credential, credential hash, credential length,
allowed app id, unrelated caller id, raw JSON, or derived fingerprint: only
the six fields and the fixed safety markers are ever printed.

Exit codes: 0 when a classification was produced (INVALID/YES/NO results are
valid diagnostic findings), 2 on usage or internal faults. Errors are printed
as fixed strings only; exception text is never propagated.
"""

from __future__ import annotations

import importlib
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_engine_identity_modules():
    """Import the production identity modules under their production names.

    The Engine ``app`` package ``__init__`` pulls in ``padiem_ai_core``, which
    is not installed for CI gate runners. A stub parent package keeps the
    production import names (``app.service_identity``,
    ``app.identity_enforcement``, ``app.authority_diagnostic``) intact while
    bypassing ``__init__`` entirely, so this CLI executes the verbatim
    production classifier that the runtime diagnostic route uses.
    """
    if "app" not in sys.modules:
        package = types.ModuleType("app")
        package.__path__ = [str(ROOT / "apps" / "padiem-ai-engine" / "app")]  # type: ignore[attr-defined]
        sys.modules["app"] = package
    service_identity = importlib.import_module("app.service_identity")
    identity_enforcement = importlib.import_module("app.identity_enforcement")
    authority_diagnostic = importlib.import_module("app.authority_diagnostic")
    return service_identity, identity_enforcement, authority_diagnostic


_service_identity, _identity_enforcement, _authority_diagnostic = (
    _load_engine_identity_modules()
)

CALLER_REGISTRY_V1_ENV = _identity_enforcement.CALLER_REGISTRY_V1_ENV
CALLER_REGISTRY_V1_OVERLAY_ENV = _identity_enforcement.CALLER_REGISTRY_V1_OVERLAY_ENV
parse_caller_registry_v1 = _identity_enforcement.parse_caller_registry_v1
parse_caller_registry_v1_overlay = _identity_enforcement.parse_caller_registry_v1_overlay
MAX_ENGINE_CALLERS = _service_identity.MAX_ENGINE_CALLERS
EXPECTED_OVERLAY_CALLER_ID = _authority_diagnostic.EXPECTED_OVERLAY_CALLER_ID

STATUS_MARKERS = (
    ("B54_ENGINE_AUTHORITY_CONTENTBLIND", ("PASS",)),
    ("SECRET_VALUE_OUTPUT", ("0",)),
    ("RAW_REGISTRY_JSON_OUTPUT", ("0",)),
    ("CLOUDFLARE_MUTATION", ("0",)),
    ("PRODUCTION_MUTATION", ("0",)),
)

CLOSED_FIELDS = _authority_diagnostic.CLOSED_FIELDS


def diagnose(base_raw: str | None, overlay_raw: str | None) -> dict[str, str]:
    """Delegate to the production runtime classifier (single source of truth)."""
    return dict(
        _authority_diagnostic.classify_authority_payloads(base_raw, overlay_raw)
    )


def render(fields: dict[str, str]) -> str:
    """Render only the approved fields and fixed safety markers."""
    lines = [f"{name}={fields[name]}" for name in CLOSED_FIELDS]
    lines.append("B54_ENGINE_AUTHORITY_CONTENTBLIND=PASS")
    lines.extend(f"{name}={value}" for name, (value,) in STATUS_MARKERS[1:])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args:
        print(
            "usage: b54_engine_caller_authority_contentblind_diagnostic.py "
            "(reads registry payloads from the Engine environment variable names)",
            file=sys.stderr,
        )
        return 2
    base_raw = os.environ.get(CALLER_REGISTRY_V1_ENV)
    overlay_raw = os.environ.get(CALLER_REGISTRY_V1_OVERLAY_ENV)
    if base_raw is None and overlay_raw is None:
        print(
            "B54_ENGINE_AUTHORITY_CONTENTBLIND=FAIL "
            "REASON=no_registry_payloads_in_environment",
            file=sys.stderr,
        )
        return 2
    try:
        fields = diagnose(base_raw, overlay_raw)
    except Exception:
        print(
            "B54_ENGINE_AUTHORITY_CONTENTBLIND=FAIL REASON=internal_fault",
            file=sys.stderr,
        )
        return 2
    print(render(fields))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
