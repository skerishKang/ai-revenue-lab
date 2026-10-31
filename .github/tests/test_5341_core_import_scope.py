"""#5341: shared Core changes run only the checks their import scope can affect.

The proof is static and fail-closed:

* a Core module that no product imports is *independent* for that product;
* a Core module inside a product's import closure keeps the complete product
  regression, including the shared B62/Engine/B14 integration contracts;
* an unknown, unparsable or oversized change set keeps the complete path.

The contracts below pin the analyzer, the B62 and Engine lane wiring and the
required check names. No test, security scan or deployment gate is removed.
"""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".github/scripts"
B62_WORKFLOW = ROOT / ".github/workflows/b62-padiem-chat-ci.yml"
ENGINE_WORKFLOW = ROOT / ".github/workflows/padiem-ai-engine-ci.yml"
B62_CLASSIFIER = SCRIPTS / "b62_ci_impact_scope_3989.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scope = _load("ci_core_import_scope", SCRIPTS / "ci_core_import_scope.py")
classifier = _load("b62_ci_impact_scope", B62_CLASSIFIER)

SHA_A = "a" * 40
SHA_B = "b" * 40
REPO = "skerishKang/ai-revenue-lab"


def file(path: str, status: str = "modified") -> dict:
    return {"filename": path, "status": status}


def fake_event(event_type: str = "pull_request") -> dict:
    event: dict = {"repository": {"full_name": REPO}}
    if event_type == "pull_request":
        event["pull_request"] = {"base": {"sha": SHA_A}, "head": {"sha": SHA_B}}
    else:
        event.update(before=SHA_A, after=SHA_B)
    return event


def job_block(text: str, name: str) -> str:
    """Extract one workflow job block without a YAML dependency."""
    start = re.search(rf"^  {re.escape(name)}:\n", text, re.M)
    if not start:
        raise AssertionError(f"missing job: {name}")
    end = re.search(r"^  [a-z][\w-]*:\n", text[start.end():], re.M)
    return text[start.start(): start.end() + end.start() if end else len(text)]


