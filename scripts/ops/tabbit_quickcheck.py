"""UI QuickCheck launcher: one bounded Tabbit screen check for a small UI edit.

Opt-in local QA only. This does NOT replace any required branch-protection CI,
security gate, approval or production deploy safeguard
(docs/operations/UI_UX_TABBIT_QUICKCHECK_20261012.md).

It drives the already-installed Tabbit CLI so a single acceptance claim about a
real page is answered with at most three screenshots, in roughly 30-90 seconds,
instead of a repeated full test sweep.

Usage:
  python scripts/ops/tabbit_quickcheck.py --url https://preview.example/ --action open
  python scripts/ops/tabbit_quickcheck.py --url https://preview.example/ --action narrow --width 390
  python scripts/ops/tabbit_quickcheck.py --url https://preview.example/ --action click \
      --role button --name "검색"

Safety properties, enforced in code:
  * http(s) URLs only, and never a URL carrying credentials.
  * Only a task-owned page is used. The tool never runs `claim`/`resume` and
    never passes `--tab`/`--group`, so an existing signed-in customer tab is
    never navigated.
  * Screenshots are capped at three and the CLI's own limit is re-checked.
  * Evidence holds URL, viewport, revision, action, timings and the measured
    result. No cookie, token, header, credential, page text or account content.
  * Absent CLI or unusable session exits BLOCKED (code 2) without guessing
    commands.

Exit codes: 0 PASS, 1 FAIL, 2 BLOCKED.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

MAX_SCREENSHOTS = 3
DEFAULT_TIMEOUT_MS = 60_000
MAX_TIMEOUT_MS = 180_000
CLI_TIMEOUT_SECONDS = 170
VIEWPORT_TOLERANCE_PX = 24
ACTIONS = ("open", "narrow", "click")

PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"


def launcher_path() -> Path | None:
    """The documented stable launcher, or None when Tabbit is not installed."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            candidate = Path(base) / "Tabbit" / "LocalAgent" / "bin" / "tabbit-cli.exe"
            return candidate if candidate.is_file() else None
        return None
    home = os.environ.get("HOME")
    if home:
        candidate = Path(home) / ".local" / "bin" / "tabbit-cli"
        return candidate if candidate.is_file() else None
    return shutil.which("tabbit-cli")


def parse_cli_output(stdout: str) -> dict | None:
    """Return the CLI's JSON envelope, ignoring the instance banner line."""
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                decoded = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(decoded, dict):
                return decoded
    return None


def validate_url(url: str) -> str | None:
    """Return a refusal reason for a URL, or None when it is acceptable."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return "only http(s) URLs are allowed"
    if not parts.netloc or not parts.hostname:
        return "URL has no host"
    if parts.username or parts.password:
        return "URL must not carry credentials"
    return None


def clamp_timeout_ms(requested: int) -> int:
    return max(5_000, min(int(requested), MAX_TIMEOUT_MS))


def _js(value: object) -> str:
    """Embed a Python value as a JSON literal, so no argument becomes code."""
    return json.dumps(value)


def build_program(url: str, action: str, width: int, desktop_width: int,
                  role: str, name: str) -> str:
    """One Node program: navigate, perform the single bounded action, capture.

    `page` and `tabbit` are Tabbit-provided globals. The program drives the
    *measured* CSS width rather than the window size it asked for: a connected
    browser can report a different `window.innerWidth` than the requested
    viewport (page zoom, window chrome), and a check that silently measures
    something else would answer a question nobody asked. One corrective pass
    derives the observed ratio and re-applies it.
    """
    locator = ""
    if action == "click":
        locator = f"""
const clicked = page.getByRole({_js(role)}, {{ name: {_js(name)}, exact: true }});
await clicked.waitFor({{ state: 'visible', timeout: 15000 }});
await clicked.click();
await page.waitForTimeout(400);"""
    target = width if action == "narrow" else desktop_width

    return f"""
const TARGET_CSS_WIDTH = {_js(target)};
const TOLERANCE = {_js(24)};

async function cssWidth() {{
  return await page.evaluate(() => window.innerWidth);
}}

// One corrective pass only. A connected browser can report a different
// `window.innerWidth` than the viewport it was handed, and a navigation can put
// the window back, so this runs *after* goto and is re-checked there.
async function reachCssWidth(t) {{
  const first = await cssWidth();
  const ratio = first > 0 ? first / t : 1;
  if (Math.abs(first - t) <= TOLERANCE || ratio <= 0.2 || ratio >= 5) {{
    return {{ achieved: first, corrected: false, ratio: null }};
  }}
  await page.setViewportSize({{ width: Math.round(t / ratio), height: 900 }});
  await page.waitForTimeout(300);
  return {{ achieved: await cssWidth(), corrected: true, ratio: Math.round(ratio * 1000) / 1000 }};
}}

