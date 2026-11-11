"""CI queue incident 2026-11-12 — PR checks keep their own concurrency group.

A single fixed concurrency group on the B62 Cloudflare mock deploy workflow let
one queued main-push run (43094998096, pending since 20:16 UTC) hold every PR's
mock deploy check: PR #7514's run 43095603147 waited behind it. Three other
PR-triggered read-only checks carried the same fixed-group shape (quote URL
activation preflight, live content marker probe, Gmail post-seed attestation).

The rule pinned for the corrected workflows:
- pull_request runs use a per-PR group (the PR number is in the group),
- a superseded PR run is cancelled (cancel-in-progress is on for PR runs),
- push/dispatch runs keep the one shared serial group, so the deploy/ops
  protection window those workflows exist for is unchanged.
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

#: workflow file -> the shared serial group kept for push/dispatch runs
CASES = {
    "b62-cloudflare-worker-deploy.yml": "b62-cloudflare-mock-deploy",
    "b62-b66-quote-url-activation-gate.yml": "b62-b66-quote-url-activation-gate",
    "b62-live-content-marker-gate.yml": "b62-live-content-marker-gate",
    "b54-gmail-postseed-readonly-attestation.yml": "b54-gmail-postseed-readonly-attestation",
}


def _load(name: str) -> dict:
    text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
    return yaml.safe_load(text)


def _triggers(workflow: dict) -> dict:
    # PyYAML reads the bare `on:` key as boolean True (YAML 1.1).
    return workflow.get("on", workflow.get(True))


def test_pr_checks_use_a_per_pr_group_and_cancel_superseded_runs() -> None:
    for name, serial_group in CASES.items():
        concurrency = _load(name)["concurrency"]
        group = concurrency["group"]
        assert "github.event_name == 'pull_request'" in group, name
        assert "github.event.pull_request.number" in group, name
        assert group.endswith("'" + serial_group + "' }}"), name
        assert concurrency["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}", name


def test_the_corrected_workflows_still_trigger_on_pull_request() -> None:
    for name in CASES:
        assert "pull_request" in _triggers(_load(name)), name
