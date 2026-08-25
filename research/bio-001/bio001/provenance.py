from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REQUIRED_MANIFEST_FIELDS = (
    "dataset_name",
    "upstream_url",
    "data_license",
    "permitted_use",
    "redistribution_allowed",
    "version",
    "fingerprint",
)


def load_manifest(path: Path) -> dict[str, Any]:
    """Load only evidence-ready dataset provenance metadata."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    missing = [field for field in REQUIRED_MANIFEST_FIELDS if field not in payload]
    if missing:
        raise ValueError(f"dataset manifest missing fields: {', '.join(missing)}")

    for field in REQUIRED_MANIFEST_FIELDS:
        if field == "redistribution_allowed":
            if not isinstance(payload[field], bool):
                raise ValueError("redistribution_allowed must be boolean")
            continue
        value = str(payload[field]).strip()
        if not value or value.upper() in {"UNKNOWN", "TBD", "TODO"}:
            raise ValueError(f"dataset manifest field {field!r} is not evidence-ready")

    upstream = str(payload["upstream_url"])
    if not upstream.startswith(("https://", "http://")):
        raise ValueError("upstream_url must identify the external source")
    return payload
