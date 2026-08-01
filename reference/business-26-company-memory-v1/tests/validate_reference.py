from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "styles.css").read_text(encoding="utf-8")
JS = (ROOT / "app.js").read_text(encoding="utf-8")
VERSION = "company-memory-20260728-1"

required_files = [
    "README.md", "REFERENCE_NOTES.md", "IMAGE_SOURCES.md", "MOTION_SPEC.md", "VALIDATION.md",
    "index.html", "styles.css", "app.js", "states/state-contract.json",
    "assets/images/warehouse-scene.svg", "assets/images/prototype-notebook.svg",
    "assets/images/contract-excerpt.svg", "assets/images/incident-memo.svg",
    "assets/images/blueprint-lineage.svg", "assets/images/witness-strip.svg",
    "assets/images/pause-decision.svg", "assets/images/successor-note.svg",
]
required_states = ["cover", "chronology", "thread", "lineage", "witnesses", "reconstruction", "mobile"]
required_statuses = ["당시 기록", "나중 회고", "확인된 사실", "편집상 추론", "충돌 설명", "누락 증거", "이후 결과"]
forbidden_runtime = ["http://", "https://", "//cdn", "fetch(", "XMLHttpRequest", "WebSocket", "EventSource"]
errors: list[str] = []

for relative in required_files:
    if not (ROOT / relative).is_file():
        errors.append(f"missing file: {relative}")

for state in required_states:
    if f'data-state="{state}"' not in HTML:
        errors.append(f"missing visual state: {state}")
    if f'data-state-target="{state}"' not in HTML:
        errors.append(f"missing state control: {state}")

if len(re.findall(r'data-state="[^"]+"', HTML)) != 7:
    errors.append("visual state count must equal seven")

for status in required_statuses:
    if status not in HTML:
        errors.append(f"missing source status: {status}")

if f"styles.css?v={VERSION}" not in HTML or f"app.js?v={VERSION}" not in HTML:
    errors.append("deterministic asset version missing")
if VERSION not in JS:
    errors.append("runtime version constant missing")
if "prefers-reduced-motion: reduce" not in CSS:
    errors.append("reduced-motion media query missing")
if "animationend" not in JS or "human-review" not in JS:
    errors.append("human review completion source missing")
if "is-running', 'is-complete" not in JS:
    errors.append("previous complete state is not cleared on replay")

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

manifest = (ROOT / "IMAGE_SOURCES.md").read_text(encoding="utf-8")
for image in sorted((ROOT / "assets/images").glob("*.svg")):
    relative = image.relative_to(ROOT).as_posix()
    if relative not in manifest:
        errors.append(f"undocumented image: {relative}")

result = {
    "status": "pass" if not errors else "fail",
    "version": VERSION,
    "required_states": required_states,
    "source_statuses": required_statuses,
    "local_references": len(local_refs),
    "errors": errors,
}
print(json.dumps(result, ensure_ascii=False, indent=2))
if errors:
    raise SystemExit(1)
