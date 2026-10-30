"""#6265 retroactive guard — CI reverse-dependency trigger contract.

Incident: PR #6265 removed ``_OPTIMIZE_FOR`` (and the auto/fallback knobs)
from ``packages/padiem-ai-core/padiem_ai_core/b14_execution.py`` while
touching no KAgent file. KAgent's CI lane (validate-b54-kagent.yml) only
triggered on a hand-picked list of Core files, so main stayed green while
four KAgent tests and one KAgent source module that import
``padiem_ai_core.b14_execution`` were already broken. The break only
surfaced when later PRs (#6339/#6335) happened to touch KAgent paths and
were repaired by #6280. The same structure shipped once before with the
missing ``pypdf`` dependency.

Contract enforced here
----------------------
For every CI workflow whose ``pull_request.paths`` includes
``apps/<app>/**``, the app's *effective* shared-package dependencies must
each be covered by a ``packages/<pkg>/**`` entry in the same paths list.
The effective dependencies of an app are:

* the ``file://`` package dependencies declared in ``apps/<app>/pyproject.toml``;
* every ``packages/<pkg>`` the workflow itself installs with
  ``pip install -e`` (the KAgent style: the pyproject declares no package
  dependency but the CI installs the shared Core explicitly).

The covered-package set is the union of ``packages/<pkg>/**`` entries and
same-package file entries (``packages/<pkg>/<rest>``) already present, so
pre-existing per-file triggers keep satisfying the rule while the glob is
what actually closes the partial-list gap.

Scope note: the enforced package set is padiem-ai-core — both recorded
incidents (the missing ``pypdf``, the #6265 ``_OPTIMIZE_FOR`` removal) are
Core changes. The table lives in ``REVERSE_DEPENDENCY_RULES`` and extends
mechanically if another shared package earns the same treatment.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"

#: Shared packages whose every dependent-app CI must carry a glob trigger.
#: Both recorded incidents (#6265 _OPTIMIZE_FOR, missing pypdf) are changes
#: to this package. Extend the tuple to enforce more packages mechanically.
SHARED_PACKAGES: tuple[str, ...] = ("padiem-ai-core",)

#: Deployment workflows filter on app paths because they deploy them; they
#: are owned by the protected deployment policy and are explicitly outside
#: this rule (no deployment workflow was modified for it — pinned by a test
#: below). The Worker deploy lane also negates test paths on purpose.
EXCLUDED_WORKFLOWS: frozenset[str] = frozenset({"b62-cloudflare-worker-deploy.yml"})

#: Apps whose pyproject declares a file:// dependency on a shared package.
#: Verified 2026-10-31 from apps/*/pyproject.toml.
DECLARED_FILE_DEPS: dict[str, frozenset[str]] = {
    "padiem-chat": frozenset({"padiem-ai-core", "padiem-control-plane"}),
    "padiem-ai-engine": frozenset({"padiem-ai-core"}),
    "padiem-document-parser": frozenset({"padiem-ai-core"}),
    "padiem-file-lane": frozenset({"padiem-ai-core"}),
}

#: Apps that declare no package dependency but whose CI installs shared
#: packages with ``pip install -e``. The install step is the dependency
#: evidence (korean-ai-code-agent/pyproject.toml declares ``dependencies =
#: []`` while its workflow installs three monorepo packages).
CI_INSTALLED_DEPS: dict[str, frozenset[str]] = {
    "korean-ai-code-agent": frozenset({"padiem-ai-core", "padiem-control-plane"}),
}

#: The dependency table this change enforces, in report order.
#: (app, workflow file, required shared package globs)
EXPECTED_DEPENDENCY_TABLE: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("padiem-chat", "b62-padiem-chat-ci.yml", ("packages/padiem-ai-core/**",)),
    ("padiem-ai-engine", "padiem-ai-engine-ci.yml", ("packages/padiem-ai-core/**",)),
    ("korean-ai-code-agent", "validate-b54-kagent.yml", ("packages/padiem-ai-core/**",)),
    ("padiem-file-lane", "validate-padiem-file-lane.yml", ("packages/padiem-ai-core/**",)),
)

_APP_PATH = re.compile(r"^apps/([^/]+)/\*\*$")
_PKG_ENTRY = re.compile(r"^packages/([^/]+)(?:/\*\*)?$")
_INSTALL_LINE = re.compile(r"pip install[^\n]*-e\s+\S*packages/([^/\s\"']+)")
_PULL_REQUEST_PATHS = re.compile(r"^  pull_request:\s*$", re.MULTILINE)


def _on_block(text: str) -> str:
    """Return the ``on:`` block of a workflow (up to the first ``jobs:`` key)."""
    start = text.index("on:")
    jobs = text.find("\njobs:", start)
    return text[start : jobs if jobs != -1 else len(text)]


def _pull_request_paths(workflow_path: Path) -> list[str] | None:
    """Extract the pull_request paths entries, or None when absent."""
    block = _on_block(workflow_path.read_text(encoding="utf-8"))
    if _PULL_REQUEST_PATHS.search(block) is None:
        return None
    entries: list[str] = []
    in_paths = False
    for line in block.splitlines():
        stripped = line.strip()
        is_section_key = bool(re.match(r"^[\w-]+:\s*$", line)) and not line.startswith(" ")
        if re.match(r"^    paths:\s*$", line):
            in_paths = True
            continue
        if is_section_key:
            in_paths = False
            continue
        if in_paths and stripped.startswith("- "):
            entries.append(stripped[2:].strip().strip("'\""))
    return entries


def _apps_of(paths: list[str]) -> set[str]:
    apps: set[str] = set()
    for entry in paths:
        match = _APP_PATH.match(entry)
        if match:
            apps.add(match.group(1))
    return apps


def _deps_of(app: str, workflow_text: str) -> set[str]:
    declared = set(DECLARED_FILE_DEPS.get(app, frozenset()))
    for match in _INSTALL_LINE.finditer(workflow_text):
        declared.add(match.group(1))
    return declared


def _covered_packages(paths: list[str]) -> set[str]:
    covered: set[str] = set()
    for entry in paths:
        match = _PKG_ENTRY.match(entry)
        if match:
            covered.add(match.group(1))
    return covered


class TestReverseDependencyTriggers(unittest.TestCase):
    def test_kagent_lane_triggers_on_any_core_change(self):
        """The #6265 fix: a partial Core edit must run the KAgent lane."""
        paths = _pull_request_paths(WORKFLOWS / "validate-b54-kagent.yml")
        self.assertIsNotNone(paths)
        assert paths is not None
        self.assertIn("packages/padiem-ai-core/**", paths)

    def test_file_lane_triggers_on_any_core_change(self):
        """file-lane declares Core as a file:// dependency in its pyproject."""
        paths = _pull_request_paths(WORKFLOWS / "validate-padiem-file-lane.yml")
        self.assertIsNotNone(paths)
        assert paths is not None
        self.assertIn("packages/padiem-ai-core/**", paths)

    def test_documented_dependency_table_is_mechanically_true(self):
        """Every row of the dependency table holds against the workflow."""
        for app, workflow_file, required_globs in EXPECTED_DEPENDENCY_TABLE:
            with self.subTest(app=app, workflow=workflow_file):
                paths = _pull_request_paths(WORKFLOWS / workflow_file)
                self.assertIsNotNone(paths, f"{workflow_file} lost its paths filter")
                assert paths is not None
                for glob in required_globs:
                    self.assertIn(glob, paths)

    def test_no_dependent_app_workflow_misses_the_core_glob(self):
        """The fail-closed sweep: every workflow that filters on an app with a
        padiem-ai-core dependency must trigger on the whole Core package."""
        violations: list[str] = []
        for workflow_path in sorted(WORKFLOWS.glob("*.yml")):
            if workflow_path.name in EXCLUDED_WORKFLOWS:
                continue
            paths = _pull_request_paths(workflow_path)
            if paths is None:
                continue  # dispatch/push-only lanes have no reverse trigger.
            workflow_text = workflow_path.read_text(encoding="utf-8")
            for app in sorted(_apps_of(paths)):
                deps = _deps_of(app, workflow_text) & set(SHARED_PACKAGES)
                covered = _covered_packages(paths)
                missing = deps - covered
                if missing:
                    pkg = sorted(missing)[0]
                    violations.append(
                        f"{workflow_path.name}: app {app} depends on "
                        f"{sorted(missing)} but paths has no "
                        f"'packages/{pkg}/**' entry"
                    )
        self.assertEqual(violations, [], "\n".join(violations))

    def test_the_incident_import_chain_is_now_in_trigger_scope(self):
        """The exact #6265 surface: b14_execution.py sits under the glob the
        KAgent lane now carries, so its next breaking edit cannot stay green
        while KAgent consumers import it."""
        core_module = ROOT / "packages/padiem-ai-core/padiem_ai_core/b14_execution.py"
        self.assertTrue(core_module.exists())
        paths = _pull_request_paths(WORKFLOWS / "validate-b54-kagent.yml")
        assert paths is not None
        covered = _covered_packages(paths)
        self.assertIn("padiem-ai-core", covered)

    def test_no_deploy_workflow_was_modified_for_this_rule(self):
        """Scope guard: deployment gates stay untouched by this rule."""
        for workflow_path in WORKFLOWS.glob("*.yml"):
            text = workflow_path.read_text(encoding="utf-8")
            if "deploy_production_code" in text or "deploy-mock" in text:
                self.assertNotIn(
                    "#6265 retroactive guard",
                    text,
                    f"{workflow_path.name}: the reverse-dependency rule must "
                    "not be enforced inside a deployment workflow",
                )


if __name__ == "__main__":
    unittest.main()
