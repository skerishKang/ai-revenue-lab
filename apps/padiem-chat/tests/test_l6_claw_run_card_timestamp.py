"""CLAW2 / L6 — the run card shows a readable instant, not a raw ISO string.

Scope (CLAW2, presentation only): the Claw run-history card printed the exact
value the server stored for ``created_at`` straight at the reader, so every
completed run displayed an ISO-8601 UTC instant such as
``2026-09-19T01:00:00Z`` in its meta line.

The same instant is now rendered in the page's own language and zone, and the
exact stored value is preserved in the element's ``title`` so the record is not
hidden. A value the browser cannot parse is shown exactly as the server sent it
rather than replaced with a guess.

No server file, route, store or contract is touched, and no new locale string is
introduced: the rendering comes from the platform's own ``Intl`` formatter using
the page language the locale module already applies.

Static string assertions alone do not prove behavior, so this file also runs a
Node harness that executes the REAL ``renderClawRunCard`` source with a minimal
DOM shim. The harness proves actual behavior:

- CARD_HIDES_RAW_ISO_INSTANT=PASS
- CARD_KEEPS_EXACT_STORED_VALUE=PASS
- CARD_FOLLOWS_PAGE_LANGUAGE=PASS
- CARD_UNPARSEABLE_VALUE_SHOWN_VERBATIM=PASS
- CARD_ABSENT_VALUE_ADDS_NOTHING=PASS
- CARD_OTHER_FIELDS_UNCHANGED=PASS
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "static/app.js"
ISO_INSTANT = "2026-09-19T01:00:00Z"


def _app() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _card_fn() -> str:
    app = _app()
    start = app.index("  function renderClawRunCard(run) {")
    end = app.index("\n  // Unguarded fetch:", start)
    return app[start:end]


# ── static contracts ───────────────────────────────────────────────────────


def test_meta_line_renders_through_the_instant_helper() -> None:
    fn = _card_fn()
    assert "readableClawInstant(createdAt)" in fn
    # The raw stored field is no longer handed straight to the meta line.
    assert not re.search(r"run\.created_at\s*\]", fn)
    assert "const createdAt = typeof run.created_at === \"string\" ? run.created_at : \"\";" in fn


def test_exact_stored_value_is_preserved() -> None:
    fn = _card_fn()
    assert 'if (createdAt) meta.setAttribute("title", createdAt);' in fn


def test_helper_never_invents_a_value() -> None:
    fn = _card_fn()
    # Unparseable or absent input is returned exactly as received.
    assert "if (Number.isNaN(parsed.getTime())) return value;" in fn
    assert 'if (typeof value !== "string" || !value) return "";' in fn
    # The formatter is the platform's own, keyed to the page language only.
    assert 'dateStyle: "medium", timeStyle: "short"' in fn
    assert "new Intl.DateTimeFormat(instantLanguage" in fn
    # No hardcoded locale-specific date text is added to app.js.
    for line in fn.splitlines():
        assert not any("\uac00" <= ch <= "\ud7a3" for ch in line), line.strip()


def test_page_language_defaults_without_a_document_element() -> None:
    fn = _card_fn()
    # The isolated harnesses used by other guards supply no documentElement.
    assert "document?.documentElement?.lang" in fn


# ── behavioral proof via Node executing the real renderer ──────────────────

_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const app = fs.readFileSync(process.argv[2], "utf8");

const start = app.indexOf("  function renderClawRunCard(run) {");
const end = app.indexOf("\n  // Unguarded fetch:", start);
if (start < 0 || end <= start) throw new Error("real run-card source must be located");
const CARD = app.slice(start, end).trim();

function el(tag) {
  return {
    tag, className: "", textContent: "", dataset: {}, children: [], listeners: {},
    setAttribute(name, value) { this[name] = value; },
    append(...items) { this.children.push(...items); },
    appendChild(child) { this.children.push(child); return child; },
    addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); },
    click() { (this.listeners.click || []).forEach((fn) => fn()); },
  };
}

function renderer(lang) {
  const document = {
    documentElement: lang === undefined ? undefined : { lang },
    createElement: el,
  };
  return vm.runInNewContext("(" + CARD + ")", {
    document,
    window: { PadiemClawPdfPreview: null },
    clawT: (key) => key,
    clawRunStatusLabel: (status) => status,
    clawRunHistoryPdfControllers: new Set(),
    setClawRunHistoryStatus: () => {},
    downloadClawArtifact: () => {},
    openSavedConversation: () => {},
    renderClawApprovalControls: () => {},
  });
}

function walk(root, out) {
  out = out || [];
  (root.children || []).forEach((child) => { out.push(child); walk(child, out); });
  return out;
}
function metaOf(card) { return walk(card).filter((n) => n.className === "claw-run-card-meta")[0]; }
function build(createdAt, lang) {
  return renderer(lang)({
    run_id: "run.one", title: "[KAKAO] quote_draft: A업체", status: "completed",
    channel: "kakao", action: "quote_draft", created_at: createdAt,
    result_summary: "견적 요약", artifact: null, session: null,
  });
}

const checks = {};
const ok = (name, condition, detail) => {
  checks[name] = condition;
  if (!condition) { console.log(JSON.stringify({ ok: false, error: name, detail, checks })); process.exit(0); }
};

// 1) The raw ISO instant no longer reaches the reader, and the year still does.
const ko = metaOf(build("2026-09-19T01:00:00Z", "ko"));
ok("CARD_HIDES_RAW_ISO_INSTANT",
   ko.textContent.indexOf("2026-09-19T01:00:00Z") < 0
   && ko.textContent.indexOf("T01:00:00Z") < 0
   && ko.textContent.indexOf("2026") >= 0, ko.textContent);

// 2) The exact stored instant stays available on the element.
ok("CARD_KEEPS_EXACT_STORED_VALUE", ko.title === "2026-09-19T01:00:00Z", ko.title);

// 3) The page language decides the rendering, not a hardcoded locale.
const en = metaOf(build("2026-09-19T01:00:00Z", "en"));
ok("CARD_FOLLOWS_PAGE_LANGUAGE",
   en.textContent !== ko.textContent
   && en.textContent.indexOf("2026") >= 0
   && en.textContent.indexOf("T01:00:00Z") < 0,
   en.textContent + " | " + ko.textContent);

// 4) An unparseable stored value is shown exactly as received.
for (const garbage of ["not-a-date", "2026-13-45T99:99:99Z", "0000-00-00"]) {
  const card = metaOf(build(garbage, "ko"));
  ok("CARD_UNPARSEABLE_VALUE_SHOWN_VERBATIM", card.textContent.indexOf(garbage) >= 0, garbage);
  ok("CARD_KEEPS_EXACT_STORED_VALUE", card.title === garbage, garbage);
}

// 5) An absent value adds no separator and no title.
for (const missing of ["", null, undefined, 0]) {
  const card = metaOf(build(missing, "ko"));
  ok("CARD_ABSENT_VALUE_ADDS_NOTHING",
     card.title === undefined && card.textContent === "kakao · quote_draft", String(missing));
}

// 6) The rest of the meta line and the card are untouched.
const normal = metaOf(build("2026-09-19T01:00:00Z", "ko"));
ok("CARD_OTHER_FIELDS_UNCHANGED",
   normal.textContent.startsWith("kakao · quote_draft · ")
   && normal.textContent.split(" · ").length === 3);
const noLang = metaOf(build("2026-09-19T01:00:00Z", undefined));
ok("CARD_OTHER_FIELDS_UNCHANGED", noLang.textContent.indexOf("2026") >= 0 && noLang.title === "2026-09-19T01:00:00Z");

console.log(JSON.stringify({ ok: true, checks, ko: ko.textContent, en: en.textContent }));
"""