class CoreImportScopeProof(unittest.TestCase):
    def test_shared_core_modules_stay_inside_the_product_closure(self):
        closure, _edges, names = scope._product_closure(ROOT, "b62")
        for shared in (
            "b14_execution",
            "contracts",
            "document_normalization",
            "execution_runtime",
            "orchestration",
            "web_runtime",
            # #5817: Chat composes the isolated parser over the async authority,
            # and that client shares the bounded wire with the sync client, so
            # the parser wire modules are Chat product code from here on.
            "isolated_parser_client",
        ):
            with self.subTest(shared=shared):
                self.assertIn(shared, names)
                self.assertIn(shared, closure)

    def test_independent_core_modules_are_outside_the_b62_closure(self):
        closure, _edges, names = scope._product_closure(ROOT, "b62")
        for independent in (
            "pdf_authoring",
            "workspace_storage",
        ):
            with self.subTest(independent=independent):
                self.assertIn(independent, names)
                self.assertNotIn(independent, closure)

    def test_independent_core_modules_are_outside_the_engine_closure(self):
        closure, _edges, names = scope._product_closure(ROOT, "engine")
        for independent in (
            "isolated_parser_client",
            "pdf_authoring",
            "workspace_storage",
        ):
            with self.subTest(independent=independent):
                self.assertIn(independent, names)
                self.assertNotIn(independent, closure)

    def test_removed_template_cloner_skill_is_not_a_core_module(self):
        for product in ("b62", "engine"):
            with self.subTest(product=product):
                _closure, _edges, names = scope._product_closure(ROOT, product)
                self.assertNotIn("template_cloner_skill", names)

    def test_engine_shared_core_modules_stay_inside_the_engine_closure(self):
        closure, _edges, _names = scope._product_closure(ROOT, "engine")
        for shared in (
            "b14_execution",
            "execution_runtime",
            "orchestration",
            "tool_runtime",
        ):
            with self.subTest(shared=shared):
                self.assertIn(shared, closure)

    def test_focused_plan_covers_the_changed_core_module(self):
        plan = scope.core_focused_plan(
            ROOT,
            [file("packages/padiem-ai-core/padiem_ai_core/pdf_authoring.py")],
            "b62",
        )
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertTrue(plan["independent"])
        self.assertIn("pdf_authoring", plan["modules"])
        self.assertIn("test_pdf_authoring_2827.py", plan["tests"])

    def test_focused_plan_of_a_shared_core_module_is_refused(self):
        self.assertIsNone(
            scope.core_focused_plan(
                ROOT,
                [file("packages/padiem-ai-core/padiem_ai_core/b14_execution.py")],
                "b62",
            )
        )
        self.assertIsNone(
            scope.core_focused_plan(
                ROOT,
                [file("packages/padiem-ai-core/padiem_ai_core/contracts.py")],
                "engine",
            )
        )

    def test_focused_plan_refuses_unknown_and_broken_change_sets(self):
        for broken in (
            None,
            [],
            [file("packages/padiem-ai-core/padiem_ai_core/workspace_storage.py", "deleted")],
            [file("packages/padiem-ai-core/padiem_ai_core/workspace_storage.py", "renamed")],
            [file("packages/padiem-ai-core/padiem_ai_core/__init__.py")],
            [file("packages/padiem-ai-core/tests/conftest.py")],
            [file("packages/padiem-ai-core/pyproject.toml")],
            [file("packages/padiem-ai-core/padiem_ai_core/../padiem_ai_core/contracts.py")],
            [file("apps/padiem-chat/app/chat_routes.py")],
            [file("packages/padiem-ai-core/padiem_ai_core/workspace_storage.py")] * 2,
        ):
            with self.subTest(broken=str(broken)[:70]):
                self.assertIsNone(
                    scope.core_focused_plan(
                        ROOT,
                        broken,
                        "b62",
                    )
                )

    def test_dependent_core_modules_join_the_focused_plan(self):
        # pdf_preview imports image_helpers, so an image_helpers change must
        # also run the pdf preview contracts.
        plan = scope.core_focused_plan(
            ROOT,
            [file("packages/padiem-ai-core/padiem_ai_core/image_helpers.py")],
            "b62",
        )
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertIn("image_helpers", plan["modules"])
        self.assertIn("pdf_preview", plan["modules"])
        self.assertIn("test_image_helpers_3037.py", plan["tests"])

    def test_changed_core_test_runs_its_own_module(self):
        plan = scope.core_focused_plan(
            ROOT,
            [file("packages/padiem-ai-core/tests/test_workspace_storage.py")],
            "b62",
        )
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertIn("test_workspace_storage.py", plan["tests"])

    def test_engine_shared_execution_contract_keeps_the_complete_path(self):
        # The Engine execution contract is shared, so both the Engine lane and
        # the B62 lane keep their complete regression for it.
        for shared in (
            "packages/padiem-ai-core/padiem_ai_core/execution_runtime.py",
            "packages/padiem-ai-core/padiem_ai_core/b14_execution.py",
            "packages/padiem-ai-core/padiem_ai_core/orchestration.py",
        ):
            with self.subTest(shared=shared):
                self.assertIsNone(
                    scope.core_focused_plan(ROOT, [file(shared)], "engine")
                )
                self.assertIsNone(
                    scope.core_focused_plan(ROOT, [file(shared)], "b62")
                )


class RuntimeLaneTriggers(unittest.TestCase):
    """A documentation-only change must not start a runtime regression lane."""

    def test_docs_only_changes_stay_out_of_the_runtime_lanes(self):
        for workflow_path in (B62_WORKFLOW, ENGINE_WORKFLOW):
            with self.subTest(workflow=workflow_path.name):
                text = workflow_path.read_text(encoding="utf-8")
                self.assertNotIn("docs/**", text)
                self.assertIn("packages/padiem-ai-core/**", text)

    def test_core_change_still_triggers_both_runtime_lanes(self):
        b62 = B62_WORKFLOW.read_text(encoding="utf-8")
        engine = ENGINE_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("packages/padiem-ai-core/**", b62)
        self.assertIn("packages/padiem-ai-core/**", engine)


