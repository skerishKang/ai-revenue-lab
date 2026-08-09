#!/usr/bin/env python3
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
html = (ROOT / "index.html").read_text(encoding="utf-8")
css = (ROOT / "styles/main.css").read_text(encoding="utf-8")
js = (ROOT / "scripts/review.js").read_text(encoding="utf-8")

expected = {"cover", "product", "maker", "neighbour", "season", "kit", "mobile"}
states = set(re.findall(r'data-state="([a-z-]+)"', html))
targets = set(re.findall(r'data-state-target="([a-z-]+)"', html))
external = re.findall(r'(?:src|href)="https?://', html)
assets = [value.split('#', 1)[0] for value in re.findall(r'(?:src|href)="(\./[^"?]+)', html)]
missing = [asset for asset in assets if not (ROOT / asset[2:]).is_file()]
checks = {
    "seven_states": states == expected,
    "seven_controls": targets == expected,
    "local_assets": not missing,
    "no_external_runtime": not external,
    "mobile_media": "@media (max-width: 460px)" in css,
    "reduced_motion": "prefers-reduced-motion: reduce" in css,
    "deterministic_css": "main.css?v=local-shop-magazine-20260728-1" in html,
    "deterministic_js": "review.js?v=local-shop-magazine-20260728-1" in html,
    "animationend_authority": "animationend" in js and "revealQuote" in js,
    "synthetic_disclosure": "모두 합성 자료" in html,
}
for name, passed in checks.items():
    print(f"{'PASS' if passed else 'FAIL'} {name}")
if missing:
    print("missing:", missing)
sys.exit(0 if all(checks.values()) else 1)
