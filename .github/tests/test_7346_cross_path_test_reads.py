"""#7346 guard — a test that reads another bundle's file must run when that file moves.

Incident: ``packages/padiem-ai-core/tests/test_4194_model_lane_timeout_guard.py``
loads ``apps/korean-ai-platform/app/pilot/b14_timeout_policy.py`` from source.
#7336 added a sibling-relative import to that app file; the app's own PR checks
passed because the Core suite never ran there, so main broke and only the
nightly full suite noticed (#7340).

The survey script resolves every test file that reads another bundle's path and
checks whether any pull-request workflow that runs the reading test also
triggers on the read path. This guard fails when a new cross-bundle read lands
without that mapping, and when an allowlist entry is no longer needed.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "scripts" / "cross_path_test_reads_7346.py"

_spec = importlib.util.spec_from_file_location("cross_path_test_reads_7346", SCRIPT)
assert _spec and _spec.loader
survey_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = survey_module
_spec.loader.exec_module(survey_module)

#: (reading test file, read path) -> reason the pair is accepted unmapped.
ALLOWLIST: dict[tuple[str, str], str] = {
    (
        "packages/padiem-control-plane/tests/test_owner_model_name_parts.py",
        "apps/korean-ai-platform/app/pilot/google_provider.py",
    ): (
        "No pull-request workflow runs the Control Plane unit suite at all "
        "(padiem-control-plane-ci.yml runs only .github contracts), so there is "
        "no PR lane to attach the path to; the suite is nightly-only. Adding a "
        "Control Plane unit job is a new suite, not a paths mapping."
    ),
    (
        ".github/tests/test_b54_p01_overlay_caller_id_parity.py",
        "apps/padiem-chat/app/web_xlsx_p01_engine_client.py",
    ): (
        "The two B54 caller-registry gates that run this parity contract pin a "
        "gate-decoupling invariant: their workflow code must never name "
        "padiem-chat. Adding the Chat path would trip that invariant, so the "
        "read stays nightly-only until the gate ownership is redesigned."
    ),
    (
        ".github/tests/test_b62_automation_scheduler_config.py",
        "apps/padiem-chat/wrangler.toml",
    ): (
        "Adding the Chat binding file to this gate's paths exposes a "
        "pre-existing stale contract on main: #6773 added [triggers] to "
        "apps/padiem-chat/wrangler.toml while "
        "test_repository_scheduler_source_stays_inert still asserts it is "
        "inert. Repairing that contract is a separate decision; mapping it "
        "here would turn an unrelated PR red."
    ),
}


def _pairs() -> dict[tuple[str, str], dict]:
    return {(row["suite"], row["reads"]): row for row in survey_module.survey()["pairs"]}


def test_every_cross_bundle_read_runs_in_the_read_paths_pr_check():
    violations = []
    for pair in _pairs().values():
        for entry in pair["files"]:
            if entry["verdict"] != "unpaired":
                continue
            if (entry["test"], entry["read_path"]) in ALLOWLIST:
                continue
            violations.append(
                f"{entry['test']}:{entry['line']} reads {entry['read_path']} "
                f"but no PR workflow that runs it triggers on that path "
                f"(runners: {', '.join(entry['runners']) or 'none'})"
            )
    assert violations == [], (
        "Map the read path into the workflow paths that run the reading test, "
        "or record an allowlist reason.\n" + "\n".join(violations)
    )


def test_allowlist_entries_are_still_required():
    unpaired = {
        (entry["test"], entry["read_path"])
        for pair in _pairs().values()
        for entry in pair["files"]
        if entry["verdict"] == "unpaired"
    }
    stale = [key for key in ALLOWLIST if key not in unpaired]
    assert stale == [], (
        "These allowlist entries are now covered; delete them from ALLOWLIST: "
        f"{stale}"
    )


def test_the_7340_pair_is_mapped():
    """The exact surface of #7336 -> #7340: Core reading the B14 policy module."""
    pair = _pairs()[("packages/padiem-ai-core", "apps/korean-ai-platform")]
    assert pair["verdict"] == "paired"
    assert any(
        entry["test"].endswith("test_4194_model_lane_timeout_guard.py")
        for entry in pair["files"]
    )
