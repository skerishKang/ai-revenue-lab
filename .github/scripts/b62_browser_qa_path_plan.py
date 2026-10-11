"""Choose exact B62 browser QA lanes for one pull_request workflow run.

GitHub API failure, oversized PR, or missing changed-file context runs *all*
lanes; never silently skip regression tests due to classifier uncertainty.
This is non-privileged PR CI and reads public/accessible PR file metadata only.

Lane ownership is per product surface, not "anything under apps/". A lane that
drives a B62 flow depends on the shared Chat app (factory, auth, session,
storage, worker, static bundle) and on its own QA script - not on another
product's leaf modules. `apps/padiem-chat/app/b66_*` and the B66 quote runtime
are therefore excluded from every lane (#3989): they cannot change a B62 flow,
and the mandatory B62 Padiem Chat CI still runs the whole Chat suite plus the
Worker bundle dry-run for those files, so an import or composition break stays
a hard failure. The exclusions are ordered after their positives in the
manifest, and `.github/tests/test_3989_ci_scope.py` pins the boundary, the
mixed-change behaviour and the fail-open states.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / ".github" / "ci" / "b62_browser_qa_paths.json"
MAX_PR_FILES = 3000
B66_QUOTE_CSS = "apps/padiem-chat/static/b66-quote-runtime.css"

# #3989: the two Claw manual-entry CSS rules affect only labelled inputs
# inside the Claw workspace. Preserve browser smoke, accessibility, identity,
# document and project-file coverage while skipping other unrelated journeys.
CLAW_MANUAL_INTAKE_CSS = "apps/padiem-chat/static/claw-manual-intake.css"
# Supplier quote comparison is a separate Claw-only UI surface. Keep the
# same conservative five shared-smoke/a11y/auth/document/file checks.
CLAW_QUOTE_COMPARE_CSS = "apps/padiem-chat/static/claw-quote-compare.css"
CLAW_MANUAL_QA_OWNERS = frozenset({
    "accessibility-browser-qa",
    "auth-history-browser-qa",
    "browser-qa",
    "document-browser-qa",
    "project-files-browser-qa",
})
_CLAW_MANUAL_SELECTORS = frozenset({
    ".claw-field",
    ".claw-field input",
    ".claw-field select",
})
# Narrow, explicit CSS grammar. Every target still lives inside Claw quote
# comparison, including two selectors guarded by the parent app state.
_CLAW_QUOTE_SELECTOR = re.compile(
    r"\.claw-(?:quote-compare|qc-[a-z0-9-]+)"
    r"(?::(?:first-of-type|disabled|focus-visible)|\[data-state=\"(?:error|success)\"\])?"
    r"(?:\s+(?:select|input)(?::focus-visible)?|\s*>\s*button)?\Z"
)
_CLAW_QUOTE_STATE_SELECTORS = frozenset({
    '.app-shell:not([data-state="claw"]) .claw-quote-compare',
    '.claw-workspace[data-view="inbox"] ~ .claw-quote-compare',
})
_CLAW_QUOTE_MEDIA = frozenset({
    "@media (max-width: 920px)",
    "@media (max-width: 560px)",
})

# Both the B66 JS bridge and these styles belong solely to the hidden B66
# quote dialog. The CSS exclusion is valid only while every selector remains
# anchored to an exact B66 quote class. This guard fails open on ambiguity.
_B66_CSS_SELECTOR = re.compile(r"^\.b66-quote-[\w-]+(?=$|[\s.:#\[>+~])")


# Only isolated leaf modules can omit unrelated Glass visual tail.
GLASS_TAIL_UNCHANGED_LEAVES = frozenset({
    "apps/padiem-chat/static/claw-web-xlsx-sources.js",
    "apps/padiem-chat/static/conversation-export.js",
})


def require_glass_visual_tail(
    changed_paths: set[str] | None, statuses: dict[str, str] | None,
    *, manual: bool = False, expected_files: int | None = None,
) -> bool:
    """Return required unless exact modified UI leaf paths are proven."""
    if manual or not changed_paths or statuses is None:
        return True
    # A truncated API response or missing PR changed_files is never proof.
    if type(expected_files) is not int or expected_files != len(changed_paths):
        return True
    if not changed_paths.issubset(GLASS_TAIL_UNCHANGED_LEAVES):
        return True
    if set(statuses) != changed_paths:
        return True
    return any(s != "modified" for s in statuses.values())


# Any policy update to the shared dispatcher must exercise every QA lane.
PLAN_FILES = frozenset(
    {
        ".github/workflows/b62-browser-qa-unified.yml",
        ".github/scripts/b62_browser_qa_path_plan.py",
        # Schedule implementation/test updates must prove every affected lane.
        ".github/scripts/b62_browser_qa_tail_parallel.py",
        ".github/tests/test_3989_b62_browser_tail_parallel.py",
        ".github/scripts/b62_glass_shell_visual_qa.py",
        ".github/workflows/b62-glass-animation-timing-certification.yml",
        ".github/tests/test_3989_b62_glass_timing_ownership.py",
        ".github/tests/test_3989_b62_owner_leaf_browser_base.py",
        ".github/tests/test_3989_b62_headless_shell_install.py",
        ".github/tests/test_3989_b66_quote_css_scope.py",
        ".github/tests/test_3989_claw_manual_css_scope.py",
        ".github/tests/test_3989_claw_quote_css_scope.py",
        ".github/ci/b62_browser_qa_paths.json",
    }
)


def load_paths() -> dict[str, list[str]]:
    info = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if info.get("schema") != 1 or not isinstance(info.get("jobs"), dict):
        raise ValueError("Invalid B62 browser QA ownership manifest")
    return info["jobs"]


def path_matches(filename: str, patterns: list[str]) -> bool:
    """Apply positive/negative path patterns in order, conservatively.

    Python fnmatch '*' matches '/', which can overselect compared to Github's
    minimatch semantics, but cannot silently miss an eligible exact/recursive
    B62 path (all maintained patterns are recursive or exact paths).
    """
    selected = False
    for item in patterns:
        negative = item.startswith("!")
        pattern = item[1:] if negative else item
        if fnmatch.fnmatchcase(filename, pattern):
            selected = not negative
    return selected


def b66_quote_css_is_isolated(source: str | None = None) -> bool:
    """Reject any rule that could style non-B66 Chat UI; no CSS dependency.

    Parsing is intentionally narrow: only B66 class-anchored selectors and
    media-query groups are allowed. Unknown at-rules, malformed CSS, missing
    source or comment/brace ambiguity trigger the full B62 browser suite.
    """
    if source is None:
        try:
            source = (ROOT / B66_QUOTE_CSS).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return False
    if re.search(r"@(?:import|font-face|keyframes|property|layer|namespace|charset)\b", source, re.I):
        return False
    if source.count("/*") != source.count("*/"):
        return False
    cleaned = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    if "/*" in cleaned or "*/" in cleaned:
        return False
    stack: list[str] = []
    count = 0
    position = 0
    for part in re.finditer(r"([^{}]*)([{}])", cleaned, flags=re.S):
        if part.start() != position:
            return False
        prefix = part.group(1).strip()
        brace = part.group(2)
        position = part.end()
        if brace == "{":
            if prefix.startswith("@media "):
                if stack and stack[-1] != "group":
                    return False
                stack.append("group")
            else:
                if not prefix or prefix.startswith("@"):
                    return False
                if stack and stack[-1] != "group":
                    return False
                if not all(_B66_CSS_SELECTOR.match(sel.strip()) for sel in prefix.split(",")):
                    return False
                stack.append("rule")
                count += 1
        else:
            if not stack:
                return False
            if stack[-1] == "group" and prefix:
                return False
            stack.pop()
    return count > 0 and not stack and not cleaned[position:].strip()


def claw_manual_css_is_isolated(source: str | None = None) -> bool:
    """Proof for exact Claw field selectors; anything else runs all lanes.

    No permissive CSS parsing: disallow at-rules, nested rules, global and
    sibling selectors. Missing/malformed source or an unknown selector must
    never silently reduce browser QA.
    """
    if source is None:
        try:
            source = (ROOT / CLAW_MANUAL_INTAKE_CSS).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return False
    if source.count("/*") != source.count("*/"):
        return False
    cleaned = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    if "/*" in cleaned or "*/" in cleaned or "@" in cleaned:
        return False
    position = 0
    seen: set[str] = set()
    rule = re.compile(r"\s*([^{}]+?)\s*\{([^{}]*)\}", re.S)
    while position < len(cleaned) and cleaned[position:].strip():
        hit = rule.match(cleaned, position)
        if hit is None:
            return False
        for selector in hit.group(1).split(","):
            selector = " ".join(selector.split())
            if selector not in _CLAW_MANUAL_SELECTORS:
                return False
            seen.add(selector)
        position = hit.end()
    return ".claw-field" in seen and not cleaned[position:].strip()


def claw_quote_css_is_isolated(source: str | None = None) -> bool:
    """Verify ALL selectors in Claw quote CSS, including responsive groups.

    Any new selector, media query, at-rule, malformed/unreadable CSS, nesting
    or global escape restores the original full browser QA instead of skipping.
    """
    if source is None:
        try:
            source = (ROOT / CLAW_QUOTE_COMPARE_CSS).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return False
    if source.count("/*") != source.count("*/"):
        return False
    cleaned = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    if "/*" in cleaned or "*/" in cleaned or re.search(r"url\s*\(", cleaned, re.I):
        return False
    stack: list[str] = []
    position = 0
    rules = 0
    for token in re.finditer(r"([^{}]*)([{}])", cleaned, flags=re.S):
        if token.start() != position:
            return False
        prefix = token.group(1).strip()
        position = token.end()
        if token.group(2) == "{":
            if prefix in _CLAW_QUOTE_MEDIA and not stack:
                stack.append("media")
            elif not stack or stack[-1] == "media":
                if not prefix or prefix.startswith("@"):
                    return False
                for selector in prefix.split(","):
                    selector = " ".join(selector.split())
                    if (selector not in _CLAW_QUOTE_STATE_SELECTORS
                            and not _CLAW_QUOTE_SELECTOR.fullmatch(selector)):
                        return False
                stack.append("rule")
                rules += 1
            else:
                return False
        else:
            if not stack or (stack[-1] == "media" and prefix):
                return False
            # Rule contents must be declarations, never nested CSS/at-rules.
            if stack[-1] == "rule" and (
                not prefix or "@" in prefix or "<" in prefix or ">" in prefix
            ):
                return False
            stack.pop()
    return rules > 0 and not stack and not cleaned[position:].strip()


def choose_lanes(
    changed_paths: set[str] | None, patterns_by_job: dict[str, list[str]]
) -> dict[str, bool]:
    if changed_paths is not None and B66_QUOTE_CSS in changed_paths:
        if not b66_quote_css_is_isolated():
            return {job: True for job in patterns_by_job}
        # Exact B66-only stylesheet is loaded with Chat, but its selectors
        # cannot affect B62 surfaces while the strict local scope guard passes.
        # Remove only this path, preserving every other mixed-PR dependency.
        changed_paths = changed_paths - {B66_QUOTE_CSS}
    if changed_paths is None:
        return {job: True for job in patterns_by_job}
    if changed_paths & PLAN_FILES:
        return {job: True for job in patterns_by_job}
    claw_field_change = CLAW_MANUAL_INTAKE_CSS in changed_paths
    if claw_field_change and not claw_manual_css_is_isolated():
        return {job: True for job in patterns_by_job}
    claw_quote_change = CLAW_QUOTE_COMPARE_CSS in changed_paths
    if claw_quote_change and not claw_quote_css_is_isolated():
        return {job: True for job in patterns_by_job}
    isolated_claw_css = {CLAW_MANUAL_INTAKE_CSS, CLAW_QUOTE_COMPARE_CSS}
    remaining = changed_paths - isolated_claw_css
    return {
        job: (
            ((claw_field_change or claw_quote_change) and job in CLAW_MANUAL_QA_OWNERS)
            or any(path_matches(path, patterns) for path in remaining)
        )
        for job, patterns in patterns_by_job.items()
    }


def choose_manual_lanes(
    lane: str, patterns_by_job: dict[str, list[str]]
) -> dict[str, bool]:
    """Manually dispatch one original QA job or explicitly select all."""
    if lane == "all":
        return {job: True for job in patterns_by_job}
    if lane not in patterns_by_job:
        raise ValueError("Invalid manual B62 QA lane selection")
    return {job: job == lane for job in patterns_by_job}


def fetch_changed_paths(event: dict, environ: dict[str, str], statuses: dict[str, str] | None = None) -> set[str] | None:
    pr = event.get("pull_request") or {}
    number = pr.get("number") or event.get("number")
    if not isinstance(number, int) or number < 1:
        return None
    if int(pr.get("changed_files", 0)) >= MAX_PR_FILES:
        return None
    api_url = environ.get("GITHUB_API_URL", "").rstrip("/")
    repo = environ.get("GITHUB_REPOSITORY", "")
    token = environ.get("GITHUB_TOKEN", "")
    if not api_url.startswith("https://") or "/" not in repo or not token:
        return None
    names: set[str] = set()
    for page in range(1, 32):
        url = f"{api_url}/repos/{repo}/pulls/{number}/files?per_page=100&page={page}"
        request = Request(
            url,
            headers={
                "Authorization": "Bearer " + token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urlopen(request, timeout=12) as response:
                items = json.load(response)
        except (HTTPError, URLError, OSError, ValueError, TimeoutError):
            return None
        if not isinstance(items, list):
            return None
        for entry in items:
            if not isinstance(entry, dict) or not isinstance(entry.get("filename"), str):
                return None
            filename = entry["filename"]
            names.add(filename)
            if statuses is not None:
                statuses[filename] = entry.get("status", "")
            if entry.get("status") == "renamed" and entry.get("previous_filename"):
                previous = entry["previous_filename"]
                names.add(previous)
                if statuses is not None:
                    statuses[previous] = "renamed"
        if len(items) < 100:
            return names
        if page == 30:
            # GitHub caps list-pull-request-files at 3000 entries.
            return None
    return None


def main() -> int:
    patterns = load_paths()
    manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    if manual:
        lane = os.environ.get("B62_MANUAL_LANE", "")
        chosen = choose_manual_lanes(lane, patterns)
        changed = None
        statuses = None
        expected_files = None
    else:
        statuses = {}
        expected_files = None
        try:
            event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
            expected_files = (event.get("pull_request") or {}).get("changed_files")
            changed = fetch_changed_paths(event, os.environ, statuses)
        except (KeyError, ValueError, OSError, json.JSONDecodeError):
            changed = None
        chosen = choose_lanes(changed, patterns)
    glass_tail_required = require_glass_visual_tail(
        changed, statuses, manual=manual, expected_files=expected_files,
    )
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        raise RuntimeError("GITHUB_OUTPUT is missing: cannot report QA selection")
    # Explicitly report every job. No implicit default-to-skip.
    with open(output, "a", encoding="utf-8") as out:
        out.write(f"glass_visual_tail_required={'true' if glass_tail_required else 'false'}\n")
        for job, selected in chosen.items():
            safe_name = job.replace("-", "_")
            out.write(f"{safe_name}={'true' if selected else 'false'}\n")
    selection_label = (
        ("manual lane " + lane) if manual
        else ("fallback all" if changed is None else "PR file list")
    )
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as out:
            out.write("### B62 Browser QA selection\n\n")
            out.write(f"Changed-file classifier: {selection_label}\n\n")
            out.write(f"Glass visual tail: {'REQUIRED' if glass_tail_required else 'SKIP_PROVEN_LEAF'}\n\n")
            for job, selected in chosen.items():
                out.write(f"- {job}: {'RUN' if selected else 'SKIP'}\n")
    print(f"B62_GLASS_VISUAL_TAIL={'REQUIRED' if glass_tail_required else 'SKIP_PROVEN_UNCHANGED'}")
    print(
        "B62_QA_PATH_PLAN=",
        "manual-" + lane if manual else ("fallback-all" if changed is None else "filtered"),
        "RUN=",
        sum(chosen.values()),
        "TOTAL=",
        len(chosen),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())