class B62LaneWiring(unittest.TestCase):
    def setUp(self) -> None:
        self.text = B62_WORKFLOW.read_text(encoding="utf-8")

    def test_required_check_name_is_preserved(self):
        aggregate = job_block(self.text, "b62-test")
        self.assertIn("name: b62-test", aggregate)
        self.assertIn("if: always()", aggregate)
        self.assertIn("b62-core-parser-focused", aggregate)

    def test_focused_lane_keeps_every_other_job_skipped(self):
        self.assertIn("core_focused_only", self.text)
        self.assertIn("B62_CI_MODE=CORE_FOCUSED", self.text)
        self.assertIn(
            "needs.registry-ci-plan.outputs.scope == 'core_focused_only'", self.text
        )
        self.assertNotIn("core_parser_only", self.text)

    def test_focused_lane_runs_the_changed_core_contract(self):
        focused = job_block(self.text, "b62-core-parser-focused")
        self.assertIn("B62_CORE_INDEPENDENT_IMPORT_SMOKE=PASS", focused)
        self.assertIn("packages/padiem-ai-core/tests/", focused)
        self.assertIn("python -m compileall -q packages/padiem-ai-core/padiem_ai_core", focused)

    def test_core_scope_outputs_are_published(self):
        plan = job_block(self.text, "registry-ci-plan")
        self.assertIn("core_tests: ${{ steps.classify-b62.outputs.core_tests }}", plan)
        self.assertIn("core_modules: ${{ steps.classify-b62.outputs.core_modules }}", plan)


class EngineLaneWiring(unittest.TestCase):
    def setUp(self) -> None:
        self.text = ENGINE_WORKFLOW.read_text(encoding="utf-8")

    def test_engine_job_name_is_preserved(self):
        self.assertIn("engine-core-reuse:", self.text)

    def test_engine_uses_the_shared_core_import_scope_proof(self):
        self.assertIn("--core-product engine", self.text)
        self.assertIn("Classify the Core change impact for Engine", self.text)
        self.assertIn("Focused independent Core contract", self.text)
        self.assertIn("ENGINE_CORE_FOCUSED=1", self.text)

    def test_every_complete_engine_step_stays_gated_on_the_proof(self):
        heavy = (
            "Engine network-free tests",
            "Padiem AI Core full tests",
            "Python Worker bundle dry-run",
            "Real Worker/Pyodide Drive external transport probe",
        )
        for marker in heavy:
            with self.subTest(marker=marker):
                self.assertIn(marker, self.text)
        engine_steps = re.findall(
            r"if: steps\.engine-source\.outputs\.present == 'true'([^\n]*)",
            self.text,
        )
        gated = [line for line in engine_steps if "core_independent" in line]
        self.assertTrue(gated)
        complete = [line for line in gated if "core_independent != 'true'" in line]
        focused = [line for line in gated if "core_independent == 'true'" in line]
        self.assertEqual(len(focused), 1, focused)
        self.assertEqual(len(complete), len(gated) - 1, gated)

    def test_engine_classifier_keeps_the_full_path_on_unknown_changes(self):
        self.assertIn("CORE_IMPACT_SCOPE", B62_CLASSIFIER.read_text(encoding="utf-8"))
        for event_type in ("workflow_dispatch", "schedule"):
            with self.subTest(event_type=event_type):
                self.assertIsNone(
                    classifier.changed_files(
                        fake_event(), event_type, REPO, "token"
                    )
                )


class ClassifierFailClosed(unittest.TestCase):
    def test_api_ambiguity_keeps_the_complete_path(self):
        for data in (
            {"status": "behind", "files": [file("packages/padiem-ai-core/padiem_ai_core/workspace_storage.py")]},
            {"status": "ahead", "files": [file("packages/padiem-ai-core/padiem_ai_core/workspace_storage.py")] * 101},
            {"status": "ahead", "files": None},
        ):
            with self.subTest(data=str(data)[:60]):
                with patch.object(
                    classifier.urllib.request,
                    "urlopen",
                    return_value=io.BytesIO(json.dumps(data).encode()),
                ):
                    files = classifier.changed_files(
                        fake_event(), "pull_request", REPO, "token"
                    )
                self.assertIsNone(files)
                self.assertEqual(classifier.impact_scope(files), classifier.FULL)

    def test_exact_compare_proves_the_focused_core_scope(self):
        data = {
            "status": "ahead",
            "files": [file("packages/padiem-ai-core/padiem_ai_core/pdf_authoring.py")],
        }
        with patch.object(
            classifier.urllib.request,
            "urlopen",
            return_value=io.BytesIO(json.dumps(data).encode()),
        ):
            files = classifier.changed_files(fake_event(), "pull_request", REPO, "token")
        self.assertEqual(
            classifier.impact_scope(files), classifier.CORE_FOCUSED_ONLY
        )


if __name__ == "__main__":
    unittest.main()
