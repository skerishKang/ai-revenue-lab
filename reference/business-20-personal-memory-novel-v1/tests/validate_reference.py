from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "styles.css").read_text(encoding="utf-8")
JS = (ROOT / "app.js").read_text(encoding="utf-8")
VERSION = "memory-novel-20260727-1"

required_files = [
    "README.md", "REFERENCE_NOTES.md", "IMAGE_SOURCES.md", "MOTION_SPEC.md",
    "index.html", "styles.css", "app.js",
    "assets/images/station-winter.svg",
    "assets/images/source-contact-sheet.svg",
    "assets/images/handwritten-note.svg",
    "assets/images/manuscript-proof.svg",
    "assets/images/transformation-map.svg",
]
required_states = ["cover", "source", "draft", "map", "versions", "proof", "mobile"]
required_labels = ["FACT", "INFERENCE", "FICTION", "REDACTED", "AUTHOR APPROVED"]
forbidden_runtime = ["http://", "https://", "//cdn", "fetch(", "XMLHttpRequest", "WebSocket"]

errors: list[str] = []

for relative in required_files:
    if not (ROOT / relative).is_file():
        errors.append(f"missing file: {relative}")

for state in required_states:
    if f'data-state="{state}"' not in HTML:
        errors.append(f"missing visual state: {state}")
    if f'data-state-target="{state}"' not in HTML:
        errors.append(f"missing state control: {state}")

for label in required_labels:
    if label not in HTML:
        errors.append(f"missing truth label: {label}")

if f"styles.css?v={VERSION}" not in HTML:
    errors.append("stylesheet deterministic version query missing")
if f"app.js?v={VERSION}" not in HTML:
    errors.append("script deterministic version query missing")
if VERSION not in JS:
    errors.append("runtime version constant missing")
if "prefers-reduced-motion:reduce" not in CSS.replace(" ", ""):
    errors.append("reduced-motion media query missing")
if "680ms" not in (ROOT / "MOTION_SPEC.md").read_text(encoding="utf-8"):
    errors.append("motion duration evidence missing")

runtime_text = HTML + "\n" + CSS + "\n" + JS
for token in forbidden_runtime:
    if token in runtime_text:
        errors.append(f"external/runtime token present: {token}")

local_refs = re.findall(r'(?:src|href)="([^"?#]+)', HTML)
for ref in local_refs:
    if ref.startswith("#"):
        continue
    if not (ROOT / ref).is_file():
        errors.append(f"missing local reference: {ref}")

image_manifest = (ROOT / "IMAGE_SOURCES.md").read_text(encoding="utf-8")
for image in (ROOT / "assets/images").glob("*.svg"):
    relative = image.relative_to(ROOT).as_posix()
    if relative not in image_manifest:
        errors.append(f"undocumented image: {relative}")

result = {
    "status": "pass" if not errors else "fail",
    "version": VERSION,
    "required_states": required_states,
    "truth_labels": required_labels,
    "local_references": len(local_refs),
    "errors": errors,
}
print(json.dumps(result, ensure_ascii=False, indent=2))
if errors:
    raise SystemExit(1)
