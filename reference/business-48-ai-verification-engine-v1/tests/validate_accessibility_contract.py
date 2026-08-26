from html.parser import HTMLParser
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "styles/main.css").read_text(encoding="utf-8")
JS = (ROOT / "scripts/review.js").read_text(encoding="utf-8")
MANIFEST = (ROOT / "IMAGE_SOURCES.md").read_text(encoding="utf-8")

STATES = ["cover", "submission", "claims", "checks", "evidence", "decision", "mobile"]
PERSISTENT_BOUNDARIES = [
    "FAILED CHECK",
    "SKIPPED — NOT PASSED",
    "UNAVAILABLE EVIDENCE",
    "STALE EVIDENCE — DO NOT USE",
    "RESIDUAL CONDITION",
    "APPROVAL SCOPE LIMITED",
    "NO UNIVERSAL CERTIFICATION",
    "DEPLOYMENT NOT AUTHORIZED",
]
FORBIDDEN_MEANINGS = [
    "SELF-CHECK — INDEPENDENT VALIDATION",
    "SKIPPED — PASSED",
    "UNAVAILABLE EVIDENCE — PASSED",
    "UNIVERSAL CERTIFICATION GRANTED",
    "MERGE AUTHORIZED",
    "DEPLOYMENT AUTHORIZED",
]


class ContractParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tabs: list[dict[str, str]] = []
        self.panels: list[dict[str, str]] = []
        self.ids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = {key: value or "" for key, value in attrs}
        if data.get("id"):
            self.ids.append(data["id"])
        if data.get("role") == "tab":
            self.tabs.append(data)
        if data.get("role") == "tabpanel":
            self.panels.append(data)


parser = ContractParser()
parser.feed(HTML)

assert len(parser.ids) == len(set(parser.ids)), "all element IDs must be unique"
assert len(parser.tabs) == len(STATES), "exactly seven tabs required"
assert len(parser.panels) == len(STATES), "exactly seven tabpanels required"

for state, tab, panel in zip(STATES, parser.tabs, parser.panels, strict=True):
    expected_tab_id = f"tab-{state}"
    expected_panel_id = f"panel-{state}"
    assert tab.get("data-state-control") == state
    assert tab.get("id") == expected_tab_id
    assert tab.get("aria-controls") == expected_panel_id
    assert panel.get("data-state") == state
    assert panel.get("id") == expected_panel_id
    assert panel.get("aria-labelledby") == expected_tab_id

assert all(label in HTML for label in PERSISTENT_BOUNDARIES)
assert all(HTML.count(label) >= 2 for label in PERSISTENT_BOUNDARIES), (
    "boundaries must remain in both decision and mobile records"
)
assert not any(phrase in HTML for phrase in FORBIDDEN_MEANINGS)
assert "animationend" in JS and "briefComplete" in JS
assert "setTimeout" not in JS
assert re.search(r"briefComplete\s+110ms\s+660ms", CSS)
assert "prefers-reduced-motion:reduce" in CSS
assert not re.search(r'(?:src|href)="https?://|//cdn', HTML + CSS + JS)
assert all(column in MANIFEST for column in [
    "Asset type",
    "Role",
    "Source / ownership",
    "Licence basis",
    "Creation / acquisition date",
    "Intended use",
])

print("ACCESSIBILITY_SOURCE_CONTRACT_PASS")
