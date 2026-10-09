"""Choose exact B62 browser QA lanes for one pull_request workflow run.

GitHub API failure, oversized PR, or missing changed-file context runs *all*
lanes; never silently skip regression tests due to classifier uncertainty.
This is non-privileged PR CI and reads public/accessible PR file metadata only.
"""

from __future__ import annotations

import fnmatch
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / ".github" / "ci" / "b62_browser_qa_paths.json"
MAX_PR_FILES = 3000

# Any policy update to the shared dispatcher must exercise every QA lane.
PLAN_FILES = frozenset(
    {
        ".github/workflows/b62-browser-qa-unified.yml",
        ".github/scripts/b62_browser_qa_path_plan.py",
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


def choose_lanes(
    changed_paths: set[str] | None, patterns_by_job: dict[str, list[str]]
) -> dict[str, bool]:
    if changed_paths is None:
        return {job: True for job in patterns_by_job}
    if changed_paths & PLAN_FILES:
        return {job: True for job in patterns_by_job}
    return {
        job: any(path_matches(path, patterns) for path in changed_paths)
        for job, patterns in patterns_by_job.items()
    }


def fetch_changed_paths(event: dict, environ: dict[str, str]) -> set[str] | None:
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
            names.add(entry["filename"])
            if entry.get("status") == "renamed" and entry.get("previous_filename"):
                names.add(entry["previous_filename"])
        if len(items) < 100:
            return names
        if page == 30:
            # GitHub caps list-pull-request-files at 3000 entries.
            return None
    return None


def main() -> int:
    patterns = load_paths()
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        changed = fetch_changed_paths(event, os.environ)
    except (KeyError, ValueError, OSError, json.JSONDecodeError):
        changed = None
    chosen = choose_lanes(changed, patterns)
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        raise RuntimeError("GITHUB_OUTPUT is missing: cannot report QA selection")
    # Explicitly report every job. No implicit default-to-skip.
    with open(output, "a", encoding="utf-8") as out:
        for job, selected in chosen.items():
            safe_name = job.replace("-", "_")
            out.write(f"{safe_name}={'true' if selected else 'false'}\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as out:
            out.write("### B62 Browser QA selection\n\n")
            out.write(f"Changed-file classifier: {'fallback all' if changed is None else 'PR file list'}\n\n")
            for job, selected in chosen.items():
                out.write(f"- {job}: {'RUN' if selected else 'SKIP'}\n")
    print(
        "B62_QA_PATH_PLAN=",
        "fallback-all" if changed is None else "filtered",
        "RUN=",
        sum(chosen.values()),
        "TOTAL=",
        len(chosen),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())