def _run_harness() -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the behavioral harness"
    harness_path = ROOT / "tests" / "_l6_claw_run_card_timestamp_harness.js"
    harness_path.write_text(_HARNESS, encoding="utf-8")
    try:
        result = subprocess.run(
            [node, str(harness_path), str(APP_JS)],
            capture_output=True, text=True, timeout=60,
        )
    finally:
        harness_path.unlink(missing_ok=True)
    assert result.returncode == 0, f"harness exited {result.returncode}: {result.stderr}"
    line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "{}"
    return json.loads(line)


def test_behavioral_run_card_timestamp() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, payload
    for name in (
        "CARD_HIDES_RAW_ISO_INSTANT",
        "CARD_KEEPS_EXACT_STORED_VALUE",
        "CARD_FOLLOWS_PAGE_LANGUAGE",
        "CARD_UNPARSEABLE_VALUE_SHOWN_VERBATIM",
        "CARD_ABSENT_VALUE_ADDS_NOTHING",
        "CARD_OTHER_FIELDS_UNCHANGED",
    ):
        assert payload["checks"].get(name) is True, name


if __name__ == "__main__":
    test_meta_line_renders_through_the_instant_helper()
    test_exact_stored_value_is_preserved()
    test_helper_never_invents_a_value()
    test_page_language_defaults_without_a_document_element()
    test_behavioral_run_card_timestamp()
    print("L6_CLAW_RUN_CARD_TIMESTAMP_TESTS=PASS")
