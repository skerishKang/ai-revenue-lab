"""#3989: preserve four EXACT real Workerd assertions while booting one isolate.

No production network or Pyodide launches here; the exact-head Linux CI runs
the real four-case Workerd smoke and records runtime duration.
"""
from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".github/scripts"
OLD_RUNNER = SCRIPTS / "b62_worker_probe_parallel.sh"
NEW_RUNNER = SCRIPTS / "b62_worker_probe_shared_runtime.sh"
CHECKER = SCRIPTS / "b62_worker_probe_shared_assertions.py"
COMBINED = ROOT / "apps/padiem-chat/worker_runtime_combined_probe.py"
WORKFLOW = ROOT / ".github/workflows/b62-padiem-chat-ci.yml"
CASES = ("timeout", "web_transport", "r2_read", "p01_binding")
OLD_SUCCESS = {
    "timeout": "WORKER_TIMEOUT_RUNTIME_PASS",
    "web_transport": "WORKER_WEB_TRANSPORT_PASS",
    "r2_read": "WORKER_R2_OBJECTBODY_READ_PASS",
    "p01_binding": "WORKER_P01_BINDING_COMPOSITION_PASS",
}
MOD_NAMES = {
    case: "worker_runtime_" + case + "_probe" for case in CASES
}

spec = importlib.util.spec_from_file_location("shared_assertions_3989", CHECKER)
assert spec is not None and spec.loader is not None
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class SharedWorkerSourceProof(unittest.TestCase):
    def test_all_four_original_result_predicates_unchanged(self):
        self.assertEqual(set(checker.REQUIRED), set(CASES))
        self.assertEqual(checker.SUCCESS, OLD_SUCCESS)
        for case in CASES:
            old = (SCRIPTS / ("b62_worker_probe_" + case + ".sh")).read_text(encoding="utf-8")
            match = re.search(r"required\s*=\s*\((.*?)\n\)", old, re.S)
            self.assertIsNotNone(match, case)
            original = ast.literal_eval("(" + match.group(1) + ")")
            self.assertEqual(checker.REQUIRED[case], original)
            self.assertIn(OLD_SUCCESS[case], old)
            passed = {key: True for key in original}
            if case in ("r2_read", "p01_binding"):
                passed["unexpected_exception"] = False
            self.assertEqual(checker.check(case, passed), OLD_SUCCESS[case])
            for name in original:
                failed = dict(passed)
                failed[name] = False
                with self.subTest(case=case, missing=name):
                    with self.assertRaises(ValueError):
                        checker.check(case, failed)
            if case in ("r2_read", "p01_binding"):
                failed = dict(passed)
                failed["unexpected_exception"] = True
                with self.assertRaises(ValueError):
                    checker.check(case, failed)

    def test_only_one_real_workerd_with_all_four_cases_and_real_origins(self):
        script = NEW_RUNNER.read_text(encoding="utf-8")
        self.assertEqual(script.count('setsid npx --yes wrangler@4.130.0 dev'), 1)
        self.assertIn('main = "worker_runtime_combined_probe.py"', script)
        self.assertIn('--port 8795 --inspector-port 9235 --persist-to "$PERSIST_DIR"', script)
        self.assertIn("for case in timeout web_transport r2_read p01_binding; do", script)
        self.assertIn('B62_PROBE_CASE="$case"', script)
        self.assertIn('B62_PROBE_RESULT_PATH="$result"', script)
        self.assertIn("B62_WORKER_PROBE_COUNT=$count", script)
        self.assertIn("B62_WORKER_PROBES=FAIL", script)
        self.assertIn("B62_WORKER_PROBES=PASS", script)
        self.assertIn("if [[ \"$code\" == '200' ]]", script)
        self.assertIn("if [[ \"$READY\" -ne 1 ]]", script)
        self.assertIn("uv run --locked python tests/worker_runtime_probe_origin.py --port 9099", script)
        self.assertIn("uv run --locked python tests/worker_runtime_probe_origin.py --port 9100", script)
        self.assertIn('kill -TERM -- "-$WORKER_PID"', script)
        self.assertIn('kill -KILL -- "-$WORKER_PID"', script)
        self.assertLess(script.index("r2_read p01_binding"), script.index("B62_WORKER_PROBES=PASS"))

    def test_original_four_scripts_still_exist_and_can_run_standalone(self):
        original = OLD_RUNNER.read_text(encoding="utf-8")
        self.assertIn('exec bash "$SOURCE_DIR/b62_worker_probe_shared_runtime.sh"', original)
        self.assertIn('if (( $# == 0 )); then', original)
        self.assertIn('for index in 0 1 2 3; do', original)
        self.assertIn('npx --yes wrangler@4.130.0 --version', original)
        for case in CASES:
            old = (SCRIPTS / ("b62_worker_probe_" + case + ".sh")).read_text(encoding="utf-8")
            self.assertIn('setsid npx --yes wrangler@4.130.0 dev', old)
            self.assertIn("trap cleanup EXIT", old)

    def test_ci_retains_lock_vendor_prewarm_and_bundle_checks(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("four assertions, one Workerd, fail-closed", source)
        self.assertIn("run: bash ../../.github/scripts/b62_worker_probe_parallel.sh", source)
        self.assertIn('b62_worker_probe_shared_assertions.py', source)
        self.assertIn('b62_worker_probe_*.sh', source)
        self.assertIn("Pywrangler dependency sync from committed pylock", source)
        self.assertIn("Verify vendored Worker dependency versions", source)
        self.assertIn("Python Worker bundle dry-run", source)
        self.assertIn("b62-test", source)
        self.assertIn('test_3989_b62_worker_shared_runtime.py',
                      source)

    def test_unknown_cases_and_incomplete_json_fail_closed(self):
        for bad in ("unknown", "", "TIMEOUT"):
            with self.subTest(case=bad):
                with self.assertRaises(ValueError):
                    checker.check(bad, {})
        for case in CASES:
            with self.subTest(case=case):
                with self.assertRaises(ValueError):
                    checker.check(case, [])
                with self.assertRaises(ValueError):
                    checker.check(case, {})


class SharedWorkerRoutingProof(unittest.IsolatedAsyncioTestCase):
    async def test_real_request_propagation_and_reject_unknown_cases(self):
        calls = []
        fake = {}
        fake_workers = ModuleType("workers")

        class Response:
            def __init__(self, text, status=200):
                self.text, self.status = text, status

        fake_workers.WorkerEntrypoint = object
        fake_workers.Response = Response
        fake["workers"] = fake_workers
        for case, name in MOD_NAMES.items():
            mod = ModuleType(name)
            async def handler(_, request, label=case):
                calls.append((label, request))
                return Response(label, status=200)
            mod.Default = type("Default", (), {"fetch": handler})
            fake[name] = mod

        worker_spec = importlib.util.spec_from_file_location(
            "worker_runtime_combined_probe_test", COMBINED)
        assert worker_spec is not None and worker_spec.loader is not None
        with patch.dict(sys.modules, fake):
            worker = importlib.util.module_from_spec(worker_spec)
            worker_spec.loader.exec_module(worker)
        self.assertEqual(set(worker.PROBES), set(CASES))
        instance = worker.Default()
        for case in CASES:
            request = SimpleNamespace(url=f"http://127.0.0.1/probe?case={case}")
            reply = await instance.fetch(request)
            self.assertEqual(reply.status, 200)
            self.assertEqual(reply.text, case)
            self.assertIs(calls[-1][1], request)
        for url in ("http://localhost/probe", "http://localhost/probe?case=invalid",
                    "http://localhost/probe?case=timeout&case=r2_read",
                    "http://localhost/probe?case=timeout&other=1",
                    "http://localhost/probe?case="):
            reply = await instance.fetch(SimpleNamespace(url=url))
            self.assertEqual(reply.status, 400, url)
        reply = await instance.fetch(SimpleNamespace(url="http://localhost/ready"))
        self.assertEqual(reply.status, 200)
        reply = await instance.fetch(SimpleNamespace(url="http://localhost/anything"))
        self.assertEqual(reply.status, 404)


if __name__ == "__main__":
    unittest.main()
