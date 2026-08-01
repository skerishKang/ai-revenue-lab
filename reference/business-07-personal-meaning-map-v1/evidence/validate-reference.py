from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "personal-meaning-map-20260726-2"
SOURCE_SUFFIXES = {".html", ".css", ".js", ".md", ".py", ".svg", ".json", ".txt"}


def line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def main() -> None:
    sources = sorted(path for path in ROOT.rglob("*") if path.is_file() and path.suffix in SOURCE_SUFFIXES)
    counts = {str(path.relative_to(ROOT)): line_count(path) for path in sources}
    over_limit = {path: count for path, count in counts.items() if count > 500}
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    loaded_assets = re.findall(r'(?:href|src)="([^"]+\.(?:css|js)[^"]*)"', html)
    stale = [asset for asset in loaded_assets if f"?v={VERSION}" not in asset]
    external = re.findall(r'(?:href|src)="(https?://[^"]+)"', html)
    local_refs = re.findall(r'(?:href|src)="(\./[^"]+)"', html)
    normalized_refs = [ref.split('?', 1)[0].removeprefix('./') for ref in local_refs]
    missing_local_assets = [ref for ref in normalized_refs if not (ROOT / ref).is_file()]
    states = re.findall(r'data-review-state="([^"]+)"', html)
    result = {
        "source_line_counts": counts,
        "over_500_lines": over_limit,
        "loaded_css_js": loaded_assets,
        "stale_or_unversioned_css_js": stale,
        "external_runtime_assets": external,
        "local_asset_references": normalized_refs,
        "missing_local_assets": missing_local_assets,
        "states": states,
        "state_count": len(states),
        "pass": not over_limit and not stale and not external and not missing_local_assets and len(states) == 7,
    }
    output = ROOT / "evidence" / "static-validation.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["pass"] else 1)


if __name__ == "__main__":
    main()