await page.setViewportSize({{ width: TARGET_CSS_WIDTH, height: 900 }});
await page.goto({_js(url)}, {{ waitUntil: 'domcontentloaded', timeout: 30000 }});
await page.waitForTimeout(800);
const sizing = await reachCssWidth(TARGET_CSS_WIDTH);
await page.waitForTimeout(300);{locator}
const facts = await page.evaluate(() => ({{
  url: location.href,
  title: document.title,
  innerWidth: window.innerWidth,
  clientWidth: document.documentElement.clientWidth,
  scrollWidth: document.documentElement.scrollWidth,
}}));
// The measured facts come from DOM evaluation, so disabling animations for the
// image does not weaken them. It stops a continuously animating surface from
// holding the screenshot open until Playwright's stability wait expires.
const shot = await page.screenshot({{ fullPage: false, animations: 'disabled', timeout: 15000 }});
return {{
  facts,
  requestedViewport: TARGET_CSS_WIDTH,
  sizing,
  viewportHonored: Math.abs(facts.innerWidth - TARGET_CSS_WIDTH) <= TOLERANCE,
  horizontalOverflow: facts.scrollWidth > facts.clientWidth + 1,
  screenshotCount: shot.screenshotCount,
  limitExceeded: shot.recommendedLimitExceeded === true,
}};
"""


def judge(action: str, value: dict, requested_width: int) -> tuple[str, list[str]]:
    """Derive the verdict from measured facts only, never from intent.

    A browser can refuse to render the requested CSS width even after the
    corrective pass. That is surfaced as its own observation rather than being
    allowed to masquerade as a product verdict.
    """
    facts = value.get("facts") or {}
    observations: list[str] = []
    verdict = PASS

    honored = value.get("viewportHonored") is True
    if not honored:
        observations.append(
            f"requested CSS width {requested_width}px was not rendered; measured innerWidth="
            f"{facts.get('innerWidth')}px (sizing={value.get('sizing')}) — the check cannot "
            "certify a width it did not actually display"
        )

    if not facts.get("url"):
        observations.append("no final URL reported")
        verdict = FAIL
    if value.get("limitExceeded"):
        observations.append("screenshot limit exceeded")
        verdict = FAIL
    if value.get("screenshotCount", 0) > MAX_SCREENSHOTS:
        observations.append(f"screenshotCount={value.get('screenshotCount')} exceeds {MAX_SCREENSHOTS}")
        verdict = FAIL

    if action == "narrow":
        overflow = value.get("horizontalOverflow")
        observations.append(f"horizontalOverflow={overflow} at clientWidth={facts.get('clientWidth')}")
        if overflow is not False:
            verdict = FAIL
    elif action == "click":
        observations.append(f"clicked as requested; final title present={bool(facts.get('title'))}")
    else:
        observations.append(f"loaded title={facts.get('title')!r}")

    if facts.get("title") in (None, ""):
        observations.append("empty document title")
        if verdict == PASS:
            verdict = FAIL
    if not honored and verdict == PASS:
        # Never certify a claim about a width that was not actually rendered.
        verdict = FAIL
    return verdict, observations


def run_cli(launcher: Path, args: list[str], program: str | None = None) -> tuple[int, dict | None, str]:
    # text mode is on, so the program must be handed over as str; bytes would
    # make the stdin pipe reject it.
    completed = subprocess.run(
        [str(launcher), *args],
        input=program,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=CLI_TIMEOUT_SECONDS,
    )
    return completed.returncode, parse_cli_output(completed.stdout or ""), (completed.stderr or "")


def collect_screenshots(result: dict, evidence: Path, url: str) -> list[str]:
    """Copy only the images this check produced into the evidence directory."""
    names: list[str] = []
    seen: set[str] = set()
    try:
        evidence.mkdir(parents=True, exist_ok=True)
    except OSError:
        return names
    for entry in result.get("screenshotsDelta") or []:
        source = entry.get("path")
        if not source or source in seen:
            continue
        seen.add(source)
        try:
            origin = urlsplit(url).netloc.replace(":", "_") or "page"
            target = evidence / f"quickcheck-{len(names) + 1}-{origin}.png"
            shutil.copyfile(source, target)
            names.append(target.name)
        except OSError:
            # A missing artifact is reported as absent evidence, never invented.
            continue
    return names


def git_revision() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = (completed.stdout or "").strip()
    return value if completed.returncode == 0 and re.fullmatch(r"[0-9a-f]{7,40}", value) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One bounded Tabbit UI QuickCheck (opt-in local QA).")
    parser.add_argument("--url", required=True)
    parser.add_argument("--action", choices=ACTIONS, default="open")
    parser.add_argument("--width", type=int, default=390, help="narrow viewport width for --action narrow")
    parser.add_argument("--desktop-width", type=int, default=1440)
    parser.add_argument("--role", default="button", help="locator role for --action click")
    parser.add_argument("--name", default="", help="exact accessible name for --action click")
    parser.add_argument("--timeout-ms", type=int, default=DEFAULT_TIMEOUT_MS)
    parser.add_argument("--task", default="", help="task/tab-group label; defaults to quickcheck-<action>")
    parser.add_argument("--evidence-dir", default="", help="defaults to .tmp/tabbit-quickcheck/<utc-stamp>")
    args = parser.parse_args(argv)

    started = time.monotonic()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    evidence = Path(args.evidence_dir or Path(".tmp") / "tabbit-quickcheck" / stamp)
    metadata: dict[str, object] = {
        "tool": "tabbit_quickcheck",
        "url": args.url,
        "action": args.action,
        "requested_viewport": args.width if args.action == "narrow" else args.desktop_width,
        "revision": git_revision(),
        "started_utc": stamp,
        "screenshots": [],
        "observations": [],
    }

    def emit(verdict: str, code: int) -> int:
        metadata["result"] = verdict
        metadata["elapsed_seconds"] = round(time.monotonic() - started, 2)
        try:
            evidence.mkdir(parents=True, exist_ok=True)
            (evidence / "quickcheck.json").write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8",
            )
        except OSError:
            pass
        print(json.dumps({**metadata, "evidence_dir": str(evidence)}, ensure_ascii=False, indent=2))
        return code

    refusal = validate_url(args.url)
    if refusal:
        metadata["observations"] = [refusal]
        return emit(BLOCKED, 2)

    launcher = launcher_path()
    if launcher is None:
        metadata["observations"] = ["tabbit-cli launcher not found at the documented stable path"]
        return emit(BLOCKED, 2)

    task = args.task or f"quickcheck-{args.action}"
    try:
        code, diagnosis, _ = run_cli(launcher, ["diagnose"])
        if code != 0 or not diagnosis or diagnosis.get("ok") is not True:
            metadata["observations"] = ["tabbit diagnose did not report a running controller"]
            return emit(BLOCKED, 2)
        controller = (diagnosis.get("controller") or "")
        if controller != "running":
            metadata["observations"] = [f"tabbit controller state={controller!r}"]
            return emit(BLOCKED, 2)

        program = build_program(
            args.url, args.action, args.width, args.desktop_width, args.role, args.name,
        )
        code, payload, stderr = run_cli(
            launcher,
            ["nodejs", "--task", task, "--request-id", f"qc-{stamp}", "--timeout-ms", str(clamp_timeout_ms(args.timeout_ms))],
            program,
        )
        result = (payload or {}).get("result") or {}
        status = (payload or {}).get("status") or result.get("status") or ""
        if code != 0 or status != "succeeded":
            metadata["observations"] = [f"tabbit nodejs status={status or 'unknown'} exit={code}"]
            detail = result.get("error") or (payload or {}).get("error") or stderr[-200:]
            metadata["failure_detail"] = str(detail)[:200]
            return emit(BLOCKED, 2)

        value = result.get("value") or {}
        facts = value.get("facts") or {}
        metadata["measured"] = {
            "final_url": facts.get("url"),
            "title": facts.get("title"),
            "inner_width": facts.get("innerWidth"),
            "client_width": facts.get("clientWidth"),
            "scroll_width": facts.get("scrollWidth"),
            "horizontal_overflow": value.get("horizontalOverflow"),
            "screenshot_count": value.get("screenshotCount"),
            "viewport_honored": value.get("viewportHonored"),
            "viewport_sizing": value.get("sizing"),
        }
        metadata["screenshots"] = collect_screenshots(result, evidence, args.url)
        requested_width = args.width if args.action == "narrow" else args.desktop_width
        verdict, observations = judge(args.action, value, requested_width)
        metadata["observations"] = observations
        return emit(verdict, 0 if verdict == PASS else 1)
    except subprocess.TimeoutExpired:
        metadata["observations"] = [f"tabbit invocation exceeded {CLI_TIMEOUT_SECONDS}s"]
        return emit(BLOCKED, 2)
    except OSError as error:
        metadata["observations"] = [f"launcher invocation failed: {type(error).__name__}"]
        return emit(BLOCKED, 2)
    finally:
        # Release task ownership even on failure, but keep the tabs: plain finish
        # never closes acquired user tabs, and this tool never acquires any.
        try:
            run_cli(launcher, ["finish", "--task", task])
        except Exception:  # noqa: BLE001 — cleanup must not mask the verdict
            pass


if __name__ == "__main__":
    sys.exit(main())
